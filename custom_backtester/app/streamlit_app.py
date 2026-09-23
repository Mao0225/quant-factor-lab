from __future__ import annotations

import hashlib
import subprocess
import sys
import json
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
FIELD_DOC_PATH = next(iter(WORKSPACE_ROOT.glob("v_stock_daily_full_*.md")), WORKSPACE_ROOT / "v_stock_daily_full_字段说明.md")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit("请先安装 streamlit：pip install streamlit") from exc

from custom_bt.data import list_store_fields, load_meta, load_store_stock_list, stock_list_path
from custom_bt.docs import enrich_fields, enrich_operators
from custom_bt.jobs import create_backtest_job, load_job_status, update_job_status
from custom_bt.platform_jobs import create_platform_job
from custom_bt.results import list_runs
from custom_bt.expressions import list_operators


SUMMARY_LABELS = {
    "total_return": "总收益",
    "annual_return": "年化收益",
    "sharpe": "夏普比率",
    "max_drawdown": "最大回撤",
    "calmar": "Calmar",
    "win_rate": "胜率",
    "average_turnover": "平均换手",
    "total_cost": "总成本",
    "annual_cost": "年化成本",
    "number_of_trades": "交易次数",
    "average_holding_count": "平均持仓数",
}


SUMMARY_RATE_KEYS = {
    "total_return",
    "annual_return",
    "max_drawdown",
    "win_rate",
    "average_turnover",
    "total_cost",
    "annual_cost",
}

SAVED_RATE_COLUMNS = ["换手率", "最大回撤", "年化收益", "总收益"]
ANNUAL_RATE_COLUMNS = ["收益", "最大回撤", "换手", "成本", "胜率"]


ANNUAL_LABELS = {
    "year": "年份",
    "return": "收益",
    "sharpe": "夏普",
    "max_drawdown": "最大回撤",
    "turnover": "换手",
    "cost": "成本",
    "win_rate": "胜率",
}


STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "finished": "已完成",
    "failed": "失败",
    "missing": "状态缺失",
}


def _parse_multiline_values(value: str) -> list[str]:
    values = []
    seen = set()
    for raw in str(value).replace(",", "\n").splitlines():
        item = raw.strip()
        if item and item not in seen:
            values.append(item)
            seen.add(item)
    return values


def _parse_optional_float(value: str) -> float | None:
    text = str(value).strip()
    return None if not text else float(text)


def _parse_int_values(value: str) -> list[int]:
    values = []
    seen = set()
    for item in _parse_multiline_values(value):
        number = int(item)
        if number not in seen:
            values.append(number)
            seen.add(number)
    return values


def _resolve_app_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def _master_store_ready(store_dir: str | Path) -> bool:
    path = Path(store_dir)
    return (path / "meta.json").is_file() and (path / "stocks").is_dir()


def _latest_active_job_dir(jobs_root: str | Path) -> Path | None:
    root = Path(jobs_root)
    if not root.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for status_path in root.glob("*/status.json"):
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status.get("status") not in {"queued", "running"}:
            continue
        candidates.append((status_path.parent.stat().st_mtime, status_path.parent))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _visible_job_dir(jobs_root: str | Path) -> Path | None:
    current = st.session_state.get("current_job_dir")
    if current:
        path = Path(str(current))
        if (path / "status.json").exists():
            return path
    return _latest_active_job_dir(jobs_root)


def _factor_generation_run_dir(job_dir: str | Path) -> Path | None:
    path = Path(job_dir)
    config_path = path / "platform_job.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if config.get("operation") != "generate_factors":
        return None
    payload = config.get("payload") or {}
    pool_id = str(payload.get("pool_id") or "").strip()
    factor_runs_root = payload.get("factor_runs_root")
    if not pool_id or not factor_runs_root:
        return None
    runtime_key = {
        "pool_id": pool_id,
        "fields": list(payload.get("fields") or []),
        "splits": {
            name: {
                "cache_start": str(value.get("cache_start", "")),
                "cache_end": str(value.get("cache_end", "")),
            }
            for name, value in sorted((payload.get("splits") or {}).items())
        },
        "max_backtrack_days": int(payload.get("max_backtrack_days", 100)),
        "target_horizon": int(payload.get("target_horizon", 20)),
        "max_future_days": int(payload.get("max_future_days", 20)),
    }
    runtime_id = hashlib.sha256(json.dumps(runtime_key, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    generation_config = payload.get("generation_config") or {}
    run_id = str(generation_config.get("run_id") or f"{pool_id}_{runtime_id}")
    return Path(factor_runs_root).expanduser().resolve() / run_id


def _load_factor_generation_progress(job_dir: str | Path) -> dict[str, object]:
    run_dir = _factor_generation_run_dir(job_dir)
    if run_dir is None:
        return {}
    state_path = run_dir / "run_state.json"
    if not state_path.exists():
        return {"factor_run_dir": str(run_dir)}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"factor_run_dir": str(run_dir)}
    state["factor_run_dir"] = str(run_dir)
    return state


def _load_yaml_defaults(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _default_source_path() -> Path:
    return PROJECT_ROOT.parent.parent / "数据" / "daily_with_maindata_v2.csv"


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def _load_pool_manifests(pools_root: str | Path) -> pd.DataFrame:
    rows = []
    root = Path(pools_root)
    if not root.exists():
        return pd.DataFrame(columns=["pool_id", "name", "n_stocks", "selection_start", "selection_end"])
    for path in sorted(root.glob("*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(data)
    if not rows:
        return pd.DataFrame(columns=["pool_id", "name", "n_stocks", "selection_start", "selection_end"])
    return pd.DataFrame(rows).sort_values(["name", "pool_id"], na_position="last").reset_index(drop=True)


def _load_factor_run_manifests(factor_runs_root: str | Path) -> pd.DataFrame:
    rows = []
    root = Path(factor_runs_root)
    if not root.exists():
        return pd.DataFrame(columns=["run_id", "pool_id", "accepted_count", "created_at"])
    for path in sorted(root.glob("*/factor_run.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data.setdefault("run_id", path.parent.name)
        rows.append(data)
    if not rows:
        return pd.DataFrame(columns=["run_id", "pool_id", "accepted_count", "created_at"])
    return pd.DataFrame(rows).sort_values("run_id", ascending=False).reset_index(drop=True)


def _load_accepted_factor_table(factor_run_dir: str | Path) -> pd.DataFrame:
    path = Path(factor_run_dir) / "accepted_factors.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A background worker may still be appending the last record.
                continue
            if isinstance(row, dict):
                rows.append(row)
    return pd.DataFrame(rows)


def _load_factor_backtest_summary(path: str | Path) -> pd.DataFrame:
    summary_path = Path(path) / "factor_backtest_summary.csv"
    if not summary_path.exists():
        return pd.DataFrame()
    return pd.read_csv(summary_path)


def _list_factor_backtest_result_dirs(results_root: str | Path) -> list[Path]:
    root = Path(results_root)
    factor_root = root / "factor" if (root / "factor").exists() else root
    if not factor_root.exists():
        return []
    paths = [path.parent for path in factor_root.rglob("factor_backtest_summary.csv") if path.is_file()]
    return sorted(set(paths), key=lambda path: path.stat().st_mtime, reverse=True)


def _format_summary_value(key: str, value: object) -> object:
    if _is_missing(value):
        return "-"
    if key in SUMMARY_RATE_KEYS:
        return f"{float(value) * 100:.2f}%"
    if isinstance(value, (int, float)):
        return f"{float(value):.4f}"
    return value


def _summary_frame(summary: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [{"指标": SUMMARY_LABELS.get(key, key), "值": _format_summary_value(key, value)} for key, value in summary.items()]
    )


def _summary_cards(summary: dict) -> list[dict[str, object]]:
    return [
        {"label": SUMMARY_LABELS.get(key, key), "value": _format_summary_value(key, value)}
        for key, value in summary.items()
    ]


def _render_summary_cards(summary: dict) -> None:
    cards = _summary_cards(summary)
    if not cards:
        return
    cols_per_row = 4
    for start in range(0, len(cards), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, card in zip(cols, cards[start:start + cols_per_row]):
            col.metric(card["label"], card["value"])


def _annual_frame(annual: pd.DataFrame) -> pd.DataFrame:
    if annual.empty:
        return annual
    frame = annual.rename(columns=ANNUAL_LABELS).copy()
    for col in ANNUAL_RATE_COLUMNS:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce") * 100.0
    return frame


def _alpha_expr_from_run(run: dict) -> str:
    canonical_expression = str(run.get("canonical_expression", "")).strip()
    if canonical_expression:
        return canonical_expression
    alphas = run.get("config", {}).get("alphas", [])
    exprs = [str(item.get("expr", "")).strip() for item in alphas if item.get("expr")]
    return " + ".join(exprs) if exprs else "-"


def _note_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "note.md"


def _load_note(run_dir: str | Path) -> str:
    path = _note_path(run_dir)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _save_note(run_dir: str | Path, note: str) -> None:
    _note_path(run_dir).write_text(note, encoding="utf-8")


def _note_preview(note: str, limit: int = 80) -> str:
    text = " ".join(note.split())
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit - 1] + "..."


def _display_text(value: object) -> str:
    if _is_missing(value):
        return ""
    return str(value)


def _saved_runs_table(runs: list[dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        summary = run.get("summary", {}) or {}
        config = run.get("config", {}) or {}
        # Existing factor manifests store settings flat, manual/composite nest them.
        backtest = config.get("backtest", config) or {}
        generation = run.get("generation_metrics", {}) or {}
        preprocess = run.get("factor_preprocess", {}) or {}
        preprocess_method = preprocess.get("method", "") if isinstance(preprocess, dict) else str(preprocess)
        composition_metrics = run.get("composition_metrics", {}) or {}
        if not generation:
            generation_prefix = "generation_"
            generation = {
                key[len(generation_prefix):]: value
                for key, value in run.items()
                if key.startswith(generation_prefix)
            }
        rows.append(
            {
                "canonical_expression": _alpha_expr_from_run(run),
                "result_type": _display_text(run.get("result_type")),
                "pool_id": _display_text(run.get("pool_id")),
                "factor_run_id": _display_text(run.get("factor_run_id")),
                "composition_id": _display_text(run.get("composition_id")),
                "组合规模": _display_text(run.get("max_factors")),
                "选择指标": _display_text(run.get("selection_metric")),
                "mutual IC 阈值": _display_text(run.get("mutual_ic_threshold")),
                "权重方法": _display_text(run.get("weight_method")),
                "因子预处理": _display_text(preprocess_method),
                "组合 IC": composition_metrics.get("ic"),
                "组合 Rank IC": composition_metrics.get("rank_ic"),
                "组合 ICIR": composition_metrics.get("icir"),
                "组合 Rank ICIR": composition_metrics.get("rank_icir"),
                "PPO IC": generation.get("ic"),
                "PPO Rank IC": generation.get("rank_ic"),
                "PPO ICIR": generation.get("icir"),
                "PPO Coverage": generation.get("coverage"),
                "PPO Score": generation.get("score"),
                "运行名称": _display_text(run.get("run_name")),
                "表达式": _alpha_expr_from_run(run),
                "夏普比": summary.get("sharpe"),
                "换手率": None if _is_missing(summary.get("average_turnover")) else float(summary.get("average_turnover")) * 100.0,
                "最大回撤": None if _is_missing(summary.get("max_drawdown")) else float(summary.get("max_drawdown")) * 100.0,
                "年化收益": None if _is_missing(summary.get("annual_return")) else float(summary.get("annual_return")) * 100.0,
                "总收益": None if _is_missing(summary.get("total_return")) else float(summary.get("total_return")) * 100.0,
                "开始日期": _display_text(backtest.get("start_date")),
                "结束日期": _display_text(backtest.get("end_date")),
                "TopK": _display_text(backtest.get("top_k")),
                "备注": _note_preview(_load_note(run.get("path", ""))),
                "创建时间": _display_text(run.get("created_at")),
                "_path": _display_text(run.get("path")),
            }
        )
    return pd.DataFrame(rows)


def _download_button(path: Path, label: str, scope: str) -> None:
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, key=f"download:{scope}:{path.name}")


def _request_rerun() -> None:
    rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun is None:
        st.warning("当前 Streamlit 版本不支持自动刷新，请手动刷新页面查看任务状态。")
        return
    rerun()


def _format_fields(fields: list[dict[str, str]]) -> pd.DataFrame:
    frame = pd.DataFrame(enrich_fields(fields, FIELD_DOC_PATH))
    if frame.empty:
        return frame
    return frame.rename(
        columns={"name": "字段名", "dtype": "类型", "source": "来源", "description": "解释"}
    )


def _format_operators() -> pd.DataFrame:
    frame = pd.DataFrame(enrich_operators(list_operators()))
    if frame.empty:
        return frame
    return frame.rename(
        columns={
            "name": "操作符",
            "category": "分类",
            "category_cn": "分类名称",
            "description_cn": "解释",
            "example": "示例",
        }
    )


@st.cache_data(show_spinner=False)
def _load_stock_table_cached(store_dir: str, marker: float) -> pd.DataFrame:
    _ = marker
    stocks = load_store_stock_list(store_dir)
    if not stocks:
        return pd.DataFrame()
    return pd.DataFrame(stocks).rename(
        columns={
            "code": "股票代码",
            "rows": "数据行数",
            "start_date": "开始日期",
            "end_date": "结束日期",
            "latest_date": "最近日期",
            "latest_open": "最近开盘价",
            "latest_close": "最近收盘价",
            "latest_volume": "最近成交量",
            "latest_amount": "最近成交额",
        }
    )


def _start_background_job(job_dir: Path) -> None:
    log_path = job_dir / "job.log"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "custom_bt.cli", "run-job", "--job-dir", str(job_dir)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )
    update_job_status(job_dir, "queued", "后台进程已启动，等待进入计算阶段", {"pid": process.pid, "log_path": str(log_path.resolve())})


def _start_platform_background_job(job_dir: Path) -> None:
    log_path = job_dir / "job.log"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "custom_bt.cli", "run-platform-job", "--job-dir", str(job_dir)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )
    update_job_status(
        job_dir,
        "queued",
        "平台任务已提交到后台，等待执行",
        {"pid": process.pid, "log_path": str(log_path.resolve())},
    )


def _render_result_dir(run_dir: Path, scope: str) -> None:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    daily_path = run_dir / "daily_report.csv"
    annual_path = run_dir / "annual_metrics.csv"
    from app.workbench_state import read_json
    identity = read_json(manifest_path)
    config = identity.get('config', {}) or {}
    settings = config.get('backtest', config) or {}
    st.subheader(identity.get('run_name') or run_dir.name)
    st.caption('来源：{}　｜　股票池：{}　｜　{} 至 {}　｜　TopK：{}'.format(
        {'manual': '表达式回测', 'factor': '生成因子', 'composite': '因子组合'}.get(identity.get('result_type'), '历史结果'),
        identity.get('pool_id') or '全量数据', settings.get('start_date', '—'), settings.get('end_date', '—'), settings.get('top_k', '—')))
    if summary_path.exists():
        st.subheader("汇总指标")
        _render_summary_cards(json.loads(summary_path.read_text(encoding="utf-8")))
    if daily_path.exists():
        daily = pd.read_csv(daily_path)
        daily["date"] = pd.to_datetime(daily["date"])
        daily["净值"] = daily["account"] / daily["account"].iloc[0]
        daily["PNL"] = daily["净值"] - 1.0
        daily["回撤"] = daily["drawdown"]
        st.subheader("PNL / 回撤曲线")
        st.line_chart(daily.set_index("date")[["PNL", "回撤"]])
    if annual_path.exists():
        st.subheader("年度指标")
        st.dataframe(
            _annual_frame(pd.read_csv(annual_path)),
            use_container_width=True,
            column_config={
                "收益": st.column_config.NumberColumn(format="%.2f%%"),
                "最大回撤": st.column_config.NumberColumn(format="%.2f%%"),
                "换手": st.column_config.NumberColumn(format="%.2f%%"),
                "成本": st.column_config.NumberColumn(format="%.2f%%"),
                "胜率": st.column_config.NumberColumn(format="%.2f%%"),
                "夏普": st.column_config.NumberColumn(format="%.4f"),
            },
        )
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if manifest.get("canonical_expression"):
        st.subheader("表达式")
        st.code(manifest["canonical_expression"], language="text")
    weights_path = run_dir / "factor_weights.json"
    if weights_path.exists():
        try:
            weights = json.loads(weights_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            weights = []
        if weights:
            st.subheader("组合因子权重")
            st.dataframe(pd.DataFrame(weights), use_container_width=True, hide_index=True, key=f"weights:{scope}")
    st.subheader("备注")
    note = st.text_area("备注内容", _load_note(run_dir), height=120, key=f"run-note:{scope}")
    if st.button("保存备注", key=f"save-note:{scope}"):
        _save_note(run_dir, note)
        st.success("备注已保存")
    with st.expander("完整参数与元数据", expanded=False):
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            generation = manifest.get("generation_metrics", {}) or {}
            optimization = manifest.get("optimization", {}) or {}
            preprocess = manifest.get("factor_preprocess", {}) or {}
            preprocess_method = preprocess.get("method", "-") if isinstance(preprocess, dict) else (preprocess or "-")
            weight_method = manifest.get("weight_method") or optimization.get("method") or "-"
            composition_metrics = manifest.get("composition_metrics", {}) or {}
            st.subheader("结果元数据")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"字段": "结果类型", "值": manifest.get("result_type", "-")},
                        {"字段": "规范表达式", "值": manifest.get("canonical_expression", "-")},
                        {"字段": "股票池", "值": manifest.get("pool_id", "-")},
                        {"字段": "因子运行", "值": manifest.get("factor_run_id", "-")},
                        {"字段": "组合 ID", "值": manifest.get("composition_id", "-")},
                        {"字段": "来源因子运行", "值": ",".join(str(item) for item in manifest.get("source_factor_run_ids", []) or [])},
                        {"字段": "组合规模", "值": manifest.get("max_factors", "-")},
                        {"字段": "选择指标", "值": manifest.get("selection_metric", "-")},
                        {"字段": "mutual IC 阈值", "值": manifest.get("mutual_ic_threshold", "-")},
                        {"字段": "权重方法", "值": weight_method},
                        {"字段": "因子预处理", "值": preprocess_method},
                        {"字段": "Target Horizon", "值": manifest.get("target_horizon", "-")},
                        {"字段": "组合 IC", "值": composition_metrics.get("ic")},
                        {"字段": "组合 Rank IC", "值": composition_metrics.get("rank_ic")},
                        {"字段": "组合 ICIR", "值": composition_metrics.get("icir")},
                        {"字段": "组合 Rank ICIR", "值": composition_metrics.get("rank_icir")},
                        {"字段": "PPO IC", "值": generation.get("ic")},
                        {"字段": "PPO Rank IC", "值": generation.get("rank_ic")},
                        {"字段": "PPO ICIR", "值": generation.get("icir")},
                        {"字段": "PPO Coverage", "值": generation.get("coverage")},
                        {"字段": "PPO Score", "值": generation.get("score")},
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.json(manifest, expanded=False)
    files = [
        ("daily_report.csv", "下载每日报告"),
        ("annual_metrics.csv", "下载年度指标"),
        ("trades.csv", "下载交易明细"),
        ("positions.csv", "下载持仓明细"),
        ("summary.png", "下载汇总图片"),
    ]
    for name, label in files:
        _download_button(run_dir / name, label, scope)


def _render_job_status(job_dir: Path, scope: str) -> None:
    status = load_job_status(job_dir)
    status_name = status.get("status", "missing")
    st.subheader("后台任务状态")
    c1, c2, c3 = st.columns(3)
    c1.metric("状态", STATUS_LABELS.get(status_name, status_name))
    c2.metric("运行名称", status.get("run_name", "-"))
    c3.metric("进程 PID", status.get("pid", "-"))
    st.write(status.get("message", ""))
    progress = status.get("progress") or {}
    if progress:
        if any(key in progress for key in ["rows_read", "rows_written", "stocks_touched"]):
            p1, p2, p3 = st.columns(3)
            p1.metric("已读取行数", f"{int(progress.get('rows_read', 0)):,}")
            p2.metric("已保留行数", f"{int(progress.get('rows_written', 0)):,}")
            p3.metric("已处理股票数", f"{int(progress.get('stocks_touched', 0)):,}")
        if any(key in progress for key in ["candidate_count", "accepted_count", "rejected_count", "current_size", "completed_sizes"]):
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("候选因子", f"{int(progress.get('candidate_count', 0)):,}")
            p2.metric("入池因子", f"{int(progress.get('accepted_count', 0)):,}")
            p3.metric("拒绝因子", f"{int(progress.get('rejected_count', 0)):,}")
            p4.metric("当前规模", progress.get("current_size", "-"))
            completed_sizes = progress.get("completed_sizes") or []
            if completed_sizes:
                st.caption("已完成组合规模：" + ",".join(str(item) for item in completed_sizes))
    factor_progress = _load_factor_generation_progress(job_dir)
    if factor_progress:
        g1, g2, g3 = st.columns(3)
        g1.metric("合格因子", f"{int(factor_progress.get('accepted_count', 0)):,}")
        g2.metric("目标数", f"{int(factor_progress.get('target_count', 0)):,}")
        g3.metric("尝试次数", f"{int(factor_progress.get('attempts', 0)):,}")
        if factor_progress.get("latest_checkpoint"):
            st.caption("最新检查点: " + str(factor_progress.get("latest_checkpoint")))
    with st.expander("状态详情", expanded=False):
        st.json(status)
        log_path = status.get("log_path")
        if log_path and Path(log_path).exists():
            st.text_area(
                "后台日志",
                Path(log_path).read_text(encoding="utf-8", errors="replace")[-6000:],
                height=220,
                key=f"job-log:{scope}:{job_dir.name}",
            )
    if status_name == "finished":
        output_dir = Path(status.get("output_dir", ""))
        if output_dir.exists():
            _render_result_dir(output_dir, f"{scope}:{job_dir.name}")
        if status.get("result"):
            with st.expander("平台任务结果", expanded=True):
                st.json(status["result"])
    elif status_name == "failed":
        st.error(status.get("message", "任务失败"))
        if status.get("traceback"):
            with st.expander("错误堆栈"):
                st.code(status["traceback"])
    elif status_name in {"queued", "running"}:
        st.info("当前不会自动刷新；点击下面按钮查看最新状态。")
        if st.button("手动刷新任务状态", key=f"refresh-job:{scope}:{job_dir.name}"):
            _request_rerun()



if __name__ == "__main__":
    from app.workbench import main
    main(sys.modules[__name__])
