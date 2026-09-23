# 独立研究数据

本目录只保存从原系统导出的版本化研究快照。研究代码只读取 `snapshots/<snapshot_id>`，不会读取 `custom_backtester` 或 `single_factor`。`current.txt` 只在完整导出和校验成功后更新；旧快照保留不变。

常用流程：

```powershell
$env:PYTHONPATH = "research_pipeline"
python -m research_system export --config research_pipeline/config.local.yaml
python -m research_system validate --data-root research_data
python -m research_system states --data-root research_data --runs-root research_runs --snapshot-id <snapshot_id>
python -m research_system values --data-root research_data --runs-root research_runs --snapshot-id <snapshot_id>
python -m research_system conditional --data-root research_data --values-run <values_run> --state-run <state_run> --runs-root research_runs --snapshot-id <snapshot_id> --horizon 20
python -m research_system select --data-root research_data --conditional-run <conditional_run> --runs-root research_runs --snapshot-id <snapshot_id> --state-id bull --split train --top-n 10
python -m research_system experiment-suite --data-root research_data --values-run <values_run> --state-run <state_run> --output-root research_runs --snapshot-id <snapshot_id> --max-factors 50 --n-clusters 10 --factor-top-k 5 --top-n 20 --test-start <test_start>
```

快照包含行情、股票池、因子目录、生成阶段指标、回测汇总和 SHA-256 清单。当前真实快照包含 500 只股票、469,982 行行情和 1,264 个 accepted 因子。

`values` 根据快照中的行情字段和因子表达式逐因子计算值，结果保存在独立运行目录：

```text
research_runs/<values_run>/
  factor_values/
    factor_id=<factor_id>/values.parquet
```

每个值分区包含 `date`、`code`、`factor_id`、`value`。系统不会把缺失值伪造成零；表达式无法计算的因子会记录失败原因。

`states` 从快照行情生成规则市场状态，结果保存在 `market_states.parquet`。`conditional` 使用未来收益标签，按状态和全局交易日顺序输出 `train`、`valid`、`test` 指标，默认比例为 60%/20%/20%，可用 `--train-ratio` 和 `--valid-ratio` 覆盖。

`select` 默认只使用训练段，先选状态下得分最高的类别，再选择具体因子并生成等权组合，同时写入 `selection.json` 和审计 manifest。当前选择基线不自动读取全部因子值计算相关性；四级动态实验通过下方的 `experiment-suite` 独立运行。

`experiment-suite` 是四级研究实验入口。它先在训练期行为特征上执行 K-Means 并压缩候选因子，再依次运行 E1 基准、E2 MACoE、E3 PACoE 和 E4 完整融合。所有级别共享代表因子池、测试起点和成本参数；E4 的 `--factor-top-k` 控制训练及推理阶段保留的因子数。结果目录包含日度 IC、行为特征、簇标签、代表因子、因子权重、测试期 Alpha、每日净值和指标 JSON。


**原始数据快照**

位置：

[research_data](F:/my_code_file/因子构建/生成因子＋回测系统/research_data)

当前快照：

[20260831T074757Z_7a98fc5698](F:/my_code_file/因子构建/生成因子＋回测系统/research_data/snapshots/20260831T074757Z_7a98fc5698)

其中包括：

| 文件 | 内容 |
|---|---|
| `market.parquet` | 500 只股票、469,982 行行情数据 |
| `universe.csv` | 股票池的500只股票代码 |
| `factor_catalog.parquet` | 1,264 个因子及表达式 |
| `factor_metrics.parquet` | 因子生成阶段的 IC、Rank IC、ICIR 等 |
| `backtest_metrics.parquet` | 316 条历史回测结果 |
| `manifest.json` | 快照编号、字段、行数、哈希校验 |
| `source_metadata.json` | 原始数据来源记录 |

**衍生研究数据**

位置：

[research_runs](F:/my_code_file/因子构建/生成因子＋回测系统/research_runs)

主要包括：

- 1,264 个逐因子值：`values_20260831T074840Z_ff40c015`
- 市场状态：`state_20260831T081146Z_043b23e6`
- 条件 IC 评价：`conditional_20260831T083739Z_4c33fe73`
- 四级实验结果：`experiments_20260902T102339Z_ccebe07c`

所以目前的数据关系是：

```text
原网页系统
   ↓ 只负责导出
research_data/snapshots/   原始、固定、只读快照
   ↓ 研究计算
research_runs/             因子值、市场状态、评价和实验结果
```

当前独立快照已经校验通过，`valid=true`。后续实验只需要保留 `research_data`、`research_runs` 和 `research_pipeline`，不需要依赖原网页系统运行。
