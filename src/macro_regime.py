"""Macro regime detection using M1-M2 scissors difference and China 10Y bond yield.

Provides top-level timing valves (宏观开关) for the ETF rotation strategy.
All akshare calls are wrapped with graceful fallbacks so the strategy can
run in neutral mode when external macro data is unavailable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Literal, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# In-memory + disk caching to avoid redundant API calls
# ---------------------------------------------------------------------------
_CACHE: Dict[str, pd.DataFrame] = {}


def _cache_dir() -> Path:
    cd = Path(__file__).resolve().parent.parent / "data_cache"
    cd.mkdir(exist_ok=True, parents=True)
    return cd


def _cache_path(name: str) -> Path:
    return _cache_dir() / f"{name}.csv"


def _load_cache(name: str) -> Optional[pd.DataFrame]:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        return df
    except Exception:
        return None


def _save_cache(name: str, df: pd.DataFrame) -> None:
    try:
        df.to_csv(_cache_path(name), index=False, encoding="utf-8-sig")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------
def fetch_m1_m2_data(start_date: str) -> Optional[pd.DataFrame]:
    """Fetch M1/M2 YoY growth from akshare and compute M1-M2 scissors difference.

    Returns a DataFrame with columns: ``date``, ``m1_yoy``, ``m2_yoy``, ``m1_m2_diff``.
    Falls back to ``None`` if akshare is unavailable or the API changes.
    """
    cache_key = f"m1_m2_{start_date}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    cached = _load_cache(cache_key)
    if cached is not None:
        _CACHE[cache_key] = cached
        return cached

    try:
        import akshare as ak

        df = ak.macro_china_money_supply()
        if df is None or df.empty:
            print("[REGIME] akshare.macro_china_money_supply returned empty data")
            return None

        df.columns = [str(c).strip() for c in df.columns]

        date_col = next(
            (c for c in df.columns if "月份" in c or "日期" in c or c.lower() == "date"),
            df.columns[0],
        )

        df["date"] = pd.to_datetime(df[date_col], errors="coerce", format="%Y.%m")
        if df["date"].isna().all():
            df["date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["date"])

        m1_col = next(
            (c for c in df.columns if "M1" in c.upper() and ("同比" in c or "增速" in c or "增长" in c)),
            None,
        )
        m2_col = next(
            (c for c in df.columns if "M2" in c.upper() and ("同比" in c or "增速" in c or "增长" in c)),
            None,
        )

        if m1_col is None:
            m1_col = next((c for c in df.columns if "M1" in c.upper()), None)
        if m2_col is None:
            m2_col = next((c for c in df.columns if "M2" in c.upper()), None)

        if m1_col is None or m2_col is None:
            print(f"[REGIME] Could not locate M1/M2 columns. Available: {list(df.columns)}")
            return None

        df["m1_yoy"] = pd.to_numeric(df[m1_col], errors="coerce")
        df["m2_yoy"] = pd.to_numeric(df[m2_col], errors="coerce")
        df = df.dropna(subset=["m1_yoy", "m2_yoy"])
        df["m1_m2_diff"] = df["m1_yoy"] - df["m2_yoy"]

        df = df[df["date"] >= pd.Timestamp(start_date)].copy()
        df = df.sort_values("date").reset_index(drop=True)

        result = df[["date", "m1_yoy", "m2_yoy", "m1_m2_diff"]].copy()
        _CACHE[cache_key] = result
        _save_cache(cache_key, result)
        return result

    except Exception as exc:
        print(f"[REGIME] Failed to fetch M1-M2 data: {exc}")
        return None


def fetch_bond_yield_data(start_date: str) -> Optional[pd.DataFrame]:
    """Fetch China 10-year government bond yield from akshare.

    Returns a DataFrame with columns: ``date``, ``bond_yield_10y``.
    Falls back to ``None`` if akshare is unavailable.
    """
    cache_key = f"bond_yield_{start_date}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    cached = _load_cache(cache_key)
    if cached is not None:
        _CACHE[cache_key] = cached
        return cached

    try:
        import akshare as ak

        df = ak.bond_zh_us_rate()
        if df is None or df.empty:
            print("[REGIME] akshare.bond_zh_us_rate returned empty data")
            return None

        df.columns = [str(c).strip() for c in df.columns]

        date_col = next(
            (c for c in df.columns if "日期" in c or c.lower() == "date"),
            df.columns[0],
        )
        df["date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["date"])

        # Locate China 10Y yield column
        target_col = next(
            (c for c in df.columns if "中国国债收益率10年" in c),
            None,
        )
        if target_col is None:
            target_col = next(
                (
                    c
                    for c in df.columns
                    if ("中国" in c or "中债" in c or "国债" in c)
                    and ("10" in c or "十年" in c)
                    and "收益" in c
                ),
                None,
            )
        if target_col is None:
            print(f"[REGIME] Could not locate China 10Y bond yield column. Available: {list(df.columns)}")
            return None

        df["bond_yield_10y"] = pd.to_numeric(df[target_col], errors="coerce")
        df = df.dropna(subset=["bond_yield_10y"])
        df = df[df["date"] >= pd.Timestamp(start_date)].copy()
        df = df.sort_values("date").reset_index(drop=True)

        result = df[["date", "bond_yield_10y"]].copy()
        _CACHE[cache_key] = result
        _save_cache(cache_key, result)
        return result

    except Exception as exc:
        print(f"[REGIME] Failed to fetch bond yield data: {exc}")
        return None


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------
def compute_regime(
    m1_m2_diff: Optional[pd.Series],
    bond_yield: Optional[pd.Series],
    lookback: int = 60,
) -> Literal["risk_on", "cautious", "risk_off", "neutral"]:
    """Classify macro regime based on latest M1-M2 diff and 10Y bond yield.

    Parameters
    ----------
    m1_m2_diff:
        Series of M1-M2 scissors differences (monthly frequency is fine).
    bond_yield:
        Series of 10Y CGB yields (daily or monthly).
    lookback:
        Unused kept for API compatibility.

    Returns
    -------
    One of ``risk_on``, ``cautious``, ``risk_off``, ``neutral``.
    """
    from .config import (
        REGIME_BOND_YIELD_INVERSION,
        REGIME_CAUTIOUS_THRESHOLD,
        REGIME_RISK_ON_THRESHOLD,
    )

    if m1_m2_diff is None or m1_m2_diff.empty:
        return "neutral"

    latest_m1_m2 = float(m1_m2_diff.iloc[-1])

    if latest_m1_m2 >= REGIME_RISK_ON_THRESHOLD:
        base_regime = "risk_on"
    elif latest_m1_m2 >= REGIME_CAUTIOUS_THRESHOLD:
        base_regime = "cautious"
    else:
        base_regime = "risk_off"

    # Bond yield override: extremely high yields force caution even when M1-M2 looks good
    if bond_yield is not None and not bond_yield.empty:
        latest_yield = float(bond_yield.iloc[-1])
        if latest_yield >= REGIME_BOND_YIELD_INVERSION and base_regime == "risk_on":
            base_regime = "cautious"

    return base_regime


def compute_regime_for_date(
    date: pd.Timestamp,
    m1_m2_df: Optional[pd.DataFrame],
    bond_df: Optional[pd.DataFrame],
) -> Literal["risk_on", "cautious", "risk_off", "neutral"]:
    """Look up the most recent macro data <= *date* and classify regime."""
    m1_m2_series: Optional[pd.Series] = None
    bond_series: Optional[pd.Series] = None

    if m1_m2_df is not None and not m1_m2_df.empty:
        mask = m1_m2_df["date"] <= date
        if mask.any():
            m1_m2_series = m1_m2_df.loc[mask, "m1_m2_diff"]

    if bond_df is not None and not bond_df.empty:
        mask = bond_df["date"] <= date
        if mask.any():
            bond_series = bond_df.loc[mask, "bond_yield_10y"]

    return compute_regime(m1_m2_series, bond_series)


def detect_market_regime(
    data_dict: Optional[Dict[str, pd.DataFrame]] = None,
    benchmark_df: Optional[pd.DataFrame] = None,
    start_date: str = "2009-01-01",
    lookback: int = 60,
) -> Literal["risk_on", "cautious", "risk_off", "neutral"]:
    """High-level regime detection entry point.

    Fetches macro data (with caching) and returns the current regime.
    ``data_dict`` and ``benchmark_df`` are accepted for API compatibility but
    are not currently used for regime classification.
    """
    m1_m2_df = fetch_m1_m2_data(start_date)
    bond_df = fetch_bond_yield_data(start_date)

    m1_m2_series: Optional[pd.Series] = None
    if m1_m2_df is not None and not m1_m2_df.empty:
        m1_m2_series = pd.Series(m1_m2_df["m1_m2_diff"])

    bond_series: Optional[pd.Series] = None
    if bond_df is not None and not bond_df.empty:
        bond_series = pd.Series(bond_df["bond_yield_10y"])

    return compute_regime(m1_m2_series, bond_series, lookback=lookback)
