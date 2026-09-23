# 四级因子动态组合实验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现行为聚类、MACoE、PACoE、融合路由和成本样本外回测的统一四级实验流水线。

**Architecture:** 紧凑日度绩效表作为聚类和路由共同输入；候选池压缩后再读取股票级因子值。模型和回测分层，四级实验仅替换日度因子权重生成器。

**Tech Stack:** Python 3.11、pandas、NumPy、scikit-learn、PyTorch、PyArrow、pytest。

---

### Task 1: 日度行为特征

**Files:** Create `research_pipeline/research_system/behavior.py`; Test `research_pipeline/tests/test_behavior.py`.

- [ ] 写失败测试：验证 IC、Rank IC、斜率及 `label_available_date`。
- [ ] 运行单测并确认因模块缺失而失败。
- [ ] 实现分区级日度绩效和严格滞后 9 维特征。
- [ ] 运行单测。

### Task 2: K-Means 和候选池

**Files:** Create `research_pipeline/research_system/clustering.py`; Test `research_pipeline/tests/test_clustering.py`.

- [ ] 写失败测试：训练期拟合、可复现标签、每簇代表因子。
- [ ] 实现行为矩阵、K-Means 和代表因子选择。
- [ ] 运行单测。

### Task 3: 成本回测

**Files:** Create `research_pipeline/research_system/portfolio.py`; Test `research_pipeline/tests/test_portfolio.py`.

- [ ] 写失败测试：下一日执行、换手成本、停牌冻结和指标。
- [ ] 实现 Alpha 合成、股票权重和成本回测。
- [ ] 运行单测。

### Task 4: MACoE/PACoE/融合模型

**Files:** Create `research_pipeline/research_system/models.py`; Test `research_pipeline/tests/test_models.py`.

- [ ] 写失败测试：张量形状、确定性 Top-k、可学习 alpha 和换手损失。
- [ ] 实现简化注意力、专家网络和融合模块。
- [ ] 运行 CPU 小模型训练测试。

### Task 5: 四级实验运行器与 CLI

**Files:** Create `research_pipeline/research_system/experiments.py`; Modify `research_pipeline/research_system/cli.py`; Test `research_pipeline/tests/test_experiments.py`.

- [ ] 写失败测试：四级共享候选池和测试期边界，输出统一汇总。
- [ ] 实现 `experiment-suite` CLI、配置解析、训练、推理和产物。
- [ ] 运行小型端到端测试。

### Task 6: 真实烟雾运行与验证

- [ ] 对真实快照先运行 20-50 因子的缩小训练。
- [ ] 检查四级指标、模型输出、成本和快照一致性。
- [ ] 运行完整测试、编译检查和快照校验。
- [ ] 更新 `task_plan.md`、`findings.md`、`progress.md` 和 README。
