# Results / 回测结果

Running `python -m src.pipeline` regenerates the CSVs under this
folder.  The pre-computed artifacts shipped here summarise the latest
reference run.

运行 `python -m src.pipeline` 会在该目录重新生成全部 CSV。当前仓库
内的文件是最近一次参考运行的快照。

## 文件一览 · File listing

| 文件 | 说明 |
| --- | --- |
| `best_parameters.csv` | 参数搜索最终选定的参数 (key-value) |
| `metrics_comparison.csv` | 训练期 vs 样本外区间的核心指标对比 |
| `equity_curve_train.csv` | 训练期日频权益曲线 |
| `equity_curve_test.csv` | 样本外日频权益曲线 |
| `top10_scored_targets_test.csv` | 最新样本外 Top-10 打分候选 |
| `trading_log_train.csv` | 训练期交易明细 |
| `trading_log_test.csv` | 样本外交易明细 |
| `local_grid_results.csv` | 参数搜索全网格结果（含选择依据） |
| `next_trade_holdings_YYYYMMDD_to_YYYYMMDD.csv` | 下一交易日目标持仓（日更新） |

## 关键指标 · Headline metrics

| Metric | Training (2009-2019) | OOS (2020-2026) |
| --- | ---: | ---: |
| Annual return | 4.83% | 35.25% |
| Sharpe ratio | 0.5423 | 1.4787 |
| Max drawdown | -10.35% | -12.91% |
| Calmar ratio | 0.47 | 2.73 |
| Win rate | 44.60% | 45.67% |
| Avg holding days | 12.8 | 12.4 |

## 复现 · Reproduction

```bash
export TUSHARE_TOKEN=<your_token>
python -m src.pipeline
```

所有中间结果（CSV/PNG）会写入 `ETF_Result/` 以及本目录；要强制
重新运行，可删除该目录后再调用 pipeline。

Intermediate outputs (CSV/PNG) land in `ETF_Result/` and this folder.
Delete this folder and rerun the pipeline to force a clean regen.
