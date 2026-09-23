# 因子构建与回测系统

这是一个以日频股票数据为基础的本地研究项目，包含因子生成、表达式回测、研究数据导出，以及独立的闭环研究与选股界面。各子系统可以分别使用；仓库中的配置和文档保留了它们之间的数据衔接方式。

## 目录

| 目录 | 用途 |
| --- | --- |
| [`custom_backtester/`](custom_backtester/README.md) | 从日频 CSV 建立缓存，运行因子生成、表达式回测和 Streamlit 工作台 |
| [`single_factor/`](single_factor/README.md) | 预处理行情数据，使用 PPO 搜索并评估单因子表达式 |
| [`research_pipeline/`](research_pipeline/) | 导出研究快照，计算因子值、市场状态和条件表现 |
| [`closed_loop_research/`](closed_loop_research/README.md) | 独立的研究、回测、模型选择与选股系统，提供本地 Web 界面 |
| [`research_design/`](research_design/2026-09-21-system-design-v1.md) | 系统设计与研究方案 |

## 快速开始：表达式回测

建议使用 Python 3.11。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r custom_backtester/requirements.txt
cd custom_backtester
```

准备符合项目字段约定的日频 CSV，然后建立本地缓存：

```powershell
python -m custom_bt.cli prepare --csv "C:\path\to\v_stock_daily_full.csv" --out data_cache/stock_daily
python -m custom_bt.cli fields --data data_cache/stock_daily
python -m custom_bt.cli operators
```

编辑 [`custom_backtester/configs/default.yaml`](custom_backtester/configs/default.yaml) 中的表达式和回测参数，运行：

```powershell
python -m custom_bt.cli backtest --data data_cache/stock_daily --alpha-config configs/default.yaml --run-name demo
```

结果写入 `custom_backtester/outputs/demo/`。也可以启动网页工作台：

```powershell
python -m streamlit run app/streamlit_app.py
```

CSV 字段说明见 [`v_stock_daily_full_字段说明.md`](v_stock_daily_full_字段说明.md)。股票池、PPO 因子生成及批量因子回测的命令见 [`custom_backtester/README.md`](custom_backtester/README.md)。

## 其他入口

- 独立研究与选股界面：安装 `closed_loop_research/requirements.txt` 后，从仓库根目录运行 `python -m closed_loop_research.app --port 8767`，访问 `http://127.0.0.1:8767`。操作说明见 [`closed_loop_research/README.md`](closed_loop_research/README.md)。实际研究仍需导入本地数据。
- 单因子生成：安装 `single_factor/requirements.txt`，按 [`single_factor/README.md`](single_factor/README.md) 准备配置与数据，然后运行 `python -m single_factor.cli --help` 查看命令。
- 研究快照流程：安装 `research_pipeline/requirements.txt`，使用 [`research_pipeline/config.example.yaml`](research_pipeline/config.example.yaml) 作为本地配置参考。流程见 [`research_data/README.md`](research_data/README.md)。

## 数据与上传说明

按根目录 [`.gitignore`](.gitignore) 提交时，原始行情、研究快照、模型权重、缓存、运行结果及 `.env` 等本地配置不会上传。克隆后需要自行提供有使用权限的数据，并按各模块说明重新生成缓存。上传前可运行 `git status --short`，确认待提交文件。

本项目用于量化研究和历史回测，历史结果不代表未来收益。
