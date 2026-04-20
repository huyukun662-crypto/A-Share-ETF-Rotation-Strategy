"""Backtester: RSIRotationBacktester.

Weekly rebalancing over a multi-category ETF panel with daily hard-exit
and soft-trim risk controls. Supports a defensive (cash or bond)
allocation that kicks in once the live equity drawdown exceeds a trigger.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .config import ASSET_CATEGORY_MAP, BOND_CLASS_MAP, StrategyConfig, SYMBOL_NAME_MAP
from .indicators import (
    build_benchmark_curve,
    calc_trade_price,
    calc_transaction_cost,
    calculate_performance_metrics,
)


class RSIRotationBacktester:
    """Weekly-rebalanced ETF rotation backtester with RSI + LogBias signals."""

    def __init__(self, config: StrategyConfig):
        self.config = config

    # --- market-view construction --------------------------------------
    @staticmethod
    def _build_market_view(panel: Dict[str, pd.DataFrame]) -> Dict[pd.Timestamp, Dict[str, Dict]]:
        market_view = {}
        for symbol, df in panel.items():
            for _, row in df.iterrows():
                market_view.setdefault(row["date"], {})
                market_view[row["date"]][symbol] = row.to_dict()
        return market_view

    @staticmethod
    def _should_rebalance(date: pd.Timestamp, next_date: pd.Timestamp) -> bool:
        """True when `date` and `next_date` fall in different ISO weeks."""
        current_iso, next_iso = date.isocalendar(), next_date.isocalendar()
        return (current_iso.year, current_iso.week) != (next_iso.year, next_iso.week)

    # --- exposure control -----------------------------------------------
    def _candidate_based_exposure(self, hard_count: int) -> float:
        for min_count, exposure in self.config.candidate_exposure_map:
            if hard_count >= min_count:
                return exposure
        return 0.0

    def _get_drawdown_exposure_cap(self, equity: float, equity_peak: float) -> float:
        """Three-tier drawdown-based exposure cap."""
        if equity_peak <= 0:
            return self.config.portfolio_exposure_cap
        dd = equity / equity_peak - 1.0
        if dd <= self.config.dd_limit_3:
            return min(self.config.dd_cap_3, self.config.portfolio_exposure_cap)
        if dd <= self.config.dd_limit_2:
            return min(self.config.dd_cap_2, self.config.portfolio_exposure_cap)
        if dd <= self.config.dd_limit_1:
            return min(self.config.dd_cap_1, self.config.portfolio_exposure_cap)
        return self.config.portfolio_exposure_cap

    def _get_defensive_allocation_cap(self, equity: float, equity_peak: float) -> float:
        if self.config.defensive_mode not in {"cash", "bond"}:
            return 0.0
        if equity_peak <= 0:
            return 0.0
        dd = equity / equity_peak - 1.0
        if dd <= self.config.defensive_trigger_dd:
            return self.config.defensive_allocation_cap
        return 0.0

    # --- target weights --------------------------------------------------
    def _generate_target_weights(
        self,
        daily_map: Dict[str, Dict],
        open_trades: Dict[str, Dict],
        exposure_cap: float,
        defensive_cap: float,
    ) -> Dict[str, float]:
        ranked, soft_ranked = [], []
        for symbol, row in daily_map.items():
            if not row["is_trading"]:
                continue
            if bool(row.get("rotation_candidate", False)):
                ranked.append((symbol, row["rotation_score"]))
            elif bool(row.get("soft_candidate", False)):
                soft_ranked.append((symbol, row["rotation_score"]))

        ranked.sort(key=lambda x: x[1], reverse=True)
        soft_ranked.sort(key=lambda x: x[1], reverse=True)

        desired_count = self.config.top_n
        hard_count = len(ranked)
        if self.config.dynamic_holdings:
            if hard_count > 0:
                desired_count = min(max(hard_count, self.config.min_holdings), self.config.max_holdings)
            elif open_trades:
                desired_count = min(max(len(open_trades), self.config.min_holdings), self.config.max_holdings)
            else:
                desired_count = 0

        selected = []
        for symbol, _ in ranked:
            if len(selected) >= desired_count:
                break
            selected.append(symbol)

        for symbol in list(open_trades.keys()):
            if len(selected) >= desired_count:
                break
            if symbol not in selected and symbol in daily_map:
                row = daily_map[symbol]
                keep_cond = (
                    row.get("logbias", -99.0) > row.get("category_stop_threshold", -5.0)
                    and row.get("rsi14", 0.0) > 47
                )  # Keep 47 here: current runtime follows StrategyConfig defaults, not the separately saved optimized search parameters.
                if keep_cond:
                    selected.append(symbol)

        for symbol, _ in soft_ranked:
            if len(selected) >= desired_count:
                break
            if symbol not in selected:
                selected.append(symbol)

        if not selected:
            target_weights = {}
        else:
            target_exposure = min(self._candidate_based_exposure(hard_count), exposure_cap)
            target_weights = {symbol: target_exposure / len(selected) for symbol in selected}

        if self.config.defensive_mode != "bond" or defensive_cap is None or defensive_cap <= 0:
            return target_weights

        allocated_weight = float(sum(target_weights.values()))
        available_defensive_weight = min(max(exposure_cap - allocated_weight, 0.0), defensive_cap)
        if available_defensive_weight <= 0:
            return target_weights

        defensive_symbols = [
            symbol for symbol, row in daily_map.items()
            if symbol in BOND_CLASS_MAP and row.get("is_trading", False) and pd.notna(row.get("open"))
        ]
        if not defensive_symbols:
            return target_weights

        defensive_weight = available_defensive_weight / len(defensive_symbols)
        for symbol in defensive_symbols:
            target_weights[symbol] = defensive_weight
        return target_weights

    # --- book-keeping helpers -------------------------------------------
    def _close_trade(self, open_trade: Dict, exit_date: pd.Timestamp, exit_price: float, exit_reason: str) -> Dict:
        trade = dict(open_trade)
        trade["exit_date"] = exit_date
        trade["exit_price"] = exit_price
        trade["exit_reason"] = exit_reason
        trade["holding_days"] = int((exit_date - trade["entry_date"]).days)
        trade["trade_return"] = exit_price / trade["entry_price"] - 1.0
        return trade

    @staticmethod
    def _build_buy_signal_snapshot(
        signal_date: pd.Timestamp,
        execution_date: Optional[pd.Timestamp],
        daily_map: Dict[str, Dict],
        target_weights: Dict[str, float],
    ) -> Optional[Dict[str, object]]:
        allocations = []
        for symbol, weight in sorted(target_weights.items(), key=lambda x: x[1], reverse=True):
            if weight <= 0:
                continue
            row = daily_map.get(symbol, {})
            allocations.append({
                "symbol": symbol,
                "name": SYMBOL_NAME_MAP.get(symbol, symbol),
                "category": ASSET_CATEGORY_MAP.get(symbol, ""),
                "weight": float(weight),
                "rotation_candidate": bool(row.get("rotation_candidate", False)),
                "soft_candidate": bool(row.get("soft_candidate", False)),
            })
        if not allocations:
            return None
        return {
            "signal_date": signal_date,
            "execution_date": execution_date,
            "allocations": allocations,
        }

    @staticmethod
    def _compute_weight_map(daily_map: Dict[str, Dict], positions: Dict[str, float], cash: float) -> Dict[str, float]:
        position_values = {}
        total_equity = float(cash)
        for symbol, qty in positions.items():
            row = daily_map.get(symbol)
            if row is None or pd.isna(row.get("close")):
                continue
            value = float(qty * row["close"])
            if value <= 1e-12:
                continue
            position_values[symbol] = value
            total_equity += value
        if total_equity <= 0:
            return {}
        return {symbol: value / total_equity for symbol, value in position_values.items()}

    def _build_trade_plan_snapshot(
        self,
        signal_date: pd.Timestamp,
        execution_date: Optional[pd.Timestamp],
        daily_map: Dict[str, Dict],
        positions: Dict[str, float],
        open_trades: Dict[str, Dict],
        cash: float,
        should_weekly_rotate: bool,
        weekly_target_weights: Dict[str, float],
        exposure_cap: Optional[float],
        defensive_cap: Optional[float],
    ) -> Dict[str, object]:
        current_weights = self._compute_weight_map(daily_map, positions, cash)
        risk_target_weights = dict(current_weights)
        trigger_types: Dict[str, set] = {}
        summary_triggers: list = []

        for symbol in list(current_weights.keys()):
            row = daily_map.get(symbol)
            if row is None or not row.get("is_trading", False) or pd.isna(row.get("close")):
                continue

            exit_rsi = row.get("exit_rsi_threshold", 45)
            should_clear = (
                row.get("logbias", np.nan) < row.get("category_stop_threshold", -5.0)
                or (row.get("close", np.nan) < row.get("price_ema", np.nan) and row.get("rsi14", 100.0) < exit_rsi)
            )
            soft_trim = bool(
                self.config.enable_overheat_trim
                and (
                    (row.get("rsi14", 0.0) > 78 and not bool(row.get("rsi_up", True)))
                    or (
                        row.get("logbias", 0.0) > row.get("category_overheat_threshold", 15.0)
                        and row.get("logbias_slope", 0.0) < 0
                    )
                )
            )

            if should_clear:
                risk_target_weights[symbol] = 0.0
                trigger_types.setdefault(symbol, set()).add("hard_exit")
                if "hard_exit" not in summary_triggers:
                    summary_triggers.append("hard_exit")
            elif soft_trim:
                risk_target_weights[symbol] = current_weights.get(symbol, 0.0) * (1.0 - self.config.trim_ratio)
                trigger_types.setdefault(symbol, set()).add("soft_trim")
                if "soft_trim" not in summary_triggers:
                    summary_triggers.append("soft_trim")

        final_target_weights = dict(risk_target_weights)
        if should_weekly_rotate:
            final_target_weights = dict(weekly_target_weights)
            if "weekly_rebalance" not in summary_triggers:
                summary_triggers.append("weekly_rebalance")
            for symbol, symbol_triggers in trigger_types.items():
                if "hard_exit" in symbol_triggers:
                    final_target_weights[symbol] = 0.0
                elif "soft_trim" in symbol_triggers:
                    final_target_weights[symbol] = min(
                        final_target_weights.get(symbol, 0.0),
                        risk_target_weights.get(symbol, 0.0),
                    )

        all_symbols = set(current_weights) | set(final_target_weights)
        rows = []
        for symbol in all_symbols:
            current_weight = float(current_weights.get(symbol, 0.0))
            target_weight = float(final_target_weights.get(symbol, 0.0))
            if current_weight <= 1e-10 and target_weight <= 1e-10:
                continue

            delta_weight = target_weight - current_weight
            symbol_trigger_types = set(trigger_types.get(symbol, set()))
            if should_weekly_rotate:
                symbol_trigger_types.add("weekly_rebalance")

            if current_weight <= 1e-10 and target_weight > 1e-10:
                action = f"调入，增加 {target_weight:.2%}"
            elif current_weight > 1e-10 and target_weight <= 1e-10:
                action = f"退出，减少 {abs(delta_weight):.2%}"
            elif delta_weight > 1e-10:
                action = f"加仓，增加 {delta_weight:.2%}"
            elif delta_weight < -1e-10:
                action = f"减仓，减少 {abs(delta_weight):.2%}"
            else:
                action = "持有不变"

            rows.append({
                "symbol": symbol,
                "name": SYMBOL_NAME_MAP.get(symbol, symbol),
                "current_weight": current_weight,
                "target_weight": target_weight,
                "delta_weight": delta_weight,
                "action": action,
                "trigger_type": ",".join(sorted(symbol_trigger_types)) if symbol_trigger_types else "none",
            })

        rows.sort(key=lambda item: (-item["target_weight"], -item["current_weight"], item["symbol"]))

        return {
            "signal_date": signal_date,
            "execution_date": execution_date,
            "current_weights": current_weights,
            "target_weights": {r["symbol"]: r["target_weight"] for r in rows},
            "delta_weights": {r["symbol"]: r["delta_weight"] for r in rows},
            "trigger_types": {r["symbol"]: r["trigger_type"] for r in rows},
            "actions": {r["symbol"]: r["action"] for r in rows},
            "summary_triggers": summary_triggers,
            "rows": rows,
            "exposure_cap": exposure_cap,
            "defensive_cap": defensive_cap,
        }

    # --- order execution ------------------------------------------------
    def _execute_target_weights(self, date, daily_map, cash, positions, target_weights, open_trades):
        closed_trades = []
        turnover_today = 0.0
        total_value = cash + sum(
            qty * (daily_map[s]["open"] if pd.notna(daily_map[s]["open"]) else daily_map[s]["close"])
            for s, qty in positions.items()
        )

        # Sells first
        for symbol in list(positions.keys()):
            row = daily_map.get(symbol)
            if row is None or not row["is_trading"] or pd.isna(row["open"]):
                continue
            current_value = positions[symbol] * row["open"]
            target_value = total_value * target_weights.get(symbol, 0.0)
            diff = target_value - current_value
            if diff >= 0:
                continue
            sell_price = calc_trade_price(row["open"], self.config.slippage_rate, "sell")
            sell_qty = min(-diff / sell_price, positions[symbol])
            amount = sell_qty * sell_price
            cost = calc_transaction_cost(amount, self.config.fee_rate, self.config.stamp_duty_rate, "sell")
            cash += amount - cost
            turnover_today += amount
            positions[symbol] -= sell_qty
            if positions[symbol] <= 1e-8:
                closed_trades.append(self._close_trade(open_trades.pop(symbol), date, sell_price, "rotation_rebalance"))
                del positions[symbol]

        # Buys second
        for symbol, weight in target_weights.items():
            row = daily_map.get(symbol)
            if row is None or not row["is_trading"] or pd.isna(row["open"]):
                continue
            target_value = total_value * weight
            current_value = positions.get(symbol, 0.0) * row["open"]
            diff = target_value - current_value
            if diff <= 0:
                continue
            buy_price = calc_trade_price(row["open"], self.config.slippage_rate, "buy")
            available_amount = cash / (1 + self.config.fee_rate)
            buy_amount = min(diff, available_amount)
            if buy_amount <= 0:
                continue
            buy_qty = buy_amount / buy_price
            amount = buy_qty * buy_price
            cost = calc_transaction_cost(amount, self.config.fee_rate, self.config.stamp_duty_rate, "buy")
            if amount + cost > cash:
                continue
            cash -= amount + cost
            turnover_today += amount
            positions[symbol] = positions.get(symbol, 0.0) + buy_qty
            if symbol not in open_trades:
                open_trades[symbol] = {
                    "symbol": symbol,
                    "entry_date": date,
                    "entry_price": buy_price,
                    "entry_reason": "defensive_entry" if symbol in BOND_CLASS_MAP else "rotation_entry",
                }

        return cash, positions, turnover_today, closed_trades

    def _apply_daily_risk_controls(self, date, daily_map, cash, positions, open_trades):
        closed = []
        for symbol in list(positions.keys()):
            row = daily_map.get(symbol)
            if row is None or not row["is_trading"] or pd.isna(row.get("open")):
                continue
            qty = positions[symbol]
            if qty <= 0:
                continue

            exit_rsi = row.get("exit_rsi_threshold", 45)
            should_clear = (
                row.get("logbias", np.nan) < row.get("category_stop_threshold", -5.0)
                or (row.get("close", np.nan) < row.get("price_ema", np.nan) and row.get("rsi14", 100.0) < exit_rsi)
            )
            soft_trim = bool(
                self.config.enable_overheat_trim
                and (
                    (row.get("rsi14", 0.0) > 78 and not bool(row.get("rsi_up", True)))
                    or (
                        row.get("logbias", 0.0) > row.get("category_overheat_threshold", 15.0)
                        and row.get("logbias_slope", 0.0) < 0
                    )
                )
            )
            if not should_clear and not soft_trim:
                continue

            ratio = 1.0 if should_clear else self.config.trim_ratio
            sell_qty = qty * ratio
            sell_price = calc_trade_price(row["open"], self.config.slippage_rate, "sell")
            amount = sell_qty * sell_price
            cost = calc_transaction_cost(amount, self.config.fee_rate, self.config.stamp_duty_rate, "sell")
            cash += amount - cost
            positions[symbol] -= sell_qty
            if positions[symbol] <= 1e-8:
                closed.append(self._close_trade(open_trades.pop(symbol), date, sell_price, "rsi_exit" if should_clear else "rsi_trim"))
                del positions[symbol]

        return cash, positions, closed

    # --- main loop -------------------------------------------------------
    def run(
        self,
        panel: Dict[str, pd.DataFrame],
        benchmark_df: Optional[pd.DataFrame] = None,
        defensive_panel: Optional[Dict[str, pd.DataFrame]] = None,
    ):
        merged_panel = dict(panel)
        if defensive_panel:
            merged_panel.update(defensive_panel)
        market_view = self._build_market_view(merged_panel)
        dates = sorted(market_view.keys())
        cash = self.config.initial_capital
        equity_peak = self.config.initial_capital
        positions: Dict[str, float] = {}
        open_trades: Dict[str, Dict] = {}
        pending_weights = None
        latest_buy_signal = None
        latest_trade_plan = None
        trade_records: list = []
        equity_records: list = []

        for idx, date in enumerate(dates):
            daily_map = market_view[date]
            turnover_today = 0.0

            # Daily hard-exit / soft-trim risk controls
            if self.config.enable_daily_stop and positions:
                cash, positions, daily_closed = self._apply_daily_risk_controls(date, daily_map, cash, positions, open_trades)
                trade_records.extend(daily_closed)

            # Execute weekly rebalance from the previous day's signal
            if pending_weights is not None:
                cash, positions, rebalance_turnover, closed = self._execute_target_weights(
                    date, daily_map, cash, positions, pending_weights, open_trades
                )
                turnover_today += rebalance_turnover
                trade_records.extend(closed)
                pending_weights = None

            equity = cash + sum(qty * daily_map[s]["close"] for s, qty in positions.items())
            equity_peak = max(equity_peak, equity)
            exposure = 0.0 if equity <= 0 else max(equity - cash, 0.0) / equity
            equity_records.append({
                "date": date,
                "equity": equity,
                "nav": equity / self.config.initial_capital,
                "cash": cash,
                "position_value": equity - cash,
                "exposure": exposure,
                "turnover": turnover_today,
            })

            # Decide whether to generate a new weekly signal for next-day execution
            next_trade_date = dates[idx + 1] if idx < len(dates) - 1 else None
            should_weekly_rotate = False
            if idx < len(dates) - 1 and self._should_rebalance(date, dates[idx + 1]):
                should_weekly_rotate = True
            elif pd.Timestamp(date).weekday() == 4:
                should_weekly_rotate = True

            exposure_cap = None
            defensive_cap = None
            weekly_target_weights: Dict[str, float] = {}
            if should_weekly_rotate:
                exposure_cap = self._get_drawdown_exposure_cap(equity, equity_peak)
                defensive_cap = self._get_defensive_allocation_cap(equity, equity_peak)
                weekly_target_weights = self._generate_target_weights(daily_map, open_trades, exposure_cap, defensive_cap)
                pending_weights = weekly_target_weights
                latest_buy_signal = self._build_buy_signal_snapshot(
                    signal_date=date,
                    execution_date=next_trade_date,
                    daily_map=daily_map,
                    target_weights=weekly_target_weights,
                )

            latest_trade_plan = self._build_trade_plan_snapshot(
                signal_date=date,
                execution_date=next_trade_date,
                daily_map=daily_map,
                positions=positions,
                open_trades=open_trades,
                cash=cash,
                should_weekly_rotate=should_weekly_rotate,
                weekly_target_weights=weekly_target_weights,
                exposure_cap=exposure_cap,
                defensive_cap=defensive_cap,
            )

        # Force-close any surviving open trades for accounting
        if open_trades and dates:
            last_map = market_view[dates[-1]]
            last_date = dates[-1]
            for symbol, trade in list(open_trades.items()):
                trade_records.append(self._close_trade(trade, last_date, last_map[symbol]["close"], "forced_close"))

        equity_curve = pd.DataFrame(equity_records)
        trades_df = pd.DataFrame(trade_records)
        benchmark_curve = build_benchmark_curve(benchmark_df) if benchmark_df is not None else None
        metrics = calculate_performance_metrics(equity_curve, trades_df, self.config.initial_capital, benchmark_curve)
        return equity_curve, trades_df, metrics, latest_buy_signal, latest_trade_plan
