"""Signal panel construction and trade-plan / holdings reporting helpers.

`prepare_panel_rsi_only` turns a dict of aligned per-symbol OHLCV frames into
a signal panel with hard/soft candidacy flags, category-specific thresholds
and a composite `rotation_score`.  The remaining helpers format the latest
signal / next-trade-day holdings for on-screen display and CSV export.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .config import (
    BOND_CLASS_MAP,
    ENTRY,
    OVERHEAT,
    SOFT,
    STOP,
    STRONG,
    StrategyConfig,
    SYMBOL_NAME_MAP,
    THREE_CLASS_MAP,
)
from .indicators import calc_rsi, calculate_indicators


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------
def prepare_panel_rsi_only(
    aligned: Dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    config: StrategyConfig,
    rsi_entry: float,
    rsi_exit: float,
    entry_shifts: Dict[str, float],
    soft_shifts: Dict[str, float],
    stop_shifts: Dict[str, float],
) -> Dict[str, pd.DataFrame]:
    """Build a per-symbol DataFrame of signals, thresholds and rotation scores."""
    bench = benchmark_df[["date", "close"]].copy().sort_values("date")
    bench["benchmark_ret20"] = bench["close"].pct_change(20)

    panel: Dict[str, pd.DataFrame] = {}
    for symbol, df in aligned.items():
        category = THREE_CLASS_MAP.get(symbol)
        if category is None:
            continue

        tmp = calculate_indicators(df, ema_window=config.ema_window)
        tmp["rsi14"] = calc_rsi(tmp["close"], 14)
        tmp["rsi_up"] = tmp["rsi14"] > tmp["rsi14"].shift(1)
        tmp = tmp.merge(bench[["date", "benchmark_ret20"]], on="date", how="left")
        tmp["benchmark_ret20"] = tmp["benchmark_ret20"].ffill().fillna(0.0)
        tmp["relative_strength"] = tmp["ret_20"] - tmp["benchmark_ret20"]

        tmp["category_entry_threshold"] = ENTRY[category] + entry_shifts[category]
        tmp["category_stop_threshold"] = STOP[category] + stop_shifts[category]
        tmp["category_overheat_threshold"] = OVERHEAT[category]
        tmp["category_soft_entry_threshold"] = SOFT[category] + soft_shifts[category]
        min_strong_days = max(1, STRONG[category] + config.strong_days_required_shift)
        tmp["strong_days_10"] = (
            (tmp["logbias"] > tmp["category_entry_threshold"])
            .rolling(10, min_periods=1)
            .sum()
        )

        relative_strength_filter = (
            tmp["relative_strength"].gt(0) if config.use_relative_strength_filter else True
        )
        tmp["rotation_candidate"] = (
            tmp["logbias"].gt(tmp["category_entry_threshold"])
            & tmp["strong_days_10"].ge(min_strong_days)
            & tmp["close"].gt(tmp["price_ema"])
            & relative_strength_filter
            & tmp["logbias"].le(tmp["category_overheat_threshold"])
            & tmp["rsi14"].gt(rsi_entry)
            & tmp["is_trading"]
        )
        tmp["soft_candidate"] = (
            tmp["close"].gt(tmp["price_ema"])
            & tmp["logbias"].gt(tmp["category_soft_entry_threshold"])
            & tmp["rsi14"].gt(max(50, rsi_entry - 2))
            & tmp["is_trading"]
        )
        tmp["exit_rsi_threshold"] = rsi_exit
        tmp["rotation_score"] = (
            config.score_weight_logbias * tmp["logbias"]
            + config.score_weight_slope * tmp["logbias_slope"]
            + config.score_weight_ret20 * (tmp["ret_20"] * 100)
            + config.score_weight_relative_strength * (tmp["relative_strength"] * 100)
            + 0.10 * (tmp["rsi14"] - 50)
        )

        panel[symbol] = tmp[
            [
                "date", "open", "close", "is_trading", "price_ema",
                "logbias", "ret_20", "logbias_slope", "rsi14", "rsi_up",
                "relative_strength", "strong_days_10",
                "category_entry_threshold", "category_stop_threshold",
                "category_overheat_threshold", "category_soft_entry_threshold",
                "exit_rsi_threshold", "rotation_candidate", "soft_candidate",
                "rotation_score",
            ]
        ].copy()
    return panel


def prepare_defensive_bond_panel(aligned: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Slim OHLC panel for bond ETFs used as the defensive allocation pool."""
    panel: Dict[str, pd.DataFrame] = {}
    for symbol, df in aligned.items():
        if symbol not in BOND_CLASS_MAP:
            continue
        panel[symbol] = df[["date", "open", "close", "is_trading"]].copy()
    return panel


# ---------------------------------------------------------------------------
# Ranking & reporting helpers
# ---------------------------------------------------------------------------
def build_top_scored_targets(panel: Dict[str, pd.DataFrame], top_k: int = 10) -> pd.DataFrame:
    """Return the top-k symbols by `rotation_score` on the panel's latest date."""
    rows = []
    for symbol, df in panel.items():
        if df is None or df.empty:
            continue
        latest_row = df.dropna(subset=["rotation_score"]).tail(1)
        if latest_row.empty:
            continue
        row = latest_row.iloc[0]
        rows.append(
            {
                "date": row["date"],
                "symbol": symbol,
                "name": SYMBOL_NAME_MAP.get(symbol, symbol),
                "category": THREE_CLASS_MAP.get(symbol, ""),
                "rotation_score": float(row["rotation_score"]),
                "rotation_candidate": bool(row["rotation_candidate"]),
                "soft_candidate": bool(row["soft_candidate"]),
                "logbias": float(row["logbias"]) if pd.notna(row["logbias"]) else np.nan,
                "rsi14": float(row["rsi14"]) if pd.notna(row["rsi14"]) else np.nan,
                "ret_20": float(row["ret_20"]) if pd.notna(row["ret_20"]) else np.nan,
                "relative_strength": float(row["relative_strength"]) if pd.notna(row["relative_strength"]) else np.nan,
            }
        )

    if not rows:
        return pd.DataFrame()

    summary = pd.DataFrame(rows).sort_values(
        by=["date", "rotation_score"],
        ascending=[False, False],
    )
    latest_date = summary["date"].max()
    summary = summary[summary["date"] == latest_date].copy()
    summary = summary.sort_values("rotation_score", ascending=False).head(top_k).reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary


def print_latest_buy_signal(latest_buy_signal: Optional[Dict[str, object]]) -> None:
    if not latest_buy_signal:
        print("\nLatest Buy Signal: none")
        return

    signal_date = pd.Timestamp(latest_buy_signal["signal_date"]).strftime("%Y-%m-%d")
    execution_date = pd.Timestamp(latest_buy_signal["execution_date"]).strftime("%Y-%m-%d")
    print(f"\nLatest Buy Signal: signal_date={signal_date}, execution_date={execution_date}")
    for idx, item in enumerate(latest_buy_signal["allocations"], start=1):
        candidate_flag = "hard" if item["rotation_candidate"] else ("soft" if item["soft_candidate"] else "hold")
        print(
            f"  {idx:>2}. {item['name']} ({item['symbol']}) | "
            f"weight={item['weight']:.2%} | category={item['category']} | type={candidate_flag}"
        )


def build_next_trade_holdings_table(trade_plan: Optional[Dict[str, object]]) -> pd.DataFrame:
    columns = ["symbol", "name", "current_weight", "target_weight", "delta_weight", "action", "trigger_type"]
    if not trade_plan or not trade_plan.get("rows"):
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(trade_plan["rows"])
    return df[columns].copy()


def print_signal_summary(trade_plan: Optional[Dict[str, object]]) -> None:
    print("\n今日触发信号摘要：")
    if not trade_plan:
        print("  无最新信号，维持现有仓位。")
        return

    signal_date = pd.Timestamp(trade_plan["signal_date"]).strftime("%Y-%m-%d")
    execution_date = pd.Timestamp(trade_plan["execution_date"]).strftime("%Y-%m-%d")
    summary_map = {
        "weekly_rebalance": "周度调仓",
        "hard_exit": "日度hard-exit",
        "soft_trim": "日度soft trim",
    }
    summary_triggers = trade_plan.get("summary_triggers", [])
    if summary_triggers:
        summary_text = "、".join(summary_map.get(item, item) for item in summary_triggers)
    else:
        summary_text = "无新信号，下一交易日维持现有仓位"

    print(f"  信号日：{signal_date}")
    print(f"  执行日：{execution_date}")
    print(f"  触发类型：{summary_text}")


def print_weight_change_details(trade_plan: Optional[Dict[str, object]]) -> None:
    print("\n仓位变动说明：")
    if not trade_plan or not trade_plan.get("rows"):
        print("  无持仓变化。")
        return

    rows = trade_plan["rows"]
    meaningful_rows = [row for row in rows if abs(float(row["delta_weight"])) > 1e-10]
    if not meaningful_rows:
        print("  今日无新增调仓，下一交易日维持当前持仓。")
        return

    for row in meaningful_rows:
        print(
            f"  {row['name']} ({row['symbol']})："
            f"当前 {row['current_weight']:.2%} -> 目标 {row['target_weight']:.2%}，"
            f"{row['action']}，触发类型={row['trigger_type']}"
        )


def print_next_trade_holdings_table(trade_plan: Optional[Dict[str, object]]) -> pd.DataFrame:
    print("\n下一交易日目标持仓表：")
    table = build_next_trade_holdings_table(trade_plan)
    if table.empty:
        print("  无持仓数据。")
        return table

    display_table = table.copy()
    for col in ["current_weight", "target_weight", "delta_weight"]:
        display_table[col] = display_table[col].map(lambda x: f"{x:.2%}")
    print(display_table.to_string(index=False))
    return table


def export_next_trade_holdings_csv(trade_plan: Optional[Dict[str, object]], output_dir: Path) -> Optional[Path]:
    table = build_next_trade_holdings_table(trade_plan)
    if trade_plan is None or table.empty:
        return None

    output_dir.mkdir(exist_ok=True, parents=True)
    signal_date = pd.Timestamp(trade_plan["signal_date"]).strftime("%Y%m%d")
    execution_date = pd.Timestamp(trade_plan["execution_date"]).strftime("%Y%m%d")
    csv_path = output_dir / f"next_trade_holdings_{signal_date}_to_{execution_date}.csv"
    export_table = table.copy()
    for col in ["current_weight", "target_weight", "delta_weight"]:
        export_table[col] = export_table[col].astype(float).round(6)
    export_table.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def print_today_tomorrow_plan(
    latest_buy_signal: Optional[Dict[str, object]],
    as_of_date: pd.Timestamp,
) -> None:
    today = pd.Timestamp(as_of_date).normalize()

    print("\n今日/下一交易日持仓与操作：")
    print(f"  今日日期：{today.strftime('%Y-%m-%d')}")

    if not latest_buy_signal:
        next_trade_date = today + pd.offsets.BDay(1)
        print(f"  下一交易日：{next_trade_date.strftime('%Y-%m-%d')}")
        print("  今日持仓：无最新调仓信号，维持现有仓位。")
        print("  今日操作：无。")
        print("  下一交易日操作：若无新信号，继续维持现有仓位。")
        return

    signal_date = pd.Timestamp(latest_buy_signal["signal_date"]).normalize()
    execution_date = pd.Timestamp(latest_buy_signal["execution_date"]).normalize()
    allocations = latest_buy_signal["allocations"]
    holding_text = "；".join(
        f"{item['name']} ({item['symbol']}) {item['weight']:.2%}"
        for item in allocations
    )

    print(f"  下一交易日：{execution_date.strftime('%Y-%m-%d')}")

    if today >= execution_date:
        print(f"  今日持仓：{holding_text}")
        print(f"  今日操作：今日已处于 {execution_date.strftime('%Y-%m-%d')} 开盘调仓后的持仓，继续持有。")
        print("  下一交易日操作：若无新调仓信号，继续按当前持仓持有。")
    elif today == signal_date:
        print("  今日持仓：当前仍按上一期持仓收盘。")
        print(f"  今日操作：今日收盘后生成新调仓信号，计划于 {execution_date.strftime('%Y-%m-%d')} 开盘执行。")
        print(f"  下一交易日预期持仓：{holding_text}")
        print("  下一交易日操作：按上述目标仓位买入/调仓。")
    else:
        print(f"  最新信号日：{signal_date.strftime('%Y-%m-%d')}")
        print(f"  计划持仓：{holding_text}")
        print("  今日操作：等待执行。")
        print("  下一交易日操作：如到执行日开盘，则按目标仓位调仓；否则继续等待。")
