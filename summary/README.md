# One-Page Summary / 一页纸总结

## Elevator pitch
A weekly-rebalanced A-share ETF rotation strategy that blends
log-bias trend deviation, Wilder RSI(14), 20-day momentum and
cross-sectional relative strength into a single `rotation_score`,
selects 3–5 top-scored ETFs across **stock / commodity / dividend**
buckets, and enforces a three-tier drawdown-triggered exposure cap
plus a defensive cash / bond fallback.

一张嘴讲清楚：周度调仓的 A 股 ETF 板块轮动 —— 用
LogBias + RSI + 20 日动量 + 相对沪深 300 强弱打分，在
股票 / 商品 / 红利三桶里选 3–5 只 ETF，三档回撤阈值自动降低
暴露，极端回撤切换到现金 / 债券池。

## Why it works
- A 股板块轮动快 → 单一宽基跟不上主题；ETF 打包 + 规则化选品刚好
  匹配板块层面的动量持续性。
- 对数偏离 (LogBias) 解决简单 Bias 在高/低价位的不对称；RSI 过滤
  震荡假突破；相对强弱 (vs 沪深 300) 捕捉横截面领涨。

## Headline metrics (2020-01 ~ 2026-04 OOS)
| | OOS | CSI-300 |
| --- | ---: | ---: |
| Annual return | **35.25%** | -0.8% |
| Sharpe | **1.48** | — |
| Max drawdown | -12.91% | -39.6% |
| Calmar | **2.73** | — |
| Win rate / avg hold | 45.7% / 12.4 d | — |

> Training (2009–2019) Sharpe 0.54, annual 4.83%, max DD -10.35%.
> Parameters chosen with validation-set max-DD ≤ 12%.

## Architecture (60-second tour)
```
Tushare / akshare ──► raw OHLCV ──► indicators (LogBias, RSI14, ret_20, RS)
                                     │
                                     ▼
                        per-category thresholds (ENTRY/STOP/…)
                                     │
                                     ▼
              rotation_candidate + soft_candidate panel
                                     │
                          weekly rebalance ── score → 3–5 picks
                                     │
                 drawdown caps (3-tier) + defensive cash/bond
                                     │
                                     ▼
                       NAV / trades / next-day target CSV
```

## Parameter search in one picture
- Stage 1: `ema_window × rsi_entry × rsi_exit × exposure_map` (36 combos).
- Stage 2: 9 category-threshold shifts × strong-days × RS filter (1024 combos).
- Ranking: **validation max-DD ≤ 12%** → **train/val return gap ≤ 8%**
  → highest validation annual return.

## Talking points
1. **Discipline over discovery** — every parameter choice has a
   validation-set sanity check; the OOS window is never touched
   during tuning.
2. **Risk in layers** — the strategy uses *three* mechanisms (weekly
   candidate count, drawdown caps, defensive allocation) instead of
   a single hard stop, because hard stops in A-share ETFs tend to
   round-trip.
3. **Cross-sectional beats time-series** — relative strength vs
   CSI-300 is the factor that survives regime change best.
4. **Live-ready hooks** — `latest_buy_signal` + `latest_trade_plan`
   export next-day target weights as a CSV, so the backtester is a
   drop-in signal generator.

## Risks / what I'd test next
- ETF listing recency → pre-2020 coverage is thin for sector buckets.
- No hedging / financing cost model.
- Grid search is local — consider Bayesian optimisation and
  cross-regime stability tests (2015 crash / 2018 trade war / 2022
  pandemic selloff split tests).

## Sources & reading order
1. `summary/` (this file)
2. `README.md` (bilingual full deck)
3. `strategy/etf_sector_rotation_strategy.ipynb`
4. `src/` (modular package)
5. `results/` and `figures/`
