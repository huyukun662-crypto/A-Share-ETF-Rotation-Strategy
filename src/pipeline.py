"""End-to-end backtest pipeline.

The pipeline ties the ETF universe, parameter search, backtester and
reporting helpers together:

1. Load raw daily OHLCV for every ETF in `TREND_ETF_POOL` plus the benchmark.
2. Optimize parameters on train/validation split via `optimize_params_on_training_set`.
3. Re-run the full backtest on the training window and on the out-of-sample window.
4. Save metric tables, equity curves and overlay charts to `OUTPUT_DIR`.

`main()` is the entry point used by the notebook and by CLI invocations.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .backtester import RSIRotationBacktester
from .config import (
    BENCHMARK_CODE,
    CANDIDATE_EXPOSURE_MAP_OPTIONS,
    END_DATE,
    OOS_START_DATE,
    OPTIMIZED_CATEGORIES,
    OUTPUT_DIR,
    START_DATE,
    StrategyConfig,
    THREE_CLASS_MAP,
    TRAIN_END_DATE,
    TREND_ETF_POOL,
    TUSHARE_TOKEN,
)
from .data_loader import align_market_data, get_symbol_label, load_tushare_daily
from .indicators import (
    build_benchmark_curve,
    build_category_shift_map,
    build_drawdown_series,
)
from .parameter_search import optimize_params_on_training_set
from .signal_panel import (
    build_top_scored_targets,
    export_next_trade_holdings_csv,
    prepare_panel_rsi_only,
    print_latest_buy_signal,
    print_next_trade_holdings_table,
    print_signal_summary,
    print_weight_change_details,
)


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------
def build_backtest_config(params: Dict[str, object]) -> StrategyConfig:
    """Build a full `StrategyConfig` from a flat parameter dict."""
    return StrategyConfig(
        ema_window=int(params["ema_window"]),
        candidate_exposure_map=CANDIDATE_EXPOSURE_MAP_OPTIONS[str(params["exposure_map_version"])],
        use_relative_strength_filter=bool(params["use_relative_strength_filter"]),
        strong_days_required_shift=int(params["strong_days_shift"]),
        exposure_map_version=str(params["exposure_map_version"]),
        portfolio_exposure_cap=float(params["portfolio_exposure_cap"]),
        dd_limit_1=float(params["dd_limit_1"]),
        dd_limit_2=float(params["dd_limit_2"]),
        dd_limit_3=float(params["dd_limit_3"]),
        dd_cap_1=float(params["dd_cap_1"]),
        dd_cap_2=float(params["dd_cap_2"]),
        dd_cap_3=float(params["dd_cap_3"]),
        defensive_mode=str(params.get("defensive_mode", "cash")),
        defensive_allocation_cap=float(params.get("defensive_allocation_cap", 0.0)),
        defensive_trigger_dd=float(params.get("defensive_trigger_dd", -0.10)),
    )


# ---------------------------------------------------------------------------
# Period backtest runner
# ---------------------------------------------------------------------------
def run_backtest_on_period(
    best_params: Dict[str, object],
    raw_data: Dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    period_name: str,
    start_date: str,
    end_date: str,
):
    print(f"\n{'=' * 60}")
    print(f"Running Backtest on {period_name}")
    print(f"{'=' * 60}")
    print(f"Period: {start_date} to {end_date}")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    period_data = {}
    for symbol, df in raw_data.items():
        period_df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()
        if len(period_df) > 0:
            period_data[symbol] = period_df

    period_benchmark = benchmark_df[
        (benchmark_df["date"] >= start_ts) & (benchmark_df["date"] <= end_ts)
    ].copy()
    if period_benchmark.empty:
        print(f"[ERROR] No benchmark data available for {period_name}")
        return None, None, None, None

    aligned = align_market_data(period_data)
    config = build_backtest_config(best_params)
    panel = prepare_panel_rsi_only(
        aligned, period_benchmark, config,
        rsi_entry=float(best_params["rsi_entry"]),
        rsi_exit=float(best_params["rsi_exit"]),
        entry_shifts=build_category_shift_map(
            best_params["stock_entry_shift"],
            best_params["commodity_entry_shift"],
            best_params["dividend_entry_shift"],
        ),
        soft_shifts=build_category_shift_map(
            best_params["stock_soft_shift"],
            best_params["commodity_soft_shift"],
            best_params["dividend_soft_shift"],
        ),
        stop_shifts=build_category_shift_map(
            best_params["stock_stop_shift"],
            best_params["commodity_stop_shift"],
            best_params["dividend_stop_shift"],
        ),
    )
    backtester = RSIRotationBacktester(config)
    equity_df, trades_df, metrics, latest_buy_signal, latest_trade_plan = backtester.run(
        panel, benchmark_df=period_benchmark,
    )
    top_scored_targets = build_top_scored_targets(panel, top_k=10)

    if equity_df is not None and not equity_df.empty:
        benchmark_curve = build_benchmark_curve(period_benchmark)
        equity_df = equity_df.merge(benchmark_curve, on="date", how="left")
        equity_df["benchmark_nav"] = equity_df["benchmark_nav"].ffill().bfill()
        equity_df["strategy_drawdown"] = build_drawdown_series(equity_df["nav"])
        equity_df["benchmark_drawdown"] = build_drawdown_series(equity_df["benchmark_nav"])

    print(f"\nResults for {period_name}:")
    print(f"  Sharpe Ratio:  {metrics['sharpe_ratio']:.4f}")
    print(f"  Annual Return: {metrics['annual_return']:.4f}")
    print(f"  Max Drawdown:  {metrics['max_drawdown']:.4f}")
    print(f"  Calmar Ratio:  {metrics['calmar_ratio']:.4f}")

    if top_scored_targets is not None and not top_scored_targets.empty:
        latest_date_str = pd.Timestamp(top_scored_targets.iloc[0]["date"]).strftime("%Y-%m-%d")
        print(f"\nLatest Top 10 Scored Targets ({latest_date_str}):")
        for _, row in top_scored_targets.iterrows():
            candidate_flag = "hard" if row["rotation_candidate"] else ("soft" if row["soft_candidate"] else "watch")
            print(
                f"  {int(row['rank']):>2}. {row['name']} ({row['symbol']}) | "
                f"score={row['rotation_score']:.2f} | type={candidate_flag} | "
                f"logbias={row['logbias']:.2f} | RSI14={row['rsi14']:.2f} | "
                f"20d={row['ret_20']:.2%} | RS={row['relative_strength']:.2%}"
            )

    if "Test Set" in str(period_name):
        print_signal_summary(latest_trade_plan)
        print_weight_change_details(latest_trade_plan)
        print_next_trade_holdings_table(latest_trade_plan)
        csv_path = export_next_trade_holdings_csv(latest_trade_plan, OUTPUT_DIR)
        if csv_path is not None:
            print(f"\n下一交易日持仓 CSV：{csv_path}")
    else:
        print_latest_buy_signal(latest_buy_signal)

    return equity_df, trades_df, metrics, top_scored_targets


# ---------------------------------------------------------------------------
# Plotting & artifact saving
# ---------------------------------------------------------------------------
def plot_results(
    train_equity_df: Optional[pd.DataFrame],
    test_equity_df: Optional[pd.DataFrame],
    best_params: Dict[str, object],
    output_dir: Path = OUTPUT_DIR,
) -> None:
    output_dir.mkdir(exist_ok=True, parents=True)
    if test_equity_df is None or test_equity_df.empty:
        return

    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    excess_nav = test_equity_df["nav"] / test_equity_df["benchmark_nav"]

    axes[0].plot(test_equity_df["date"], test_equity_df["nav"], label="Strategy NAV", linewidth=2, color="green")
    axes[0].plot(test_equity_df["date"], test_equity_df["benchmark_nav"], label="Benchmark NAV",
                 linewidth=1.5, color="black", alpha=0.8)
    axes[0].set_title(f"Test NAV vs Benchmark (EMA={best_params['ema_window']})")
    axes[0].set_ylabel("NAV")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(test_equity_df["date"], excess_nav, label="Excess NAV", linewidth=2, color="darkorange")
    axes[1].axhline(1.0, color="gray", linewidth=1, linestyle="--", alpha=0.8)
    axes[1].set_title("Test Excess NAV")
    axes[1].set_ylabel("Excess NAV")
    axes[1].legend()
    axes[1].grid(alpha=0.3)

    axes[2].plot(test_equity_df["date"], test_equity_df["strategy_drawdown"], label="Strategy DD",
                 linewidth=2, color="green")
    axes[2].plot(test_equity_df["date"], test_equity_df["benchmark_drawdown"], label="Benchmark DD",
                 linewidth=1.5, color="black", alpha=0.8)
    axes[2].set_title("Test Drawdown")
    axes[2].set_xlabel("Date")
    axes[2].set_ylabel("Drawdown")
    axes[2].legend()
    axes[2].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / "train_test_comparison.png", dpi=150)
    plt.close(fig)


def save_desktop_artifacts(
    best_params: Dict[str, object],
    local_grid_results: pd.DataFrame,
    train_equity_df: Optional[pd.DataFrame],
    train_trades_df: Optional[pd.DataFrame],
    train_metrics: Dict[str, float],
    train_top_scored_targets: Optional[pd.DataFrame],
    test_equity_df: Optional[pd.DataFrame],
    test_trades_df: Optional[pd.DataFrame],
    test_metrics: Dict[str, float],
    test_top_scored_targets: Optional[pd.DataFrame],
    output_dir: Path = OUTPUT_DIR,
) -> None:
    output_dir.mkdir(exist_ok=True, parents=True)

    plot_results(train_equity_df, test_equity_df, best_params, output_dir=output_dir)
    local_grid_results.to_csv(output_dir / "local_grid_results.csv", index=False, encoding="utf-8-sig")

    if train_equity_df is not None and not train_equity_df.empty:
        train_equity_df.to_csv(output_dir / "equity_curve_train.csv", index=False, encoding="utf-8-sig")
    if test_equity_df is not None and not test_equity_df.empty:
        test_equity_df.to_csv(output_dir / "equity_curve_test.csv", index=False, encoding="utf-8-sig")
    if train_trades_df is not None and not train_trades_df.empty:
        train_trades_df.to_csv(output_dir / "trading_log_train.csv", index=False, encoding="utf-8-sig")
    if test_trades_df is not None and not test_trades_df.empty:
        test_trades_df.to_csv(output_dir / "trading_log_test.csv", index=False, encoding="utf-8-sig")
    if train_top_scored_targets is not None and not train_top_scored_targets.empty:
        train_top_scored_targets.to_csv(
            output_dir / "top10_scored_targets_train.csv", index=False, encoding="utf-8-sig",
        )
    if test_top_scored_targets is not None and not test_top_scored_targets.empty:
        test_top_scored_targets.to_csv(
            output_dir / "top10_scored_targets_test.csv", index=False, encoding="utf-8-sig",
        )

    best_params_df = pd.DataFrame(
        [{"parameter": key, "value": value} for key, value in best_params.items()]
    )
    best_params_df.to_csv(output_dir / "best_parameters.csv", index=False, encoding="utf-8-sig")

    metrics_summary = pd.DataFrame(
        [
            {"period": "Training (2009-2019)", **train_metrics},
            {"period": "Test (2020-Present)", **test_metrics},
        ]
    )
    metrics_summary.to_csv(output_dir / "metrics_comparison.csv", index=False, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------
def load_universe() -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """Fetch raw OHLCV for every ETF in the universe plus the benchmark."""
    raw_data: Dict[str, pd.DataFrame] = {}
    print("\nLoading ETF Data")
    for symbol_name, symbol in TREND_ETF_POOL.items():
        if symbol not in THREE_CLASS_MAP:
            continue
        try:
            raw_data[symbol] = load_tushare_daily(symbol, START_DATE, END_DATE, source_type="fund")
            print(f"  Loaded {symbol_name} ({symbol})")
        except Exception as exc:
            print(f"  [WARN] {symbol_name} ({symbol}) load failed: {exc}")

    benchmark_df = load_tushare_daily(BENCHMARK_CODE, START_DATE, END_DATE, source_type="fund")
    print(f"\nSuccessfully loaded {len(raw_data)} ETFs")
    print(f"Benchmark: {get_symbol_label(BENCHMARK_CODE)}")
    print(f"Benchmark data: {len(benchmark_df)} days")
    return raw_data, benchmark_df


def main():
    """End-to-end: load data → optimize → backtest train/OOS → save artifacts."""
    if not TUSHARE_TOKEN:
        raise RuntimeError(
            "TUSHARE_TOKEN is not set. The person running this script must provide it via environment variable before execution."
        )
    print(f"\n{'=' * 60}")
    print("Weekly V2 RSI-Only Backtest With Local Neighborhood Search")
    print(f"{'=' * 60}")
    print(f"Training Period: {START_DATE} to {TRAIN_END_DATE}")
    print(f"Test Period: {OOS_START_DATE} to {END_DATE}")
    print(f"Optimized Categories: {', '.join(OPTIMIZED_CATEGORIES)}")

    raw_data, benchmark_df = load_universe()

    print("\nSTEP 1: Local Train/Validation Neighborhood Search")
    best_params, local_grid_results = optimize_params_on_training_set(raw_data, benchmark_df)

    print("\nSTEP 2: Training Set Backtest with Tuned Parameters")
    train_equity_df, train_trades_df, train_metrics, train_top_scored_targets = run_backtest_on_period(
        best_params, raw_data, benchmark_df, "Training Set", START_DATE, TRAIN_END_DATE,
    )

    print("\nSTEP 3: Test Set Backtest with Tuned Parameters (Out-of-Sample)")
    test_equity_df, test_trades_df, test_metrics, test_top_scored_targets = run_backtest_on_period(
        best_params, raw_data, benchmark_df, "Test Set (OOS)", OOS_START_DATE, END_DATE,
    )

    save_desktop_artifacts(
        best_params, local_grid_results,
        train_equity_df, train_trades_df, train_metrics, train_top_scored_targets,
        test_equity_df, test_trades_df, test_metrics, test_top_scored_targets,
    )
    print(f"\nAll results saved to: {OUTPUT_DIR}")

    return best_params, local_grid_results, train_equity_df, test_equity_df


if __name__ == "__main__":
    main()
