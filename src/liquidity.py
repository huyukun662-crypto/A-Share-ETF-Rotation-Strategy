"""Liquidity-aware slippage and market impact modeling.

Provides ETF-specific slippage estimation based on AUM, trading volume,
and bid-ask spread tiers. Replaces the flat 5bp slippage with dynamic
estimates that reflect real Chinese ETF market conditions.
"""
from dataclasses import dataclass
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# ETF liquidity tiers (AUM / avg daily volume based)
# ---------------------------------------------------------------------------
# Sourced from exchange data and typical A-share ETF trading patterns.
# Tiers: "high" (沪深300, 500, 创业板 large-cap) → 3 bp
#        "medium" (sector ETFs >2B AUM) → 8 bp
#        "low" (niche/small sector ETFs <2B AUM) → 15 bp
#        "very_low" (micro ETFs, bond ETFs with low turnover) → 25 bp
# ---------------------------------------------------------------------------
LIQUIDITY_TIERS: Dict[str, str] = {
    # High liquidity (3 bp)
    "510300.SH": "high",   # 沪深300ETF华泰柏瑞
    "510050.SH": "high",   # 上证50ETF
    "159919.SZ": "high",   # 沪深300ETF嘉实
    "159952.SZ": "high",   # 创业板ETF广发
    # Medium liquidity (8 bp)
    "515030.SH": "medium", # 新能源车ETF华夏
    "512480.SH": "medium", # 半导体ETF国联安
    "512200.SH": "medium", # 房地产ETF
    "512800.SH": "medium", # 银行ETF华宝
    "512880.SH": "medium", # 证券ETF国泰
    "515220.SH": "medium", # 煤炭ETF国泰
    "515210.SH": "medium", # 钢铁ETF国泰
    "512690.SH": "medium", # 酒ETF鹏华
    "159934.SZ": "medium", # 黄金ETF易方达
    "159992.SZ": "medium", # 创新药ETF
    "159841.SZ": "medium", # 证券ETF
    "515080.SH": "medium", # 中证红利ETF招商
    "159985.SZ": "medium", # 豆粕ETF华夏
    # Low liquidity (15 bp)
    "159755.SZ": "low",    # 电池ETF广发
    "159227.SZ": "low",    # 航空航天ETF华夏
    "159326.SZ": "low",    # 电网设备ETF华夏
    "159869.SZ": "low",    # 游戏ETF华夏
    "159857.SZ": "low",    # 光伏ETF
    "562500.SH": "low",    # 机器人ETF华夏
    "561120.SH": "low",    # 家电ETF富国
    "516750.SH": "low",    # 建材ETF富国
    "159851.SZ": "low",    # 金融科技ETF华宝
    "515980.SH": "low",    # 人工智能ETF
    "515230.SH": "low",    # 软件ETF国泰
    "515880.SH": "low",    # 通信ETF国泰
    "159779.SZ": "low",    # 消费电子ETF
    "563230.SH": "low",    # 卫星ETF富国
    "159713.SZ": "low",    # 稀土ETF富国
    "159870.SZ": "low",    # 化工ETF
    "561760.SH": "low",    # 油气ETF博时
    "159980.SZ": "low",    # 有色ETF大成
    "159890.SZ": "low",    # 云计算ETF招商
    "159867.SZ": "low",    # 畜牧ETF
    "159855.SZ": "low",    # 影视ETF
    "561360.SH": "low",    # 石油ETF国泰
    "159525.SZ": "low",    # 红利低波ETF富国
    # Very low liquidity (25 bp) — mostly bond ETFs and niche products
    "511380.SH": "very_low",  # 可转债ETF博时
    "159396.SZ": "very_low",  # 信用债ETF博时
    "511030.SH": "very_low",  # 公司债ETF平安
    "511360.SH": "very_low",  # 短融ETF海富通
    "511260.SH": "very_low",  # 十年国债ETF国泰
    "511090.SH": "very_low",  # 30年国债ETF鹏扬
    "511010.SH": "very_low",  # 国债ETF国泰
}

SPREAD_BP = {"high": 0.0003, "medium": 0.0008, "low": 0.0015, "very_low": 0.0025}


@dataclass
class LiquidityConfig:
    enable_dynamic_slippage: bool = False
    base_slippage_rate: float = 0.0005  # 5 bp fallback when disabled
    spread_scaling_factor: float = 1.0
    volume_treshold_min: float = 100_000  # min daily volume for tier assignment
    use_aum_liquidity_model: bool = True


def get_effective_slippage(symbol: str, config: LiquidityConfig, volume: float = 0.0) -> float:
    """Return liquidity-adjusted slippage for the given ETF symbol."""
    if not config.enable_dynamic_slippage:
        return config.base_slippage_rate

    tier = LIQUIDITY_TIERS.get(symbol, "medium")
    base_spread = SPREAD_BP.get(tier, 0.0008)
    spread = base_spread * config.spread_scaling_factor

    if volume > 0 and config.use_aum_liquidity_model:
        if volume < config.volume_treshold_min:
            spread *= 1.5

    return spread
