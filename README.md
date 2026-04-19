# ETF Sector Rotation Strategy
# ETF 板块轮动策略

> A weekly-rebalanced A-share ETF sector rotation strategy combining
> log-bias trend deviation, Wilder's RSI(14), 20-day return momentum and
> cross-sectional relative strength. Optimised on 2009–2016 train /
> 2017–2019 validation, with a walk-forward out-of-sample test on
> 2020-present.

![Strategy NAV vs Benchmark · Excess NAV · Drawdown (OOS 2020-2026)](figures/train_test_comparison.png)

> **OOS Highlights (2020–2026)**: Sharpe **1.48** · Annualised **35.25%** ·
> Max Drawdown **-12.91%** · Calmar **2.73** · Benchmark (510300.SH)
> annualised **-0.8%**.

---

## 简体中文

### 项目概述
本项目基于 A 股宽基 + 行业 + 商品 + 红利 ETF 全景样本，构建了一套
**周度轮动策略**：以对数偏离度 (LogBias)、Wilder RSI(14)、20 日动量、
相对沪深 300 强弱作为信号，经 Train / Validation / OOS 三段样本分离
的网格搜索确定参数，并通过三档回撤阈值触发仓位收敛与防守性现金/债
券池切换，实现"进可攻、退可守"的板块轮动。

样本期：2009-01-01 至今；训练期：2009–2019；样本外：2020 至今。
基准：沪深 300ETF 华泰柏瑞 (510300.SH)。

### 论文来源 / 参考
- 自研项目。方法论融合了动量 / 趋势跟随 (Moskowitz, Ooi &
  Pedersen 2012) 与板块轮动 / 相对强弱 (Faber 2007, Gray & Vogel
  2016) 两支文献，并加入 RSI + LogBias 的 A 股风格调参。

### 仓库框架
```
ETF-Sector-Rotation-Strategy/
├─ strategy/     # 原始 Jupyter Notebook 及策略说明
├─ src/          # 模块化 Python 源码 (配置 / 数据 / 信号 / 回测 / 搜索 / 主流程)
├─ factor/       # LogBias / RSI / 相对强弱 / 动量等因子定义与解释
├─ backtest/     # 回测框架说明 (日级事件循环、周度调仓、日度风险控制)
├─ results/      # 最终参数、回测指标、权益曲线、信号 Top 10
├─ figures/      # 策略 vs 基准 NAV、超额 NAV、回撤叠加图
├─ report/       # 扩展研究报告 (PDF/Markdown，逐步补齐)
└─ summary/      # 面试一页纸总结 (interview-ready)
```
建议阅读顺序：`summary/` → `README.md` → `strategy/` → `src/` →
`results/` → `figures/`.

### 核心标签
`A 股 ETF`、`板块轮动`、`动量`、`趋势跟随`、`RSI`、`LogBias`、`相对强弱`、`周度调仓`、`回撤触发仓位管理`、`样本外验证`。

### 研究动机
A 股市场的风格切换极为频繁：
- **板块间** 轮动 (新能源 → 半导体 → 红利 → 商品)；
- **风格内** 分化 (成长/红利/周期)。

单一宽基 ETF 难以同时捕捉多个主题趋势；主动选股则受限于信息成本。
因此需要一个规则化的 **ETF 板块轮动模型**，具备以下特性：
1. **趋势友好**：在大势上行时尽可能满仓跟随；
2. **横截面强弱**：优选相对强势的类别；
3. **风险自适应**：回撤扩大时自动收敛、极端情况下切换防守；
4. **低频可操作**：周度调仓、可按目标仓位执行。

### 定价 / 信号框架
对每一只 ETF，在日频上构建：

| 因子 | 计算 | 含义 |
| --- | --- | --- |
| `LogBias` | `(log(close) - log(EMA(close, N))) * 100` | 相对 EMA 趋势的对数偏离，正值表示价格高于趋势 |
| `LogBias slope` | `LogBias - LogBias.shift(5)` | LogBias 5 日变化，刻画偏离加速 / 衰减 |
| `RSI14` | Wilder's RSI(14) on close | 短期动量强度 |
| `ret_20` | 20 日收益 | 中期动量 |
| `relative_strength` | `ret_20 - benchmark_ret_20` | 对沪深 300 的超额动量 |
| `rotation_score` | `0.4·LogBias + 0.2·slope + 0.2·ret_20·100 + 0.2·RS·100 + 0.1·(RSI-50)` | 综合轮动打分 |

每一只 ETF 按资产类别 (stock / commodity / dividend) 设定一套
`ENTRY / STOP / OVERHEAT / SOFT / STRONG` 阈值，再通过 11 维参数
搜索找到最优 shift。

### 模型设计
- **硬候选 (rotation_candidate)**：`LogBias > ENTRY_shift`、近 10 日强势
  天数 ≥ `STRONG_shift`、`close > price_EMA`、`LogBias ≤ OVERHEAT`、
  `RSI14 > rsi_entry`、`is_trading`。
- **软候选 (soft_candidate)**：`close > price_EMA`、`LogBias > SOFT_shift`、
  `RSI14 > max(50, rsi_entry-2)` — 用于候选不足时补位。
- **周度调仓**：每周 ISO-week 切换日的开盘按目标权重买入 / 卖出；
  动态持仓数 3–5。
- **权重映射**：候选数 (0/1/2/3/4/5) → 组合暴露 (base / balanced /
  aggressive 三档)。
- **三档回撤收敛**：`dd_limit_{1,2,3}` 触发时将组合暴露压到
  `dd_cap_{1,2,3}`。
- **防守性配置**：回撤深度超过 `defensive_trigger_dd` 时，将一部分
  权重切换至 `cash` 或债券 ETF 池 (`defensive_allocation_cap`)。
- **日度风险控制**：hard-exit (跌破 STOP 阈值)、soft-trim (触及 OVERHEAT)。

### 错误定价 / 超额信号
本策略的 **Alpha 来源** 是 A 股同类资产之间的短中期趋势错位：
- 板块之间动量延续；
- 估值 / 交易拥挤度反映在 LogBias 与 RSI 的分化；
- 相对沪深 300 的 ret_20 差异捕捉横截面强弱。

通过严格的 Train / Validation 分离 + 验证集回撤约束 (≤12%) 避免
过拟合，OOS 区间仅用于最终评估。

### 策略构建
完整流程见 `src/pipeline.py::main()`，核心步骤：

1. `load_universe()` — 由 Tushare 拉取 ETF 行情，akshare 兜底。
2. `optimize_params_on_training_set()` — 两阶段网格搜索
   (核心邻域 36 组 + 阈值邻域 1024 组)。
3. `run_backtest_on_period()` — 分别在训练区间和样本外区间回测。
4. `save_desktop_artifacts()` — 输出指标、权益曲线、图表到 `ETF_Result/`。

### 回测结果
| 指标 | 训练 (2009–2019) | 样本外 (2020–2026) |
| --- | ---: | ---: |
| 年化收益 | 4.83% | **35.25%** |
| Sharpe 比率 | 0.5423 | **1.4787** |
| 最大回撤 | -10.35% | -12.91% |
| Calmar | 0.47 | **2.73** |
| 胜率 | 44.60% | 45.67% |
| 平均持仓天数 | 12.8 | 12.4 |
| 基准 (510300) | 年化 2.1% | 年化 -0.8% |

> 训练集收益受 2009–2012 低估值区间影响较大；参数选择以验证集最大
> 回撤 ≤ 12% 为硬约束，使得策略在 OOS 的回撤同样可控。

![策略 NAV vs 基准、超额 NAV、回撤对比（2020-2026 OOS）](figures/train_test_comparison.png)

*OOS 区间：策略 NAV 由 1.0 攀升至约 5.05；基准 510300 在同期仅在 1.0 附近波动；超额 NAV 持续走高至 ~4.5；策略最大回撤 -12.91%，显著好于基准在 2024 年接近 -45% 的深度回撤。*

### 关键图表
- `figures/train_test_comparison.png` — 策略 / 基准 NAV、超额 NAV、回撤叠加（见上图）；
- `figures/equity_curves_side_by_side.png` — 训练期 vs 样本外权益曲线并排对比；
- `results/top10_scored_targets_test.csv` — 最新 Top 10 打分候选。

### 核心洞察
1. **单因子不够**：LogBias 单用会在震荡市反复失效；叠加 RSI 门槛能过滤假突破。
2. **相对强弱优于绝对动量**：在 2024-2025 高波动行情中，相对沪深 300 的
   ret_20 显著好于单用 20 日绝对收益。
3. **回撤档位比止损更稳**：硬止损容易"追高卖低"，分档降低总暴露
   同时保留头部仓位，更符合 ETF 轮动的实际节奏。
4. **防守切换触发要晚**：`defensive_trigger_dd = -10%` 才触发，
   可避免 2023 年那类短期急跌后的错失反弹。

### 局限性
- 成分变动：行业 ETF 上市时间差异较大，2020 年前样本稀薄。
- 手续费假设固定 (0.0003 佣金 + 0.0005 滑点)，尚未刻画融券 / 对冲成本。
- 周度调仓忽略盘中波动；极端跌停日的实际执行价会与回测偏离。
- 参数搜索只覆盖邻域，未进行全局 / 贝叶斯优化。

### 后续优化
- 加入 **宏观状态因子** (社融、M1、美债 10Y) 作为体制开关；
- **波动率定向调仓**：用 GARCH 或已实现波动替换固定 exposure cap；
- 引入 **交易冲击成本模型** 与做市撮合；
- 将最终信号对接到实盘 (Quant-Investor / Vnpy) 做小额灰度。

### 完整报告
见 `report/` (逐步补齐 PDF 研究报告)。

### 项目贡献
- 搭建了从数据、因子、回测、参数搜索到结果归档的端到端流水线；
- 清洗 Tushare 价格跳变、akshare 兜底、ETF 日历对齐等工程细节均已处理；
- 提供 `latest_buy_signal` 与 `latest_trade_plan` 两级实盘接口
  (周度买入信号 + 日度风控调仓)，可直接输出下一交易日目标持仓 CSV。

### 引用说明
如果本项目对您的研究有帮助，请引用：
```
@misc{etf-sector-rotation-2026,
  author = {Derick Hu},
  title  = {ETF Sector Rotation Strategy: LogBias + RSI with Weekly Rebalance on A-share ETF Universe},
  year   = {2026},
  url    = {https://github.com/<your-handle>/ETF-Sector-Rotation-Strategy}
}
```

---

## English Version

### Overview
A weekly-rebalanced A-share ETF rotation strategy across three asset
categories — **stock / commodity / dividend** — with a bond pool as a
defensive allocation.  Signals combine log-bias trend deviation, Wilder
RSI(14), 20-day momentum and cross-sectional relative strength, blended
into a `rotation_score`.

Sample: 2009-01-01 to today. Benchmark: CSI-300 ETF (510300.SH).
Train / Validation / OOS split: 2009–2016 / 2017–2019 / 2020–present.

### Paper Source / References
- Original research.  Methodology draws on momentum / trend-following
  (Moskowitz, Ooi & Pedersen 2012) and sector rotation / cross-sectional
  relative strength (Faber 2007; Gray & Vogel 2016), tuned for the
  A-share ETF universe with an RSI + LogBias style filter.

### Repository Structure
```
ETF-Sector-Rotation-Strategy/
├─ strategy/     # Source Jupyter notebook and one-page strategy write-up
├─ src/          # Modular Python package (config / data / signal / backtest / search / main)
├─ factor/       # LogBias / RSI / relative-strength factor definitions
├─ backtest/     # Backtester spec — daily loop, weekly rebalance, daily risk controls
├─ results/      # Best parameters, metric tables, equity curves, top-10 signals
├─ figures/      # Strategy vs benchmark NAV, excess NAV and drawdown charts
├─ report/       # Long-form research report (rolling)
└─ summary/      # One-page interview-ready summary
```
Suggested reading order: `summary/` → `README.md` → `strategy/` →
`src/` → `results/` → `figures/`.

### Core Tags
`A-share ETF`, `sector rotation`, `momentum`, `trend following`, `RSI`,
`LogBias`, `relative strength`, `weekly rebalance`, `drawdown-triggered
exposure`, `out-of-sample testing`.

### Motivation
Style rotations in A-shares are fast and uneven — from new-energy to
semiconductors to dividend to commodities.  A single broad-based ETF
can't keep up with multiple concurrent themes, and stock-picking
incurs high information costs.  A rule-based **ETF rotation model**
is a natural middle-ground: trend-friendly, cross-sectionally aware,
risk-adaptive, and operable at weekly frequency.

### Pricing / Signal Framework
Daily factors computed per symbol:

| Factor | Formula | Meaning |
| --- | --- | --- |
| `LogBias` | `(log(close) - log(EMA(close, N))) * 100` | Log deviation from EMA trend |
| `LogBias slope` | `LogBias - LogBias.shift(5)` | 5-day acceleration of the deviation |
| `RSI14` | Wilder's RSI(14) | Short-term momentum strength |
| `ret_20` | 20-day return | Medium-term momentum |
| `relative_strength` | `ret_20 - benchmark_ret_20` | Excess over CSI-300 |
| `rotation_score` | weighted blend (see below) | Composite ranking score |

```
rotation_score = 0.4·LogBias
               + 0.2·LogBias_slope
               + 0.2·(ret_20 * 100)
               + 0.2·(relative_strength * 100)
               + 0.1·(RSI14 − 50)
```

Per-category thresholds (`ENTRY / STOP / OVERHEAT / SOFT / STRONG`)
are searched by shifting each threshold within the train / validation
neighborhood.

### Model Design
- **Hard candidate** — `LogBias > ENTRY_shift`, strong-days-in-10 ≥
  `STRONG_shift`, `close > price_EMA`, `LogBias ≤ OVERHEAT`,
  `RSI14 > rsi_entry`, `is_trading`.
- **Soft candidate** — `close > price_EMA`, `LogBias > SOFT_shift`,
  `RSI14 > max(50, rsi_entry − 2)`.  Acts as a backfill when hard
  candidates are scarce.
- **Weekly rebalance** on the open of every ISO-week boundary; dynamic
  3–5 holdings.
- **Candidate-count → exposure map** (base / balanced / aggressive) —
  translates the number of live candidates into a portfolio exposure
  target.
- **Three-tier drawdown caps** — `dd_limit_{1,2,3}` trigger pinned
  exposures `dd_cap_{1,2,3}`.
- **Defensive allocation** — when live drawdown breaches
  `defensive_trigger_dd`, a fraction `defensive_allocation_cap` is
  routed to `cash` or a bond-ETF basket.
- **Daily risk controls** — hard-exit when `LogBias < STOP`; soft-trim
  at the OVERHEAT level.

### Mispricing / Alpha Signal
Alpha stems from short-to-medium term dispersion **across** A-share
ETFs:
- momentum persistence between sectors;
- crowding / valuation signals embedded in LogBias and RSI;
- cross-sectional ret_20 vs CSI-300.

Over-fitting is controlled by a strict train / validation split with
a validation max-drawdown cap (≤ 12%); OOS is held out for final
evaluation only.

### Strategy Design
The full pipeline lives in `src/pipeline.py::main()`:

1. `load_universe()` — pull OHLCV from Tushare, akshare fallback.
2. `optimize_params_on_training_set()` — two-stage grid search (36
   + 1024 combos) using `joblib.Parallel`.
3. `run_backtest_on_period()` — run the tuned params on train and
   OOS windows separately.
4. `save_desktop_artifacts()` — dump metrics, equity curves and
   comparison plots to `ETF_Result/`.

### Results
| Metric | Training (2009–2019) | OOS (2020–2026) |
| --- | ---: | ---: |
| Annual return | 4.83% | **35.25%** |
| Sharpe ratio | 0.5423 | **1.4787** |
| Max drawdown | -10.35% | -12.91% |
| Calmar ratio | 0.47 | **2.73** |
| Win rate | 44.60% | 45.67% |
| Avg holding days | 12.8 | 12.4 |
| Benchmark (510300) | 2.1% annual | -0.8% annual |

> Training-set returns are dragged down by the 2009–2012 low-valuation
> regime.  Parameter selection enforces a validation-set max-drawdown
> of ≤ 12%, which translates to a similarly bounded OOS drawdown.

![Strategy NAV vs Benchmark, Excess NAV, Drawdown (2020-2026 OOS)](figures/train_test_comparison.png)

*OOS results: strategy NAV climbs from 1.0 to ~5.05 while the CSI-300
ETF benchmark hovers near 1.0; excess NAV steadily rises to ~4.5; the
strategy's max drawdown (-12.91%) is substantially shallower than the
benchmark's ~-45% drawdown in late 2024.*

### Key Figures
- `figures/train_test_comparison.png` — overlay of strategy / benchmark
  NAV, excess NAV and drawdown across the OOS period (shown above).
- `figures/equity_curves_side_by_side.png` — train vs OOS equity
  curves side-by-side.
- `results/top10_scored_targets_test.csv` — latest Top-10 scored
  candidates from the rolling panel.

### Key Insights
1. **No single factor is enough** — LogBias alone whipsaws in ranging
   markets; adding an RSI gate cuts the false breakouts.
2. **Relative strength beats absolute momentum** — in 2024-2025, ranking
   by `ret_20 − benchmark_ret_20` dominated absolute `ret_20`.
3. **Exposure tiers > hard stops** — trimming exposure in steps
   preserves upside on reversals where a hard stop would have locked
   in the drawdown.
4. **Late defensive trigger (-10%) avoids overreaction** — short-sharp
   pullbacks like 2023 would have been mis-served by a tighter cutoff.

### Limitations
- Uneven listing dates → pre-2020 sector-ETF coverage is sparse.
- Fixed-rate cost model (0.0003 commission + 0.0005 slippage) — does
  not capture hedging, financing or borrow costs.
- Weekly rebalance ignores intraday dynamics; limit-down days will
  diverge from the simulated fills.
- Grid search is local; no global / Bayesian optimisation yet.

### Future Work
- Add **macro-regime factors** (社融 / M1 / 10Y UST) as rotation
  switches.
- Replace the fixed exposure cap with a **volatility-targeting** rule
  (GARCH or realised vol).
- Plug in a **trading-impact model** and a smarter execution engine.
- Wire the live signal into a paper-trading / small-capital deployment.

### Full Report
See `report/` (long-form PDF will be rolled out).

### Contribution
- End-to-end pipeline from data ingest → factor → backtest → parameter
  search → archive.
- Handles Tushare price-jump repairs, akshare fallback, and calendar
  alignment — engineering details that often trip up reproductions.
- Ships with both `latest_buy_signal` (weekly) and `latest_trade_plan`
  (daily risk-control) hooks, and a one-click CSV export of the next
  trading day's target holdings.

### Citation
If this repo is useful for your research, please cite:
```
@misc{etf-sector-rotation-2026,
  author = {Derick Hu},
  title  = {ETF Sector Rotation Strategy: LogBias + RSI with Weekly Rebalance on A-share ETF Universe},
  year   = {2026},
  url    = {https://github.com/<your-handle>/ETF-Sector-Rotation-Strategy}
}
```

---

### Quick Start
```bash
# 1) Install deps
pip install -r requirements.txt

# 2) Set your Tushare token (recommended) — otherwise akshare fallback is used
export TUSHARE_TOKEN=your_tushare_pro_token

# 3) Reproduce the backtest end-to-end
python -m src.pipeline

# 4) Or open the notebook
jupyter notebook strategy/etf_sector_rotation_strategy.ipynb
```

### License
MIT — see [LICENSE](LICENSE).
