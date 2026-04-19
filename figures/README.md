# Figures / 关键图表

Running `python -m src.pipeline` will regenerate the charts in this
folder (matplotlib, 150 dpi).

运行 `python -m src.pipeline` 会在该目录刷新所有图表（matplotlib，
150 dpi）。

## 图表清单 · Charts

### `train_test_comparison.png`
Three-panel overlay (16×12 inches):

1. **NAV** — strategy NAV vs CSI-300 benchmark NAV.
2. **Excess NAV** — `strategy_nav / benchmark_nav` with a dashed 1.0
   reference line.
3. **Drawdown** — strategy vs benchmark drawdown.

三联叠加图（16×12 英寸）：策略 / 基准 NAV、超额 NAV、回撤并排。

### `equity_curves_side_by_side.png` (optional)
Side-by-side train vs OOS equity curves.  Useful for interview
decks — renders the regime-change between the two windows cleanly.

训练期 vs 样本外权益曲线并排图，适合面试汇报展示两个区间的
体制切换。

## 如何自定义 · Extending

`plot_results()` in `src/pipeline.py` is the single rendering entry
point.  To add a new chart:

1. Write a new helper under `src/pipeline.py` that consumes the
   equity / trades / metrics dataframes.
2. Call it from `save_desktop_artifacts()` alongside the existing
   plotters.
3. The saved PNG lands in both `ETF_Result/` and this folder (via
   git tracking).

新增图表只需在 `src/pipeline.py::plot_results` 下面新增 helper，再
从 `save_desktop_artifacts` 里调用即可。
