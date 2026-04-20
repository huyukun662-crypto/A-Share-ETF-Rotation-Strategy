"""Data loading utilities.

Fetches daily ETF OHLCV from Tushare Pro with an akshare fallback, repairs
occasional split-like anomalies using `pct_chg`, and aligns symbols onto a
shared trading-day index.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, TypeVar

import akshare as ak
import numpy as np
import pandas as pd
import requests
import tushare as ts

T = TypeVar("T")

from .config import SYMBOL_NAME_MAP, TUSHARE_TOKEN


def normalize_symbol(symbol: str) -> str:
    """Normalize a bare 6-digit code into a Tushare `XXXXXX.XX` code."""
    symbol = str(symbol).strip().upper()
    if "." in symbol:
        return symbol
    if symbol.startswith(("159", "399", "000")):
        return f"{symbol}.SZ"
    return f"{symbol}.SH"


def get_symbol_label(symbol: str) -> str:
    code = normalize_symbol(symbol)
    return f"{SYMBOL_NAME_MAP.get(code, code)} ({code})"


def repair_price_series_with_pct_chg(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    """Detect and repair split-like gaps by rebuilding prices from `pct_chg`."""
    out = df.copy().sort_values("date").reset_index(drop=True)
    if "pct_chg" not in out.columns:
        return out

    out["pct_chg"] = pd.to_numeric(out["pct_chg"], errors="coerce")
    raw_close_return = out["close"].pct_change()
    pct_chg_return = out["pct_chg"] / 100.0
    mismatch = (raw_close_return - pct_chg_return).abs()
    anomaly_mask = (mismatch > 0.20) & pct_chg_return.notna() & raw_close_return.notna()
    if not anomaly_mask.any():
        return out.drop(columns=["pct_chg"])

    adjusted_close = []
    for idx, row in out.iterrows():
        if idx == 0:
            adjusted_close.append(float(row["close"]))
            continue
        pct_ret = row["pct_chg"] / 100.0 if pd.notna(row["pct_chg"]) else raw_close_return.iloc[idx]
        if pd.isna(pct_ret):
            pct_ret = raw_close_return.iloc[idx]
        if pd.isna(pct_ret):
            pct_ret = 0.0
        adjusted_close.append(adjusted_close[-1] * (1.0 + float(pct_ret)))

    out["adjusted_close"] = adjusted_close
    scale = out["adjusted_close"] / out["close"].replace(0, np.nan)
    for col in ["open", "high", "low", "close"]:
        out[col] = out[col] * scale
    anomaly_dates = out.loc[anomaly_mask, "date"].dt.strftime("%Y-%m-%d").tolist()
    print(f"  [DATA FIX] {get_symbol_label(ts_code)} repaired split-like price jumps on {', '.join(anomaly_dates[:5])}")
    if len(anomaly_dates) > 5:
        print(f"  [DATA FIX] {get_symbol_label(ts_code)} additional repaired dates: {len(anomaly_dates) - 5}")
    return out.drop(columns=["pct_chg", "adjusted_close"])


def _retry_fetch(fetcher: Callable[[], T], source_name: str, symbol: str, max_attempts: int = 3, base_delay: float = 1.5) -> T:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fetcher()
        except (requests.exceptions.RequestException, ConnectionError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = base_delay * attempt
            print(
                f"  [RETRY] {source_name} {get_symbol_label(symbol)} attempt {attempt}/{max_attempts} failed: {exc}. "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
    raise RuntimeError(f"{source_name} fetch failed after {max_attempts} attempts for {get_symbol_label(symbol)}") from last_error


def _prepare_ohlcv_frame(df: pd.DataFrame, start_date: str, end_date: str, ts_code: str) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in [c for c in ["open", "high", "low", "close", "volume", "pct_chg"] if c in out.columns]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.sort_values("date").dropna(subset=["open", "high", "low", "close"])
    out = out[(out["date"] >= pd.Timestamp(start_date)) & (out["date"] <= pd.Timestamp(end_date))]
    out = repair_price_series_with_pct_chg(out, ts_code)
    out["symbol"] = ts_code
    out["is_trading"] = True
    return out.reset_index(drop=True)


def _load_tushare_frame(pro, ts_code: str, start: str, end: str, source_type: str) -> pd.DataFrame:
    if source_type == "map":
        return pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
    return pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)


def _load_akshare_frame(raw_symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    return ak.fund_etf_hist_em(
        symbol=raw_symbol,
        period="daily",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust="qfq",
    )


def _process_tushare_frame(df: pd.DataFrame, start_date: str, end_date: str, ts_code: str) -> pd.DataFrame:
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    keep_cols = ["date", "open", "high", "low", "close", "volume"]
    if "pct_chg" in df.columns:
        keep_cols.append("pct_chg")
    return _prepare_ohlcv_frame(df[keep_cols].copy(), start_date, end_date, ts_code)


def _process_akshare_frame(df: pd.DataFrame, start_date: str, end_date: str, ts_code: str) -> pd.DataFrame:
    rename_map = {
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "涨跌幅": "pct_chg",
    }
    out = df.rename(columns=rename_map)
    keep_cols = ["date", "open", "high", "low", "close", "volume", "pct_chg"]
    return _prepare_ohlcv_frame(out[[c for c in keep_cols if c in out.columns]].copy(), start_date, end_date, ts_code)


def _raise_provider_error(source_name: str, symbol: str, exc: Exception) -> None:
    raise RuntimeError(f"{source_name} data load failed for {get_symbol_label(symbol)}: {exc}") from exc


def _load_akshare_daily_once(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    ts_code = normalize_symbol(symbol)
    raw_symbol = ts_code.split(".")[0]
    df = _retry_fetch(
        lambda: _load_akshare_frame(raw_symbol, start_date, end_date),
        source_name="AkShare",
        symbol=ts_code,
    )
    return _process_akshare_frame(df, start_date, end_date, ts_code)


def _load_tushare_daily_once(symbol: str, start_date: str, end_date: str, source_type: str = "fund") -> pd.DataFrame:
    pro = ts.pro_api(TUSHARE_TOKEN)
    ts_code = normalize_symbol(symbol)
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    df = _retry_fetch(
        lambda: _load_tushare_frame(pro, ts_code, start, end, source_type),
        source_name="Tushare",
        symbol=ts_code,
    )
    return _process_tushare_frame(df, start_date, end_date, ts_code)


def _load_with_fallback(symbol: str, start_date: str, end_date: str, source_type: str = "fund") -> pd.DataFrame:
    ts_code = normalize_symbol(symbol)
    if not TUSHARE_TOKEN:
        raise RuntimeError(
            "TUSHARE_TOKEN is required at runtime and must be provided by the person running the script via environment variable."
        )

    try:
        return _load_tushare_daily_once(ts_code, start_date, end_date, source_type=source_type)
    except Exception as exc:
        if source_type != "fund":
            _raise_provider_error("Tushare", ts_code, exc)
        print(f"  [DATA FALLBACK] {get_symbol_label(ts_code)} tushare unavailable, fallback to akshare: {exc}")
        try:
            return _load_akshare_daily_once(ts_code, start_date, end_date)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"All data sources failed for {get_symbol_label(ts_code)}: tushare={exc}; akshare={fallback_exc}"
            ) from fallback_exc


def load_akshare_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fallback data loader via akshare (forward-adjusted qfq)."""
    return _load_with_fallback(symbol, start_date, end_date, source_type="fund")


def load_tushare_daily(symbol: str, start_date: str, end_date: str, source_type: str = "fund") -> pd.DataFrame:
    """Primary data loader via Tushare Pro; falls back to akshare on error."""
    return _load_with_fallback(symbol, start_date, end_date, source_type=source_type)


def align_market_data(data_dict: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Align all symbols onto a shared trading-day index (forward-fill close)."""
    all_dates = sorted(set().union(*[set(df["date"]) for df in data_dict.values()]))
    master_index = pd.DatetimeIndex(all_dates, name="date")
    aligned = {}
    for symbol, df in data_dict.items():
        tmp = df.set_index("date").reindex(master_index)
        tmp["symbol"] = symbol
        tmp["is_trading"] = tmp["is_trading"].fillna(False).infer_objects(copy=False)
        tmp["close"] = tmp["close"].ffill()
        tmp["volume"] = tmp["volume"].fillna(0.0)
        aligned[symbol] = tmp.reset_index()
    return aligned


# duplicate legacy loader definitions removed
