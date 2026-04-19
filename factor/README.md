# Factor Definitions / 因子定义

The strategy combines five factors per symbol:

本策略在每只 ETF 上组合五个因子：

## 1. LogBias — Log-space deviation from EMA trend

```
LogBias_t = (log(close_t) - log(EMA_N(close)_t)) * 100
```

- 计算公式：以 `log(close)` 与 EMA(log close, N) 的差值度量价格
  相对趋势的对数偏离，再乘以 100 放大到"%"量级。
- 正值：价格在趋势之上 → 处于上升动量；
- 负值：价格在趋势之下 → 下行风险增大；
- 较之简单 Bias，对数空间能让上行 / 下行幅度对称可比。

## 2. LogBias Slope — 5-day change of LogBias

```
LogBias_slope_t = LogBias_t - LogBias_{t-5}
```

刻画偏离的加速 / 衰减：`slope > 0` 表示上涨动能仍在积累；
`slope < 0` 提示趋势可能回归均线。

Captures whether the deviation itself is accelerating (fresh momentum)
or decaying (reversion toward the mean).

## 3. RSI14 — Wilder's Relative Strength Index

```
RSI = 100 - 100 / (1 + RS),   RS = avg_gain / avg_loss
```

- 采用 Wilder EMA（α = 1/14）；
- 用于区分"弱 / 中 / 强"三档动量；
- 进出场门槛 `rsi_entry` / `rsi_exit` 是参数搜索的主力。

## 4. Ret_20 — 20-day return

简单中期动量：
```
ret_20_t = close_t / close_{t-20} - 1
```

## 5. Relative Strength — 20-day return spread vs benchmark

```
RS_t = ret_20_t - benchmark_ret_20_t
```

横截面相对强弱（vs 沪深 300）。在 A 股多主题行情中，RS 比
绝对 `ret_20` 更能锁定"领涨板块"。

Cross-sectional edge vs CSI-300.  In multi-theme A-share regimes the
**relative** momentum is a better sector-leader detector than the
absolute 20-day return.

## Rotation Score — composite ranking

```
rotation_score = 0.4·LogBias
               + 0.2·LogBias_slope
               + 0.2·(ret_20 * 100)
               + 0.2·(relative_strength * 100)
               + 0.1·(RSI14 − 50)
```

权重是基于训练集统计显著性与稳定性手工设定，未作参数优化；
这一设计让打分的量级对不同板块（股票/商品/红利）具有可比性。

Weights are set deterministically (not optimised) so scores remain
comparable across categories.  All inputs are on the "% space" to
keep units aligned.

## Category-specific thresholds

每个资产类别设置基线 `ENTRY / STOP / OVERHEAT / SOFT / STRONG`，再
由参数搜索在其基础上 shift。基线值见 `src/config.py`：

| Category | ENTRY | STOP | OVERHEAT | SOFT | STRONG |
| --- | ---: | ---: | ---: | ---: | ---: |
| stock | 4.0 | -5.5 | 16.5 | 0.8 | 3 |
| commodity | 2.8 | -4.8 | 11.0 | 0.3 | 2 |
| dividend | 1.0 | -3.0 | 6.0 | 0.0 | 2 |

基线由训练集样本统计 (2009–2016) 得到，分别对应该类别 80/5/99/60
百分位。

Baselines are the ~80/5/99/60 percentiles of each category's LogBias
distribution in the training window.
