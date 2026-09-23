"""File and draft adapters for the workbench, independent of Streamlit and compute.

Public API:
* read_json(path) -> dict: unreadable, malformed and non-object JSON becomes {}.
* resolve_store(master, legacy) -> Path: master needs meta.json and stocks/.
* list_jobs(roots) -> list[dict]: direct child job directories, newest first,
  deduplicated by resolved path. Records retain status metadata and expose path
  (absolute str), operation (manual/platform/unknown), label, status (str),
  updated_at (str), and payload (dict). Missing status is "unknown".
* jobs_for(jobs, operation=None, factor_run_id=None) -> list[dict]: conjunctive
  filtering; batch matching uses generation_config.run_id, factor_run_dir, or
  any compose factor_run_dirs entry. Input records are never mutated.
* choose_id(values, current) -> valid current, first available value, or None.
* copy_manual_run(run) -> {name, expr, pool_id, backtest}: independent editable
  draft from a saved manifest, with a unique new name and deep-copied config.
* validate_backtest(config, meta=None) -> list[str]: Chinese validation errors
  for dates and provided numeric parameters; only disjoint data dates fail,
  since the engine permits partial overlap. No data is loaded or computed.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union
from uuid import uuid4


PathLike = Union[str, Path]


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def read_json(path: PathLike) -> dict:
    """Read a JSON object safely, including UTF-8 files with a BOM."""
    try:
        return _mapping(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def resolve_store(master: PathLike, legacy: PathLike) -> Path:
    """Return the same expanded cache path that backtests should use."""
    master_path = Path(master).expanduser()
    if (master_path / "meta.json").is_file() and (master_path / "stocks").is_dir():
        return master_path
    return Path(legacy).expanduser()


def _read_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        return _mapping(yaml.safe_load(path.read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}


def list_jobs(roots: Iterable[PathLike]) -> list[dict]:
    """Merge existing job roots without conflating equal directory basenames."""
    records = []
    seen = set()
    if isinstance(roots, (str, Path)):
        roots = [roots]
    for root in roots:
        try:
            children = sorted(Path(root).expanduser().iterdir())
        except (OSError, ValueError):
            continue
        for child in children:
            if not child.is_dir():
                continue
            try:
                resolved = child.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            if not any((child / name).is_file() for name in ("status.json", "platform_job.json", "job.json", "config.yaml")):
                continue
            status = read_json(child / "status.json")
            platform = read_json(child / "platform_job.json")
            metadata = read_json(child / "job.json")
            yaml_config = _read_yaml(child / "config.yaml") if (child / "config.yaml").is_file() else {}
            config = dict(yaml_config)
            config.update(metadata)
            config.update(platform)
            operation = str(config.get("operation") or status.get("operation") or "")
            if not operation:
                is_manual = (child / "config.yaml").is_file() or "alphas" in config or "backtest" in config or status.get("run_name") or config.get("run_name")
                operation = "manual" if is_manual else "unknown"
            payload = _mapping(config.get("payload"))
            if not payload and operation == "manual":
                payload = deepcopy(config)
            generation = _mapping(payload.get("generation_config"))
            label = (status.get("run_name") or config.get("run_name") or payload.get("run_name")
                     or payload.get("name") or generation.get("name") or generation.get("run_id")
                     or config.get("name") or child.name)
            record = dict(config)
            record.update(status)
            record.update({
                "path": str(resolved),
                "operation": operation,
                "label": str(label),
                "status": str(status.get("status") or config.get("status") or "unknown"),
                "updated_at": str(status.get("updated_at") or status.get("created_at") or config.get("updated_at") or config.get("created_at") or ""),
                "payload": payload,
            })
            records.append(record)
    return sorted(records, key=lambda row: (row["updated_at"], row["path"]), reverse=True)


def _basename(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def jobs_for(jobs: Iterable[dict], operation: Optional[str] = None, factor_run_id: Optional[str] = None) -> list[dict]:
    """Scope records by operation and exact batch ID, preserving input order."""
    result = []
    for job in jobs:
        if operation is not None and job.get("operation") != operation:
            continue
        if factor_run_id is not None:
            payload = _mapping(job.get("payload"))
            generation = _mapping(payload.get("generation_config"))
            sources = payload.get("factor_run_dirs") or []
            if isinstance(sources, (str, Path)):
                sources = [sources]
            ids = {str(generation.get("run_id") or ""), _basename(payload.get("factor_run_dir"))}
            if isinstance(sources, (list, tuple)):
                ids.update(_basename(source) for source in sources)
            ids.discard("")
            if str(factor_run_id) not in ids:
                continue
        result.append(job)
    return result


def choose_id(values: Iterable[Any], current: Any) -> Any:
    """Retain a selected identifier when it still exists after a refresh."""
    available = list(values)
    return current if current in available else (available[0] if available else None)


def copy_manual_run(run: Mapping[str, Any]) -> dict:
    """Copy a saved configuration; never reuse its original output name."""
    config = _mapping(run.get("config"))
    expression = str(run.get("canonical_expression") or "").strip()
    if not expression:
        alphas = config.get("alphas") or []
        components = []
        for alpha in alphas:
            item = _mapping(alpha)
            expr = str(item.get("expr") or "").strip()
            if expr:
                components.append((expr, float(item.get("weight", 1.0))))
        if len(components) == 1 and components[0][1] == 1.0:
            expression = components[0][0]
        else:
            expression = " + ".join("({:.12g})*({})".format(weight, expr) for expr, weight in components)
    name = str(run.get("run_name") or config.get("run_name") or "manual")
    return {
        "name": "{}_copy_{}".format(name, uuid4().hex[:12]),
        "expr": expression,
        "pool_id": str(run.get("pool_id") or config.get("pool_id") or ""),
        "backtest": deepcopy(_mapping(config.get("backtest") or run.get("backtest"))),
    }


def _date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        return None


def validate_backtest(config: Mapping[str, Any], meta: Optional[Mapping[str, Any]] = None) -> list[str]:
    """Validate dates and supplied financial parameters without engine imports."""
    errors = []
    start, end = _date(config.get("start_date")), _date(config.get("end_date"))
    if start is None:
        errors.append("请填写有效的开始日期（YYYY-MM-DD）。")
    if end is None:
        errors.append("请填写有效的结束日期（YYYY-MM-DD）。")
    if start is not None and end is not None:
        if end < start:
            errors.append("结束日期不能早于开始日期。")
        else:
            data = _mapping(meta)
            lower, upper = _date(data.get("date_min")), _date(data.get("date_max"))
            if (lower and end < lower) or (upper and start > upper):
                errors.append("回测区间内没有可用数据，请调整日期或更新数据缓存。")
    positive = {"top_k": "TopK", "initial_cash": "初始资金", "max_weight_per_stock": "单股最大权重"}
    nonnegative = {"buy_cost": "买入费率", "sell_cost": "卖出费率", "slippage": "滑点", "min_cost": "最低手续费"}
    for key, label in dict(positive, **nonnegative).items():
        if key not in config:
            continue
        try:
            value = float(config[key])
            valid = not isinstance(config[key], bool) and math.isfinite(value)
            valid = valid and (value > 0 if key in positive else value >= 0)
            if key == "top_k":
                valid = valid and value.is_integer()
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            requirement = "正整数" if key == "top_k" else ("大于 0 的有限数值" if key in positive else "大于等于 0 的有限数值")
            errors.append("{}必须是{}。".format(label, requirement))
    return errors
