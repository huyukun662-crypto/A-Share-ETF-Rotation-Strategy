"""Configuration, constants, and ETF universe definitions.

All thresholds, category mappings, parameter search ranges and the
StrategyConfig dataclass live in this module.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd

# ---------------------------------------------------------------------------
# Environment hygiene
# ---------------------------------------------------------------------------
for _k in [
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "ALL_PROXY", "all_proxy",
]:
    os.environ.pop(_k, None)
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

# ---------------------------------------------------------------------------
# Credentials (read from environment, never hard-coded)
# ---------------------------------------------------------------------------
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

# ---------------------------------------------------------------------------
# Trigger & Notification Config
# ---------------------------------------------------------------------------
ENABLE_WECHAT_PUSH = bool(SERVERCHAN_SENDKEY)
WEEKLY_SIGNAL_RUN_HOUR = 17
USE_TRADING_CALENDAR = True
NOTIFY_AFTER_WEEKLY_SIGNAL = True

# ---------------------------------------------------------------------------
# Date windows
# ---------------------------------------------------------------------------
START_DATE = "2009-01-01"
TRAIN_END_DATE = "2019-12-31"
TRAIN_SEARCH_START_DATE = "2009-01-01"
TRAIN_SEARCH_END_DATE = "2016-12-31"
VALIDATION_START_DATE = "2017-01-01"
VALIDATION_END_DATE = "2019-12-31"
OOS_START_DATE = "2020-01-01"
END_DATE = pd.Timestamp.today().strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------
BENCHMARK_CODE = "510300.SH"
BENCHMARK_NAME = "沪深300ETF华泰柏瑞"

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent.parent
except NameError:
    BASE_DIR = Path.cwd()
OUTPUT_DIR = BASE_DIR / "ETF_Result"
N_WORKERS = os.cpu_count() or 1

# ---------------------------------------------------------------------------
# Parameter search ranges (stage 1: core neighborhood)
# ---------------------------------------------------------------------------
EMA_WINDOW_RANGE = [25, 30, 35]
RSI_ENTRY_RANGE = [46, 48]
RSI_EXIT_RANGE = [48, 50]
CATEGORY_ENTRY_SHIFT_RANGE = [-1.2, -0.6]
CATEGORY_SOFT_SHIFT_RANGE = [-0.6, -0.3, 0.0]
CATEGORY_STOP_SHIFT_RANGE = [-0.5, 0.0]
STRONG_DAYS_SHIFT_RANGE = [-1, 0]
USE_RELATIVE_STRENGTH_FILTER_RANGE = [False]

# Candidate-count -> portfolio exposure mapping variants
CANDIDATE_EXPOSURE_MAP_OPTIONS = {
    "base":       ((5, 1.00), (4, 0.96), (3, 0.90), (2, 0.78), (1, 0.60), (0, 0.00)),
    "balanced":   ((5, 0.88), (4, 0.82), (3, 0.74), (2, 0.60), (1, 0.42), (0, 0.00)),
    "aggressive": ((5, 1.00), (4, 1.00), (3, 0.98), (2, 0.92), (1, 0.80), (0, 0.00)),
}
EXPOSURE_MAP_VERSION_RANGE = ["base", "balanced", "aggressive"]

# ---------------------------------------------------------------------------
# Risk targets / budgets
# ---------------------------------------------------------------------------
MAX_DRAWDOWN_LIMIT = -0.15
TRAIN_DRAWDOWN_BUDGET = -0.20
TEST_DRAWDOWN_TARGET = -0.12
VALIDATION_DRAWDOWN_CAP = -0.12
TARGET_OOS_DRAWDOWN = -0.15
TARGET_OOS_ANNUAL_RETURN = 0.2503

# ---------------------------------------------------------------------------
# Baseline parameter set (used as the search neighborhood center)
# ---------------------------------------------------------------------------
BEST_OOS_BASELINE_PARAMS = {
    "ema_window": 25,
    "rsi_entry": 44.0,
    "rsi_exit": 50.0,
    "stock_entry_shift": -1.2,
    "commodity_entry_shift": -1.2,
    "dividend_entry_shift": -1.2,
    "stock_soft_shift": -0.6,
    "commodity_soft_shift": -0.3,
    "dividend_soft_shift": -0.6,
    "stock_stop_shift": -0.5,
    "commodity_stop_shift": -0.5,
    "dividend_stop_shift": -0.5,
    "strong_days_shift": -1,
    "use_relative_strength_filter": False,
    "exposure_map_version": "base",
    "portfolio_exposure_cap": 1.0,
    "dd_limit_1": -0.24,
    "dd_limit_2": -0.28,
    "dd_limit_3": -0.36,
    "dd_cap_1": 0.98,
    "dd_cap_2": 0.92,
    "dd_cap_3": 0.85,
    "defensive_mode": "cash",
    "defensive_allocation_cap": 0.0,
    "defensive_trigger_dd": -0.10,
}

# ---------------------------------------------------------------------------
# Light-risk refinement grid
# ---------------------------------------------------------------------------
LIGHT_RISK_EXPOSURE_MAP_RANGE = ["base", "balanced", "aggressive"]
LIGHT_RISK_PORTFOLIO_CAP_RANGE = [0.80, 0.85, 0.90, 0.95, 1.00]
LIGHT_RISK_DD_LIMIT_SETS = [
    (-0.18, -0.22, -0.28),
    (-0.20, -0.24, -0.30),
    (-0.08, -0.12, -0.16),
    (-0.10, -0.14, -0.18),
    (-0.12, -0.16, -0.20),
]
LIGHT_RISK_DD_CAP_SETS = [
    (0.92, 0.82, 0.70),
    (0.90, 0.78, 0.64),
    (0.85, 0.70, 0.55),
    (0.88, 0.74, 0.60),
    (0.95, 0.86, 0.74),
]
DEFENSIVE_MODES = ["cash", "bond"]
DEFENSIVE_ALLOCATION_CAP_RANGE = [0.20, 0.30, 0.40, 0.50]
DEFENSIVE_TRIGGER_DD_RANGE = [-0.08, -0.10, -0.12]

# ---------------------------------------------------------------------------
# ETF universe
# ---------------------------------------------------------------------------
TREND_ETF_POOL: Dict[str, str] = {
    # Stock / sector ETFs
    "电池ETF广发": "159755.SZ", "新能源车ETF华夏": "515030.SH", "半导体ETF国联安": "512480.SH", "航空航天ETF华夏": "159227.SZ",
    "电网设备ETF华夏": "159326.SZ", "游戏ETF华夏": "159869.SZ", "房地产ETF": "512200.SZ", "银行ETF华宝": "512800.SH",
    "光伏ETF": "159857.SZ", "机器人ETF华夏": "562500.SH", "家电ETF富国": "561120.SH", "中证红利ETF招商": "515080.SH",
    "建材ETF富国": "516750.SH", "金融科技ETF华宝": "159851.SZ", "创新药ETF": "159992.SZ", "人工智能ETF": "515980.SH",
    "软件ETF国泰": "515230.SH", "通信ETF国泰": "515880.SH", "消费电子ETF": "159779.SZ", "卫星ETF富国": "563230.SH",
    "稀土ETF富国": "159713.SZ", "化工ETF": "159870.SZ", "油气ETF博时": "561760.SH", "有色ETF大成": "159980.SZ",
    "云计算ETF招商": "159890.SZ", "证券ETF": "159841.SZ", "酒ETF鹏华": "512690.SH", "畜牧ETF": "159867.SZ",
    "钢铁ETF国泰": "515210.SH", "煤炭ETF国泰": "515220.SH", "证券ETF国泰": "512880.SH", "影视ETF": "159855.SZ",
    "石油ETF国泰": "561360.SH", "豆粕ETF华夏": "159985.SZ", "红利低波ETF富国": "159525.SZ", "黄金ETF易方达": "159934.SZ",
    "创业板ETF广发": "159952.SZ",
    # Bond ETFs (defensive pool)
    "可转债ETF博时": "511380.SH", "信用债ETF博时": "159396.SZ", "公司债ETF平安": "511030.SH", "短融ETF海富通": "511360.SH",
    "十年国债ETF国泰": "511260.SH", "30年国债ETF鹏扬": "511090.SH", "国债ETF国泰": "511010.SH",
}

SYMBOL_NAME_MAP: Dict[str, str] = {code: name for name, code in TREND_ETF_POOL.items()}
SYMBOL_NAME_MAP[BENCHMARK_CODE] = BENCHMARK_NAME

# ---------------------------------------------------------------------------
# Asset category mapping (stock / commodity / dividend / bond)
# ---------------------------------------------------------------------------
ASSET_CATEGORY_MAP: Dict[str, str] = {
    "159755.SZ": "stock", "515030.SH": "stock", "512480.SH": "stock", "159227.SZ": "stock", "159326.SZ": "stock",
    "159869.SZ": "stock", "512200.SZ": "stock", "512800.SH": "dividend", "159857.SZ": "stock", "562500.SH": "stock",
    "561120.SH": "stock", "515080.SH": "dividend", "516750.SH": "stock", "159851.SZ": "stock", "159992.SZ": "stock",
    "515980.SH": "stock", "515230.SH": "stock", "515880.SH": "stock", "159779.SZ": "stock", "563230.SH": "stock",
    "159713.SZ": "stock", "159870.SZ": "stock", "561760.SH": "stock", "159980.SZ": "stock", "159890.SZ": "stock",
    "159841.SZ": "stock", "512690.SH": "stock", "159867.SZ": "stock", "515210.SH": "commodity", "515220.SH": "commodity",
    "512880.SH": "stock", "159855.SZ": "stock", "561360.SH": "commodity", "159985.SZ": "commodity", "159934.SZ": "commodity",
    "511380.SH": "bond", "159396.SZ": "bond", "511030.SH": "bond", "511360.SH": "bond", "511260.SH": "bond",
    "511090.SH": "bond", "511010.SH": "bond", "159525.SZ": "dividend", "159952.SZ": "stock",
}

OPTIMIZED_CATEGORIES = ("stock", "commodity", "dividend")
THREE_CLASS_MAP = {k: v for k, v in ASSET_CATEGORY_MAP.items() if v in OPTIMIZED_CATEGORIES}
BOND_CLASS_MAP = {k: v for k, v in ASSET_CATEGORY_MAP.items() if v == "bond"}

# ---------------------------------------------------------------------------
# Category-specific LogBias thresholds (in %)
#   ENTRY    : hard-entry threshold (logbias must exceed this)
#   STOP     : hard-exit threshold (logbias below -> force exit)
#   OVERHEAT : over-stretched zone (no new entries, may soft-trim)
#   SOFT     : soft-entry threshold for fill when few hard candidates
#   STRONG   : minimum "strong" days in rolling 10 days to qualify
# ---------------------------------------------------------------------------
ENTRY = {"stock": 4.0, "commodity": 2.8, "dividend": 1.0}
STOP = {"stock": -5.5, "commodity": -4.8, "dividend": -3.0}
OVERHEAT = {"stock": 16.5, "commodity": 11.0, "dividend": 6.0}
SOFT = {"stock": 0.8, "commodity": 0.3, "dividend": 0.0}
STRONG = {"stock": 3, "commodity": 2, "dividend": 2}


# ---------------------------------------------------------------------------
# Strategy configuration
# ---------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    ema_window: int = 20
    top_n: int = 5
    fee_rate: float = 0.0003
    slippage_rate: float = 0.0005
    stamp_duty_rate: float = 0.0
    initial_capital: float = 1_000_000.0
    dynamic_holdings: bool = True
    min_holdings: int = 3
    max_holdings: int = 5
    # Drawdown-triggered exposure caps
    dd_limit_1: float = -0.24
    dd_limit_2: float = -0.28
    dd_limit_3: float = -0.36
    dd_cap_1: float = 0.98
    dd_cap_2: float = 0.92
    dd_cap_3: float = 0.85
    portfolio_exposure_cap: float = 1.0
    # Daily risk controls
    enable_daily_stop: bool = True
    enable_overheat_trim: bool = True
    trim_ratio: float = 0.15
    # Candidate-count -> exposure mapping
    candidate_exposure_map: tuple = CANDIDATE_EXPOSURE_MAP_OPTIONS["base"]
    # Filters / shifts
    use_relative_strength_filter: bool = True
    strong_days_required_shift: int = 0
    exposure_map_version: str = "base"
    # Rotation score weights
    score_weight_logbias: float = 0.4
    score_weight_slope: float = 0.2
    score_weight_ret20: float = 0.2
    score_weight_relative_strength: float = 0.2
    # Defensive allocation (cash or bond) when drawdown breaches trigger
    defensive_mode: str = "cash"
    defensive_allocation_cap: float = 0.0
    defensive_trigger_dd: float = -0.10

    # Trigger & Notification Config
    use_trading_calendar: bool = USE_TRADING_CALENDAR

