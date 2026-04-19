"""Train/validation parameter search.

Two stages:

- **stage_1_core_neighborhood** — scans `ema_window`, `rsi_entry`, `rsi_exit`
  and the candidate-count exposure mapping version.
- **stage_2_threshold_neighborhood** — scans the nine per-category LogBias
  entry / soft / stop shifts plus the `strong_days_required_shift` and
  the relative-strength filter toggle.

Each candidate is evaluated on a training sub-window and a validation
sub-window.  Candidates whose validation max-drawdown exceeds
`VALIDATION_DRAWDOWN_CAP` and whose train–validation annual-return gap
is ≤ 8% are preferred; the ranker falls back gracefully when no
candidate satisfies the constraints.
"""
from __future__ import annotations

from itertools import product
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .backtester import RSIRotationBacktester
from .config import (
    BEST_OOS_BASELINE_PARAMS,
    CANDIDATE_EXPOSURE_MAP_OPTIONS,
    EMA_WINDOW_RANGE,
    EXPOSURE_MAP_VERSION_RANGE,
    N_WORKERS,
    RSI_ENTRY_RANGE,
    RSI_EXIT_RANGE,
    StrategyConfig,
    TRAIN_SEARCH_END_DATE,
    TRAIN_SEARCH_START_DATE,
    VALIDATION_DRAWDOWN_CAP,
    VALIDATION_END_DATE,
    VALIDATION_START_DATE,
)
from .data_loader import align_market_data
from .indicators import (
    build_category_shift_map,
    calculate_panel_diagnostics,
    calculate_param_distance,
)
from .signal_panel import prepare_panel_rsi_only


# ---------------------------------------------------------------------------
# Single-candidate evaluator (parallel-safe)
# ---------------------------------------------------------------------------
def evaluate_single_params(
    args,
    train_aligned_data_list,
    train_benchmark_dict,
    validation_aligned_data_list,
    validation_benchmark_dict,
):
    (
        ema_window, rsi_entry, rsi_exit,
        stock_entry_shift, commodity_entry_shift, dividend_entry_shift,
        stock_soft_shift, commodity_soft_shift, dividend_soft_shift,
        stock_stop_shift, commodity_stop_shift, dividend_stop_shift,
        strong_days_shift, use_relative_strength_filter, exposure_map_version,
    ) = args

    candidate_params = {
        "ema_window": int(ema_window),
        "rsi_entry": rsi_entry, "rsi_exit": rsi_exit,
        "stock_entry_shift": stock_entry_shift,
        "commodity_entry_shift": commodity_entry_shift,
        "dividend_entry_shift": dividend_entry_shift,
        "stock_soft_shift": stock_soft_shift,
        "commodity_soft_shift": commodity_soft_shift,
        "dividend_soft_shift": dividend_soft_shift,
        "stock_stop_shift": stock_stop_shift,
        "commodity_stop_shift": commodity_stop_shift,
        "dividend_stop_shift": dividend_stop_shift,
        "strong_days_shift": int(strong_days_shift),
        "use_relative_strength_filter": bool(use_relative_strength_filter),
        "exposure_map_version": exposure_map_version,
    }

    try:
        config = StrategyConfig(
            ema_window=int(ema_window),
            candidate_exposure_map=CANDIDATE_EXPOSURE_MAP_OPTIONS[exposure_map_version],
            use_relative_strength_filter=bool(use_relative_strength_filter),
            strong_days_required_shift=int(strong_days_shift),
            exposure_map_version=exposure_map_version,
        )
        entry_shifts = build_category_shift_map(stock_entry_shift, commodity_entry_shift, dividend_entry_shift)
        soft_shifts = build_category_shift_map(stock_soft_shift, commodity_soft_shift, dividend_soft_shift)
        stop_shifts = build_category_shift_map(stock_stop_shift, commodity_stop_shift, dividend_stop_shift)

        def run_period_eval(aligned_data_list, benchmark_dict):
            aligned_data = {item["symbol"]: pd.DataFrame(item["data"]) for item in aligned_data_list}
            benchmark_df = pd.DataFrame(benchmark_dict)
            panel = prepare_panel_rsi_only(
                aligned_data, benchmark_df, config,
                rsi_entry=rsi_entry, rsi_exit=rsi_exit,
                entry_shifts=entry_shifts, soft_shifts=soft_shifts, stop_shifts=stop_shifts,
            )
            backtester = RSIRotationBacktester(config)
            equity_curve, trades, metrics, _, _ = backtester.run(panel, benchmark_df=benchmark_df)
            diagnostics = calculate_panel_diagnostics(panel, equity_curve)
            return equity_curve, trades, metrics, diagnostics

        _, train_trades, train_metrics, train_diagnostics = run_period_eval(
            train_aligned_data_list, train_benchmark_dict,
        )
        _, validation_trades, validation_metrics, validation_diagnostics = run_period_eval(
            validation_aligned_data_list, validation_benchmark_dict,
        )

        return {
            **candidate_params,
            "train_sharpe_ratio": train_metrics["sharpe_ratio"],
            "train_annual_return": train_metrics["annual_return"],
            "train_max_drawdown": train_metrics["max_drawdown"],
            "train_calmar_ratio": train_metrics["calmar_ratio"],
            "train_win_rate": train_metrics["win_rate"],
            "train_avg_hold_days": train_metrics["avg_hold_days"],
            "train_turnover": train_metrics["turnover"],
            "train_avg_exposure": train_metrics["avg_exposure"],
            "train_min_exposure": train_metrics["min_exposure"],
            "train_trade_count": int(len(train_trades[train_trades["exit_date"].notna()])) if not train_trades.empty else 0,
            "train_invested_days_ratio": train_diagnostics["invested_days_ratio"],
            "train_hard_signal_days_ratio": train_diagnostics["hard_signal_days_ratio"],
            "train_soft_signal_days_ratio": train_diagnostics["soft_signal_days_ratio"],
            "train_avg_candidate_count": train_diagnostics["avg_candidate_count"],
            "train_avg_soft_candidate_count": train_diagnostics["avg_soft_candidate_count"],
            "validation_sharpe_ratio": validation_metrics["sharpe_ratio"],
            "validation_annual_return": validation_metrics["annual_return"],
            "validation_max_drawdown": validation_metrics["max_drawdown"],
            "validation_calmar_ratio": validation_metrics["calmar_ratio"],
            "validation_win_rate": validation_metrics["win_rate"],
            "validation_avg_hold_days": validation_metrics["avg_hold_days"],
            "validation_turnover": validation_metrics["turnover"],
            "validation_avg_exposure": validation_metrics["avg_exposure"],
            "validation_min_exposure": validation_metrics["min_exposure"],
            "validation_trade_count": int(len(validation_trades[validation_trades["exit_date"].notna()])) if not validation_trades.empty else 0,
            "validation_invested_days_ratio": validation_diagnostics["invested_days_ratio"],
            "validation_hard_signal_days_ratio": validation_diagnostics["hard_signal_days_ratio"],
            "validation_soft_signal_days_ratio": validation_diagnostics["soft_signal_days_ratio"],
            "validation_avg_candidate_count": validation_diagnostics["avg_candidate_count"],
            "validation_avg_soft_candidate_count": validation_diagnostics["avg_soft_candidate_count"],
            "validation_drawdown_ok": validation_metrics["max_drawdown"] >= VALIDATION_DRAWDOWN_CAP,
            "annual_return_gap": abs(train_metrics["annual_return"] - validation_metrics["annual_return"]),
            "param_distance": calculate_param_distance(candidate_params),
        }
    except Exception:
        return {
            **candidate_params,
            "train_sharpe_ratio": -np.inf, "train_annual_return": 0.0,
            "train_max_drawdown": 0.0, "train_calmar_ratio": 0.0,
            "train_win_rate": np.nan, "train_avg_hold_days": np.nan,
            "train_turnover": 0.0, "train_avg_exposure": 0.0, "train_min_exposure": 0.0,
            "train_trade_count": 0, "train_invested_days_ratio": 0.0,
            "train_hard_signal_days_ratio": 0.0, "train_soft_signal_days_ratio": 0.0,
            "train_avg_candidate_count": 0.0, "train_avg_soft_candidate_count": 0.0,
            "validation_sharpe_ratio": -np.inf, "validation_annual_return": 0.0,
            "validation_max_drawdown": 0.0, "validation_calmar_ratio": 0.0,
            "validation_win_rate": np.nan, "validation_avg_hold_days": np.nan,
            "validation_turnover": 0.0, "validation_avg_exposure": 0.0, "validation_min_exposure": 0.0,
            "validation_trade_count": 0, "validation_invested_days_ratio": 0.0,
            "validation_hard_signal_days_ratio": 0.0, "validation_soft_signal_days_ratio": 0.0,
            "validation_avg_candidate_count": 0.0, "validation_avg_soft_candidate_count": 0.0,
            "validation_drawdown_ok": False, "annual_return_gap": np.inf,
            "param_distance": calculate_param_distance(candidate_params),
        }


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------
def select_best_result_frame(results_df: pd.DataFrame) -> pd.DataFrame:
    """Rank candidates, preferring validation-DD-compliant + low train/val gap."""
    eligible_df = results_df[results_df["validation_drawdown_ok"]].copy()
    stable_df = eligible_df[eligible_df["annual_return_gap"] <= 0.08].copy()
    if not stable_df.empty:
        stable_df["selection_mode"] = "validation_dd12_and_gap"
        stable_df["drawdown_gap"] = 0.0
        return stable_df.sort_values(
            ["validation_annual_return", "validation_sharpe_ratio", "annual_return_gap", "param_distance"],
            ascending=[False, False, True, True],
        ).reset_index(drop=True)
    if not eligible_df.empty:
        eligible_df["selection_mode"] = "validation_dd12_only"
        eligible_df["drawdown_gap"] = 0.0
        return eligible_df.sort_values(
            ["validation_annual_return", "validation_sharpe_ratio", "param_distance"],
            ascending=[False, False, True],
        ).reset_index(drop=True)

    fallback_df = results_df.copy()
    fallback_df["selection_mode"] = "fallback_validation_dd12"
    fallback_df["drawdown_gap"] = (fallback_df["validation_max_drawdown"] - VALIDATION_DRAWDOWN_CAP).abs()
    return fallback_df.sort_values(
        ["drawdown_gap", "validation_annual_return", "validation_sharpe_ratio"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def build_eval_args_from_params(params: Dict[str, object]) -> tuple:
    return (
        params["ema_window"], params["rsi_entry"], params["rsi_exit"],
        params["stock_entry_shift"], params["commodity_entry_shift"], params["dividend_entry_shift"],
        params["stock_soft_shift"], params["commodity_soft_shift"], params["dividend_soft_shift"],
        params["stock_stop_shift"], params["commodity_stop_shift"], params["dividend_stop_shift"],
        params["strong_days_shift"], params["use_relative_strength_filter"], params["exposure_map_version"],
    )


# ---------------------------------------------------------------------------
# Search stage runner
# ---------------------------------------------------------------------------
def run_search_stage(
    stage_name: str,
    base_params: Dict[str, object],
    varying_keys: Sequence[str],
    varying_values_list: Sequence[Tuple],
    train_aligned_data_list: List[dict],
    train_benchmark_dict: dict,
    validation_aligned_data_list: List[dict],
    validation_benchmark_dict: dict,
) -> Tuple[Dict[str, object], pd.DataFrame]:
    try:
        from joblib import Parallel, delayed
    except ModuleNotFoundError:
        Parallel = None
        delayed = None

    stage_param_dicts = []
    for varying_values in varying_values_list:
        params = dict(base_params)
        for key, value in zip(varying_keys, varying_values):
            params[key] = value
        stage_param_dicts.append(params)

    print(f"{stage_name}: {len(stage_param_dicts)} combinations")
    if Parallel is None:
        print("joblib not found; running search sequentially.")
        results = [
            evaluate_single_params(
                build_eval_args_from_params(params),
                train_aligned_data_list, train_benchmark_dict,
                validation_aligned_data_list, validation_benchmark_dict,
            )
            for params in stage_param_dicts
        ]
    else:
        results = Parallel(n_jobs=min(N_WORKERS, len(stage_param_dicts)), verbose=10)(
            delayed(evaluate_single_params)(
                build_eval_args_from_params(params),
                train_aligned_data_list, train_benchmark_dict,
                validation_aligned_data_list, validation_benchmark_dict,
            )
            for params in stage_param_dicts
        )
    results_df = select_best_result_frame(pd.DataFrame(results))
    best = results_df.iloc[0]

    updated_params = dict(base_params)
    for key in varying_keys:
        updated_params[key] = best[key]

    return updated_params, results_df


# ---------------------------------------------------------------------------
# Top-level search driver
# ---------------------------------------------------------------------------
def optimize_params_on_training_set(raw_data: Dict[str, pd.DataFrame], benchmark_df: pd.DataFrame):
    """Run the two-stage train/validation neighborhood search and return best params."""
    print(f"\n{'=' * 60}")
    print("Starting Train/Validation Parameter Search")
    print(f"{'=' * 60}")
    print(f"Train Search Period: {TRAIN_SEARCH_START_DATE} to {TRAIN_SEARCH_END_DATE}")
    print(f"Validation Period: {VALIDATION_START_DATE} to {VALIDATION_END_DATE}")
    print(f"Validation Drawdown Cap: {VALIDATION_DRAWDOWN_CAP:.0%}")

    train_search_start = pd.Timestamp(TRAIN_SEARCH_START_DATE)
    train_search_end = pd.Timestamp(TRAIN_SEARCH_END_DATE)
    validation_start = pd.Timestamp(VALIDATION_START_DATE)
    validation_end = pd.Timestamp(VALIDATION_END_DATE)

    train_raw_data, validation_raw_data = {}, {}
    for symbol, df in raw_data.items():
        train_df = df[(df["date"] >= train_search_start) & (df["date"] <= train_search_end)].copy()
        if not train_df.empty:
            train_raw_data[symbol] = train_df
        validation_df = df[(df["date"] >= validation_start) & (df["date"] <= validation_end)].copy()
        if not validation_df.empty:
            validation_raw_data[symbol] = validation_df

    train_benchmark_df = benchmark_df[
        (benchmark_df["date"] >= train_search_start) & (benchmark_df["date"] <= train_search_end)
    ].copy()
    if train_benchmark_df.empty:
        raise ValueError("No benchmark data available in train search period.")
    validation_benchmark_df = benchmark_df[
        (benchmark_df["date"] >= validation_start) & (benchmark_df["date"] <= validation_end)
    ].copy()
    if validation_benchmark_df.empty:
        raise ValueError("No benchmark data available in validation period.")

    aligned_train_data = align_market_data(train_raw_data)
    aligned_train_data_list = [
        {"symbol": symbol, "data": df.to_dict("records")}
        for symbol, df in aligned_train_data.items()
    ]
    train_benchmark_dict = train_benchmark_df.to_dict("list")
    aligned_validation_data = align_market_data(validation_raw_data)
    aligned_validation_data_list = [
        {"symbol": symbol, "data": df.to_dict("records")}
        for symbol, df in aligned_validation_data.items()
    ]
    validation_benchmark_dict = validation_benchmark_df.to_dict("list")

    params = dict(BEST_OOS_BASELINE_PARAMS)
    stage_frames = []

    search_plan = [
        (
            "stage_1_core_neighborhood",
            ["ema_window", "rsi_entry", "rsi_exit", "exposure_map_version"],
            product(EMA_WINDOW_RANGE, RSI_ENTRY_RANGE, RSI_EXIT_RANGE, EXPOSURE_MAP_VERSION_RANGE),
        ),
        (
            "stage_2_threshold_neighborhood",
            [
                "stock_entry_shift", "commodity_entry_shift", "dividend_entry_shift",
                "stock_soft_shift", "commodity_soft_shift", "dividend_soft_shift",
                "stock_stop_shift", "commodity_stop_shift", "dividend_stop_shift",
                "strong_days_shift", "use_relative_strength_filter",
            ],
            product(
                [-1.2, -0.6], [-1.2, -0.6], [-1.2, -0.6],
                [-0.3, 0.0], [-0.6, -0.3], [-0.6, -0.3],
                [-0.5, 0.0], [-0.5, 0.0], [-0.5, 0.0],
                [-1, 0], [False],
            ),
        ),
    ]

    for stage_name, varying_keys, varying_values in search_plan:
        params, stage_results = run_search_stage(
            stage_name, params, varying_keys, list(varying_values),
            aligned_train_data_list, train_benchmark_dict,
            aligned_validation_data_list, validation_benchmark_dict,
        )
        stage_results.insert(0, "search_stage", stage_name)
        stage_frames.append(stage_results)
        best_row = stage_results.iloc[0]
        print(
            f"{stage_name} best: train annual_return={best_row['train_annual_return']:.4f}, "
            f"train sharpe={best_row['train_sharpe_ratio']:.4f}, train max_drawdown={best_row['train_max_drawdown']:.4f}, "
            f"validation annual_return={best_row['validation_annual_return']:.4f}, "
            f"validation sharpe={best_row['validation_sharpe_ratio']:.4f}, "
            f"validation max_drawdown={best_row['validation_max_drawdown']:.4f}, "
            f"validation drawdown ok={bool(best_row['validation_drawdown_ok'])}"
        )

    print("\nBest Parameters from Local Train/Validation Neighborhood Search:")
    for key, value in params.items():
        print(f"  {key}: {value}")

    return params, pd.concat(stage_frames, ignore_index=True)
