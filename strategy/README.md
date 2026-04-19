# Strategy / 策略说明

本目录保存最原始的 Jupyter Notebook（`etf_sector_rotation_strategy.ipynb`），
可端到端复现数据加载 → 因子构造 → 参数搜索 → 训练期回测 → 样本外回测
→ 产出工件的全流程。

This folder contains the source Jupyter notebook
(`etf_sector_rotation_strategy.ipynb`) — the single-file recipe that
reproduces data load → factor build → parameter search → training
backtest → out-of-sample backtest → artifact export end-to-end.

## 阅读顺序 · Reading order

1. **Cell 1–2** — Imports & config: Tushare token is read from
   `os.environ["TUSHARE_TOKEN"]`; akshare is the fallback.
2. **Cell 3–4** — Data loading and split-jump repair via `pct_chg`.
3. **Cell 5–6** — Indicators (`LogBias`, `RSI14`, `ret_20`,
   `relative_strength`, `rotation_score`).
4. **Cell 7–8** — `RSIRotationBacktester` — weekly rebalance +
   daily hard-exit / soft-trim.
5. **Cell 9–10** — Signal panel, top-10 scored targets, latest
   buy / trade-plan formatters.
6. **Cell 11–12** — Two-stage parameter search (train +
   validation) with `joblib.Parallel`.
7. **Cell 13–16** — Pipeline / main driver.
8. **Cell 17+** — Execution cells that run the training + OOS
   backtests and dump artifacts to `ETF_Result/`.

## 环境变量 · Environment

```bash
export TUSHARE_TOKEN=<your_tushare_pro_token>   # 可选 / optional
```

If `TUSHARE_TOKEN` is not set, the loader falls back to akshare's
`fund_etf_hist_em` (前复权 / qfq-adjusted) automatically.

## 与 `src/` 包的关系 · Relationship to the `src/` package

The notebook is a flat, self-contained copy.  For production use
prefer the modular package under `src/` — the notebook is kept so
reviewers can read the strategy top-to-bottom in one sitting.
