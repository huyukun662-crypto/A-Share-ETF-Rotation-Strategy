# Backtest Framework / 回测框架

源码实现见 `src/backtester.py::RSIRotationBacktester`。本目录用于放置
回测细节的说明与工件。

Source: `src/backtester.py::RSIRotationBacktester`.  This folder holds
design notes and intermediate outputs for the backtest framework.

## 事件循环 · Event loop

对每一个交易日：

For each trading day:

1. **开盘** (`open`)
   - 若该日为周度调仓日，先按前一日收盘生成的目标权重执行调仓。
   - On a weekly-rebalance day, execute the target weights generated
     at the previous close.
2. **盘中** — 使用 `is_trading` 标记识别停牌，避免错误持仓估值。
   - Honour the `is_trading` flag to skip suspended names.
3. **收盘** (`close`)
   - 更新 NAV / 持仓。
   - 运行 **日度硬退出 (hard-exit)**：若 `LogBias < STOP_shift` 或
     `close < price_EMA`，强制卖出该头寸。
   - 运行 **日度软削减 (soft-trim)**：当 `LogBias > OVERHEAT` 时
     按 `trim_ratio` 裁剪单票权重。
   - 检测三档回撤阈值 `dd_limit_{1,2,3}` 并调整组合暴露上限。
   - 若 live drawdown 触及 `defensive_trigger_dd`，启用防守性现金 /
     债券池。

## 周度调仓 · Weekly rebalance

- 按 ISO week 切换日判断。
- 目标权重由 `_generate_target_weights` 根据 `rotation_score`
  在硬候选优先、软候选补位的规则下生成。
- Target weights are computed by `_generate_target_weights`, which
  prefers hard candidates and backfills with soft candidates when the
  target holding count (3–5) is unmet.

## 交易成本 · Transaction costs

`calc_trade_price` 与 `calc_transaction_cost`：
- 佣金 `fee_rate = 0.0003`
- 滑点 `slippage_rate = 0.0005`
- 卖出方向额外印花税 `stamp_duty_rate` (ETF 默认 0)

## 关键参数 · Critical parameters

| 参数 | 说明 | 默认 / Default |
| --- | --- | --- |
| `ema_window` | EMA 平滑窗口 | 25 |
| `top_n` | 单次最多持仓 | 5 |
| `min_holdings` / `max_holdings` | 动态持仓区间 | 3 / 5 |
| `dd_limit_{1,2,3}` | 回撤三档阈值 | -0.24 / -0.28 / -0.36 |
| `dd_cap_{1,2,3}` | 对应暴露上限 | 0.98 / 0.92 / 0.85 |
| `trim_ratio` | soft-trim 单票削减比例 | 0.15 |
| `defensive_trigger_dd` | 防守切换触发回撤 | -0.10 |
| `defensive_allocation_cap` | 切换到防守池的权重上限 | 0.0 (baseline) |

## 输出 · Outputs

每次 `RSIRotationBacktester.run()` 返回：
- `equity_curve` — 日频 NAV / 持仓 / 现金 / 回撤；
- `trades` — 单笔进出明细；
- `metrics` — Sharpe / 年化 / 最大回撤 / Calmar / 胜率 / 换手；
- `latest_buy_signal` — 最近一次周度调仓的目标持仓；
- `latest_trade_plan` — 最近的权重变动与触发类型（供下一交易日执行）。
