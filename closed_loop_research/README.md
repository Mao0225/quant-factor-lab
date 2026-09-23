# 独立研究与选股系统 v1

当前统一设计为 `research_design/2026-09-21-system-design-v1.md`。运行 `python -m closed_loop_research.app --port 8767`，打开 **http://127.0.0.1:8767**。

完整操作手册：[Markdown版](docs/完整操作手册_v1.md) · [离线浏览与打印版](docs/完整操作手册_v1.html)。涵盖快速选股、六个页面、研究配置和运行、模型管理、方案与历史、故障处理及备份恢复。

研究工作区已增加按用途浏览的回测、运行过程图表和中文验证报告，操作路径见[研究可视化使用说明](docs/研究可视化使用说明.md)。内部编号与原始 JSON 默认折叠在高级证据中。

2026-09-21 新增实跑：[十二因子组合探索完整报告](docs/十二因子组合探索_v1.md)。包含三因子/十二因子固定基准和随机/PPO×两个种子，共六组；真实冻结数量为3、12、11、10、10、10。页面已用中文解释方法、种子和协议，并区分初始池、逐批组合与冻结权重。报告保留负收益、相同组合及严格评分核验失败，不将公式数量或PPO更新次数当作效果提升。

已实现研究/选股两个工作区、六页、异步任务、冻结模型交接、人工开放、条件选股、方案修订、历史和导出。原始文件流式导入500股601,000行和50个所需源字段，完整441字段目录保留；24个价量信号字段进入原型协议，财务隔离。最新实际日2026-06-16；该日换手率疑似零值占位，相关过滤禁用。

详见 `docs/v1_runbook.md`、`docs/v1_implementation_plan.md`、`docs/v1_source_audit.md`、`docs/v1_acceptance.md`。初次验收后，按用户明确授权开放“500股价量组合 · 原型一号”（E组种子7），已生成默认Top 50结果；其余8个版本保留候选状态。开放记录见 `workspace/system_v1/model_release_v1.json`。以下保留早期内核与多年原型的历史运行说明，其菜单/功能范围由v1设计取代。

## 早期独立闭环研究内核

沿用旧系统的 **500 股数据**，独立实现 v0.4 的研究内核。旧 `single_factor/`、`custom_backtester/`、`research_pipeline/` 保留不改。所有新协议、数据副本、实验和研究页面都在本目录内。

已具备：不可变协议和快照、F/E/V/T 访问分离、因果表达式与覆盖检查、Top K 现金/股数账本、有限预算组合搜索、配对交易增量奖励、完整表达式 masked PPO、批次检查点恢复、V 选择与冻结、独立 T 执行，以及真实记录生成的只读研究工作区。企业使用端不在本版范围内。

本次已完成的演示位于 `workspace/runs/legacy500_first_edition/`，可直接打开其中的 `report.html`；验收证据为 `acceptance.json`。真实500股运行完成3批、12候选、3次PPO更新及一次恢复，最终保留原组合；33项测试通过。界面是只读查看器，训练操作使用下面的命令。

多年升级已完成9个实跑对照：288候选、12次PPO更新、8次组合提交；45项测试通过。最新报告为 `workspace/suites/history500_round1/report.html`。这轮PPO和随机搜索冻结了相同组合，2026历史比较平均净收益均为−0.27%，固定初始因子为+2.82%；目前没有PPO胜出的证据。

## 多年版本

`workspace/history500/market.parquet` 保留源文件全部 **601,000 行、500 股、1,202 个交易日**，时间为2021-06-18至2026-06-16。2021年用于预热；F=2022–2023（484日），E=2024（242日），V=2025（243日），T=2026截至6月16日（99日）。2026年数据此前已查看，结果明确标为历史比较。

表达式空间扩展至24个原始/派生价量字段，窗口1/5/10/20/60，最多15 tokens、5个活跃因子。总历史依赖≤120日，包含派生字段本身依赖。初始组合是20日收益率、负5日收益率、负20日波动率，权重0.4/0.3/0.3。

实测完整F回测约1.3秒、E约0.7秒，记录见 `workspace/benchmark_history500/benchmark.json`。本轮预登记 A/B/E × seeds 7/19/43，生成组4批×12候选、每侧Q16，V只选第2/4批；A只搜索一批。C/D接口和合成验证保留，本轮真实多年实验尚未覆盖它们。

```powershell
python -m closed_loop_research import-history --destination closed_loop_research/workspace/new_history500
python -m closed_loop_research benchmark --data closed_loop_research/workspace/history500 --output closed_loop_research/workspace/new_benchmark
python -m closed_loop_research suite --data closed_loop_research/workspace/history500 --protocol closed_loop_research/workspace/history500/research_protocol.json --output closed_loop_research/workspace/suites/my_multiyear_run --groups A B E --seeds 7 19 43 --workers 3 --final-test
python -m closed_loop_research suite-report --suite closed_loop_research/workspace/suites/history500_round1
python -m closed_loop_research.scripts.serve_suite --suite closed_loop_research/workspace/suites/history500_round1 --port 8766
```

`--workers` 使用独立进程，串行与并行同种子结果已验证一致。全部训练结束后才进行V选择，全部模型冻结后才统一执行T。报告保留每个种子、区间收益与回撤、池变化、正负奖励和真实算力。逐笔账本保存为`.json.gz`，压缩不删除证据。

第一版源代码归档在 `versions/first_edition/closed_loop_research/`。如需读取或继续旧身份的实验，命令前缀使用 `python -m closed_loop_research.versions.first_edition.closed_loop_research`。新版本不会以旧代码身份续训。第一版数据、实验和报告均保留。

本次多年实跑的源码归档在 `versions/multiyear_round1/closed_loop_research/`，其SHA256与suite_manifest一致。后续对照重入修复和分年报告改进不重写实跑结果；当前内核重跑应使用新的输出目录。单项旧实跑的读取/报告/冻结评价命令可使用归档包前缀 `python -m closed_loop_research.versions.multiyear_round1.closed_loop_research`。

## 直接使用已导入的数据（短周期调试示例）

从工作区根目录执行（Python 3.11，依赖见 `requirements.txt`）：

```powershell
# 训练；第一批后暂停在安全检查点
python -m closed_loop_research train --data closed_loop_research/workspace/prototype500 --run closed_loop_research/workspace/runs/my_run --batches-this-call 1

# 恢复同一协议、数据、代码与随机状态
python -m closed_loop_research resume --run closed_loop_research/workspace/runs/my_run

# 生成并查看真实研究记录；这里不执行 V 或 T
python -m closed_loop_research report --run closed_loop_research/workspace/runs/my_run
python -m closed_loop_research serve --run closed_loop_research/workspace/runs/my_run --port 8765

# 开发结束后，V 选择预登记快照并冻结已有 F 权重
python -m closed_loop_research select --run closed_loop_research/workspace/runs/my_run

# 单独执行最终测试；重复命令返回同一结果
python -m closed_loop_research test --run closed_loop_research/workspace/runs/my_run
python -m closed_loop_research report --run closed_loop_research/workspace/runs/my_run
```

研究页地址为 `http://127.0.0.1:8765/report.html`，也可以直接打开运行目录内 `report.html`。页签包含研究概览、协议与数据、迭代记录、当前组合与选股、验证报告。页面只展示持久化结果，不会重新训练或读取 T 行情。`serve` 只监听本机且只提供报告，不暴露检查点或任意目录。

## 500 股数据来源

实际采用 `single_factor/data/selected_500_liquid_processed/panel.parquet`，源文件 SHA256 写在 `workspace/prototype500/import_report.json`。复制最近 142 个交易日共 71,000 行，500 个代码全部保留；其中 22 日预热、120 日顺序分割。

| 区间 | 时间 | 用途 |
|---|---|---|
| F | 2025-12-03 至 2026-02-10 | 组合权重与子集搜索 |
| E | 2026-02-11 至 2026-04-15 | 候选奖励与池提交 |
| V | 2026-04-16 至 2026-05-18 | 预登记检查点选择 |
| T | 2026-05-19 至 2026-06-16 | 冻结后独立执行 |

原 `research_data` 的说明写 500 股，但其中 `market.parquet` 实际只有 391 个代码，因此没有采用它作为本次 500 股原型输入。

重新导入另一时间长度时使用新目录：

```powershell
python -m closed_loop_research import-legacy --source single_factor/data/selected_500_liquid_processed/panel.parquet --destination closed_loop_research/workspace/another_dataset --sessions 120
```

这是 `legacy_prototype` 数据模式：沿用旧价格与固定 500 股样本；假设没有额外分红拆股，开盘成交使用已登记的日线近似。股票池历史偏差、原始预处理/复权时点和涨跌停成交尚未完成正式核验。界面和结果均标注原型，不阻碍运行，也不把这些数据假设伪装成已审计事实。`audited` 模式仍要求字段来源与可用时间核验、显式公司行动和交易标记。

## 对照、消融和预算

```powershell
# 同一表达式空间、组合搜索器和执行规则；保存每个种子
python -m closed_loop_research suite --data closed_loop_research/workspace/prototype500 --output closed_loop_research/workspace/suites/main --groups A B C D E --seeds 7 19

# 全部方法和种子冻结后，再整体开启 T
python -m closed_loop_research suite --data closed_loop_research/workspace/prototype500 --output closed_loop_research/workspace/suites/main --groups A B C D E --seeds 7 19 --final-test

# 派生协议，不修改运行中实验
python -m closed_loop_research derive-protocol --source closed_loop_research/workspace/prototype500/protocol.json --output closed_loop_research/workspace/beta0.json --beta 0
```

A 固定简单因子；B 随机合法表达式；C PPO 单因子有符号 IC；D PPO 组合 IC 增量；E PPO 配对净交易增量。C/D/E 只切换生成奖励，下游搜索和池提交保持一致。A 只运行一批搜索，披露实际预算，不重复评价凑数量。

`comparison.json` 报告全部种子、均值/总体标准差、失败率、逻辑调用、实际回测和时间，不进行未验证的显著性结论。`--search-mode fixed`、`--beta 0`、`--reward absolute_trade`、`--wall-seconds` 可派生补充协议。派生协议的字段/时间划分不变时可共用数据快照；启动使用含派生 `protocol.json` 与该 `snapshot/` 的独立数据目录。

默认调试预算为 3 批 × 4 个完整表达式，单侧 Q=8、活跃因子上限 3、Top 50。Q 计目标接口调用；缓存命中计逻辑预算，不计实际回测；全零提案不占目标调用预算。每批开始前预留最坏预算，预算不足时安全停止，不增加伪造的 PPO 更新次数。墙钟预算在批次边界检查，可能超出最多一个批次。

## 文件与证据

| 文件/目录 | 内容 |
|---|---|
| `protocol.json`、`experiment.json` | 锁定协议、快照/源代码标识、依赖版本 |
| `batches/*-evaluated.json` | 表达式轨迹、质量、F 搜索、两侧 E 结果、奖励 |
| `batches/*-ppo.json` | 参数前后指纹、参数变化、loss、负奖励数量 |
| `batches/*-committed.json` | incumbent 比较、池提交/拒绝和下一池版本 |
| `backtests/*.json` | 净值、现金、成交、订单、持仓、选股与公司行动 |
| `checkpoint.json`、`checkpoints/*.pt` | 联合模型/价值/优化器/RNG/预算/池/阶段状态 |
| `pools/*.json` | 每批实际组合与预登记选择标记 |
| `selection.json`、`frozen_model.json` | 仅 V 选择、原 F 权重冻结 |
| `test_result.json`、`test_backtests/` | 独立 T 权限与结果；训练阶段不存在 |
| `report.html` | 自包含只读研究工作区 |

恢复只加载本机可信检查点；协议、快照或代码标识变化会拒绝续训，须派生新实验。数据隔离是应用层访问边界和物理分区，不声称能防止具有文件系统权限的人恶意绕过。

## 验证

```powershell
python -m pytest closed_loop_research/tests -q
```

测试包含手算账本、缺失值/资格规则、未来扰动、T 拒绝读取、同预算搜索、合法负奖励、无效候选、真实 PPO 参数更新、三个事务阶段恢复一致，以及 5 组 × 2 种子的合成机制对照。合成验收只证明机制；小预算 500 股运行也不能证明研究方法提高了样本外收益。

设计决策见 `docs/implementation_plan.md`，公式见 `docs/methods.md`，运行验收见 `docs/progress.md`。
