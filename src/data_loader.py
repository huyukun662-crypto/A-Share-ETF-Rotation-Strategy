"""Data loading utilities.

Fetches daily ETF OHLCV from Tushare Pro with an akshare fallback, repairs
occasional split-like anomalies using `pct_chg`, and aligns symbols onto a
shared trading-day index.
"""
from __future__ import annotations

from typing import Dict

import akshare as ak
import numpy as np
import pandas as pd
import tushare as ts

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


def load_akshare_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fallback data loader via akshare (forward-adjusted qfq)."""
    ts_code = normalize_symbol(symbol)
    raw_symbol = ts_code.split(".")[0]
    df = ak.fund_etf_hist_em(
        symbol=raw_symbol,
        period="daily",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust="qfq",
    )
    rename_map = {
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "涨跌幅": "pct_chg",
    }
    out = df.rename(columns=rename_map)
    keep_cols = ["date", "open", "high", "low", "close", "volume", "pct_chg"]
    out = out[[c for c in keep_cols if c in out.columns]].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in [c for c in ["open", "high", "low", "close", "volume", "pct_chg"] if c in out.columns]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.sort_values("date").dropna(subset=["open", "high", "low", "close"])
    out = out[(out["date"] >= pd.Timestamp(start_date)) & (out["date"] <= pd.Timestamp(end_date))]
    out = repair_price_series_with_pct_chg(out, ts_code)
    out["symbol"] = ts_code
    out["is_trading"] = True
    return out.reset_index(drop=True)


def load_tushare_daily(symbol: str, start_date: str, end_date: str, source_type: str = "fund") -> pd.DataFrame:
    """Primary data loader via Tushare Pro; falls back to akshare on error."""
    if not TUSHARE_TOKEN:
        print("  [WARN] TUSHARE_TOKEN not set; using akshare.")
        return load_akshare_daily(symbol, start_date, end_date)

    pro = ts.pro_api(TUSHARE_TOKEN)
    ts_code = normalize_symbol(symbol)
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    try:
        if source_type == "map":
            df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
        else:
            df = pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        keep_cols = ["date", "open", "high", "low", "close", "volume"]
        if "pct_chg" in df.columns:
            keep_cols.append("pct_chg")
        out = df[keep_cols].copy()
        out["date"] = pd.to_datetime(out["date"])
        for col in [c for c in ["open", "high", "low", "close", "volume", "pct_chg"] if c in out.columns]:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out = out.sort_values("date").dropna(subset=["open", "high", "low", "close"])
        out = out[(out["date"] >= pd.Timestamp(start_date)) & (out["date"] <= pd.Timestamp(end_date))]
        out = repair_price_series_with_pct_chg(out, ts_code)
        out["symbol"] = ts_code
        out["is_trading"] = True
        return out.reset_index(drop=True)
    except Exception as exc:
        if source_type == "fund":
            print(f"  [DATA FALLBACK] {get_symbol_label(ts_code)} tushare unavailable, fallback to akshare: {exc}")
            return load_akshare_daily(ts_code, start_date, end_date)
        raise


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
