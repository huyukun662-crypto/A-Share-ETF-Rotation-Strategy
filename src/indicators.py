"""Technical indicators and performance / diagnostic metrics.

Core signals
------------
- **LogBias**:   `(log(close) - log(EMA)) * 100`  — log-space deviation from trend
- **RSI(14)**:   Wilder's RSI on closing prices
- **logbias_slope**: 5-day change in LogBias (momentum of the deviation)
- **relative_strength**: 20-day return minus benchmark 20-day return

Also exposes equity-curve and trade-level performance metrics.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .config import BEST_OOS_BASELINE_PARAMS


# ---------------------------------------------------------------------------
# Primary indicators
# ---------------------------------------------------------------------------
def calculate_indicators(df: pd.DataFrame, ema_window: int, slope_lookback: int = 5) -> pd.DataFrame:
    """Attach LogBias, price-EMA, 20-day return and slope to a price frame."""
    out = df.copy()
    out["log_close"] = np.log(out["close"])
    out["log_ema"] = out["log_close"].ewm(span=ema_window, adjust=False, min_periods=ema_window).mean()
    out["logbias"] = (out["log_close"] - out["log_ema"]) * 100
    out["price_ema"] = out["close"].ewm(span=ema_window, adjust=False, min_periods=ema_window).mean()
    out["ret_20"] = out["close"].pct_change(20)
    out["logbias_slope"] = out["logbias"] - out["logbias"].shift(slope_lookback)
    return out


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss.ne(0), 100)
    rsi = rsi.where(avg_gain.ne(0), 0)
    return rsi


# ---------------------------------------------------------------------------
# NAV helpers
# ---------------------------------------------------------------------------
def build_benchmark_curve(benchmark_df: pd.DataFrame) -> pd.DataFrame:
    out = benchmark_df[["date", "close"]].dropna().sort_values("date").copy()
    out["benchmark_nav"] = out["close"] / out["close"].iloc[0]
    return out[["date", "benchmark_nav"]]


def build_drawdown_series(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


# ---------------------------------------------------------------------------
# Diagnostic metrics
# ---------------------------------------------------------------------------
def calculate_equity_diagnostics(equity_curve: pd.DataFrame) -> Dict[str, float]:
    if equity_curve is None or equity_curve.empty:
        return {
            "avg_exposure": 0.0,
            "peak_exposure": 0.0,
            "days_exposure_above_0_9": 0,
            "worst_month_return": 0.0,
            "worst_window_avg_exposure": 0.0,
        }

    out = equity_curve.copy()
    out["drawdown"] = build_drawdown_series(out["nav"])
    out["month"] = out["date"].dt.to_period("M")
    monthly = out.groupby("month")["nav"].agg(["first", "last"])
    monthly_return = monthly["last"] / monthly["first"] - 1.0

    worst_idx = out["drawdown"].idxmin()
    peak_idx = out.loc[:worst_idx, "nav"].idxmax()
    worst_window = out.loc[peak_idx:worst_idx]

    return {
        "avg_exposure": float(out["exposure"].mean()),
        "peak_exposure": float(out["exposure"].max()),
        "days_exposure_above_0_9": int((out["exposure"] > 0.9).sum()),
        "worst_month_return": float(monthly_return.min()) if not monthly_return.empty else 0.0,
        "worst_window_avg_exposure": float(worst_window["exposure"].mean()) if not worst_window.empty else 0.0,
    }


def calculate_performance_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_capital: float,
    benchmark_curve: Optional[pd.DataFrame],
) -> Dict[str, float]:
    if equity_curve.empty:
        return {
            "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
            "sharpe_ratio": -np.inf, "calmar_ratio": 0.0,
            "win_rate": np.nan, "avg_hold_days": np.nan,
            "turnover": 0.0, "avg_exposure": 0.0, "min_exposure": 0.0,
            "excess_return": np.nan, "annual_excess_return": np.nan,
        }

    nav = equity_curve["nav"]
    daily_ret = nav.pct_change().fillna(0.0)
    total_days = max(len(nav), 1)
    total_return = float(nav.iloc[-1] - 1.0)
    annual_return = float(nav.iloc[-1] ** (252 / total_days) - 1.0) if total_days > 1 else 0.0
    max_drawdown = float(build_drawdown_series(nav).min()) if len(nav) > 0 else 0.0
    sharpe = float(daily_ret.mean() / daily_ret.std(ddof=0) * np.sqrt(252)) if daily_ret.std(ddof=0) > 0 else -np.inf
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    closed_trades = trades[trades["exit_date"].notna()].copy() if not trades.empty else pd.DataFrame()
    win_rate = float((closed_trades["trade_return"] > 0).mean()) if not closed_trades.empty else np.nan
    avg_hold_days = float(closed_trades["holding_days"].mean()) if not closed_trades.empty else np.nan
    turnover = float(equity_curve["turnover"].sum() / max(equity_curve["equity"].mean(), initial_capital))

    metrics = {
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe if not np.isnan(sharpe) else -np.inf,
        "calmar_ratio": calmar,
        "win_rate": win_rate,
        "avg_hold_days": avg_hold_days,
        "turnover": turnover,
        "avg_exposure": float(equity_curve["exposure"].mean()),
        "min_exposure": float(equity_curve["exposure"].min()),
        "excess_return": np.nan,
        "annual_excess_return": np.nan,
    }

    if benchmark_curve is not None and not benchmark_curve.empty:
        merged = equity_curve[["date", "nav"]].merge(benchmark_curve, on="date", how="left")
        merged["benchmark_nav"] = merged["benchmark_nav"].ffill().bfill()
        merged = merged.dropna(subset=["nav", "benchmark_nav"])
        if not merged.empty:
            excess_curve = merged["nav"] / merged["benchmark_nav"]
            metrics["excess_return"] = float(excess_curve.iloc[-1] - 1.0)
            metrics["annual_excess_return"] = float(excess_curve.iloc[-1] ** (252 / len(merged)) - 1.0) if len(merged) > 1 else 0.0

    return metrics


def calculate_panel_diagnostics(panel: Dict[str, pd.DataFrame], equity_curve: pd.DataFrame) -> Dict[str, float]:
    if not panel:
        return {
            "hard_signal_days_ratio": 0.0,
            "soft_signal_days_ratio": 0.0,
            "invested_days_ratio": 0.0,
            "avg_candidate_count": 0.0,
            "avg_soft_candidate_count": 0.0,
        }

    hard_counts, soft_counts = [], []
    all_dates = sorted(set().union(*[set(df["date"]) for df in panel.values()]))
    for date in all_dates:
        hard_count, soft_count = 0, 0
        for df in panel.values():
            row = df[df["date"] == date]
            if row.empty:
                continue
            row = row.iloc[0]
            if bool(row["rotation_candidate"]):
                hard_count += 1
            if bool(row["soft_candidate"]):
                soft_count += 1
        hard_counts.append(hard_count)
        soft_counts.append(soft_count)

    invested_days_ratio = float((equity_curve["exposure"] > 0.01).mean()) if not equity_curve.empty else 0.0
    return {
        "hard_signal_days_ratio": float(np.mean(np.array(hard_counts) > 0)) if hard_counts else 0.0,
        "soft_signal_days_ratio": float(np.mean(np.array(soft_counts) > 0)) if soft_counts else 0.0,
        "invested_days_ratio": invested_days_ratio,
        "avg_candidate_count": float(np.mean(hard_counts)) if hard_counts else 0.0,
        "avg_soft_candidate_count": float(np.mean(soft_counts)) if soft_counts else 0.0,
    }


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def calculate_param_distance(params: Dict[str, object]) -> float:
    """L1 distance of a candidate parameter dict from the baseline — used as a tie-breaker."""
    baseline = BEST_OOS_BASELINE_PARAMS
    distance = 0.0
    numeric_keys = [
        "ema_window", "rsi_entry", "rsi_exit",
        "stock_entry_shift", "commodity_entry_shift", "dividend_entry_shift",
        "stock_soft_shift", "commodity_soft_shift", "dividend_soft_shift",
        "stock_stop_shift", "commodity_stop_shift", "dividend_stop_shift",
        "strong_days_shift",
    ]
    for key in numeric_keys:
        distance += abs(float(params[key]) - float(baseline[key]))
    categorical_keys = ["use_relative_strength_filter", "exposure_map_version"]
    for key in categorical_keys:
        distance += 1.0 if params[key] != baseline[key] else 0.0
    return distance


def build_category_shift_map(stock_value: float, commodity_value: float, dividend_value: float) -> Dict[str, float]:
    return {
        "stock": float(stock_value),
        "commodity": float(commodity_value),
        "dividend": float(dividend_value),
    }


def calc_trade_price(open_price: float, slippage_rate: float, side: str) -> float:
    return open_price * (1 + slippage_rate) if side == "buy" else open_price * (1 - slippage_rate)


def calc_transaction_cost(amount: float, fee_rate: float, stamp_duty_rate: float, side: str) -> float:
    cost = amount * fee_rate
    if side == "sell":
        cost += amount * stamp_duty_rate
    return cost
