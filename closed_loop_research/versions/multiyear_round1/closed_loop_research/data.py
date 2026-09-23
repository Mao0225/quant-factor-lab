"""Offline snapshot preparation and role-restricted, audited partition loading.

This is an application capability boundary, not a sandbox against malicious
Python code or a user with direct filesystem access.
"""
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pandas as pd

from .storage import atomic_json, read_json, digest, file_digest


class DataIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SegmentData:
    segment: str
    start: str
    end: str
    frame: pd.DataFrame
    snapshot_id: str

    @property
    def signal_dates(self):
        dates = sorted(self.frame.date.unique())
        return [dates[i-1] for i, d in enumerate(dates) if self.start <= str(pd.Timestamp(d).date()) <= self.end and i > 0]


def prepare_snapshot(frame, destination, protocol, field_metadata, source_metadata=None):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    required = {"date", "code", "open", "close", "eligible", "can_buy_open", "can_sell_open",
                "share_multiplier", "cash_dividend"} | set(protocol.fields)
    required |= {f"{f}__available_at" for f in protocol.fields}
    required |= set(frame.columns) & {"exec_open", "exec_close"}
    if not required.issubset(frame):
        raise ValueError(f"missing audited input columns: {sorted(required-set(frame))}")
    for field in protocol.fields:
        meta = field_metadata.get(field, {})
        if (protocol.data_mode == "audited" and meta.get("verified") is not True) or any(not meta.get(k) for k in ["source", "unit", "description", "availability", "adjustment"]):
            raise ValueError(f"unverified field: {field}")
        if protocol.data_mode == "legacy_prototype" and not meta.get("prototype_assumption"):
            raise ValueError("prototype fields require explicit assumptions")
        if protocol.data_mode == "audited" and meta["adjustment"] != "raw":
            raise ValueError("first kernel accepts audited raw-price features only")
    data = frame[sorted(required)].copy()
    data["date"] = pd.to_datetime(data.date, errors="raise").dt.normalize()
    if data.date.isna().any() or data.code.isna().any():
        raise ValueError("missing date/code")
    data["code"] = data.code.astype(str)
    if data.duplicated(["date", "code"]).any():
        raise ValueError("duplicate date/code")
    data = data.sort_values(["date", "code"]).reset_index(drop=True)
    for c in ["eligible", "can_buy_open", "can_sell_open"]:
        if data[c].isna().any() or not data[c].isin([True, False]).all():
            raise ValueError(f"explicit boolean required: {c}")
        data[c] = data[c].astype(bool)
    for c in ["open", "close", "share_multiplier", "cash_dividend", *protocol.fields]:
        data[c] = pd.to_numeric(data[c], errors="raise")
    if not np.isfinite(data[["share_multiplier", "cash_dividend"]]).all().all() or (data.share_multiplier <= 0).any() or (data.cash_dividend < 0).any():
        raise ValueError("invalid corporate actions")
    # Preserve execution prices separately from availability-masked feature values.
    if "exec_open" not in data:
        data["exec_open"] = data.open
    if "exec_close" not in data:
        data["exec_close"] = data.close
    for f in protocol.fields:
        available = pd.to_datetime(data[f"{f}__available_at"], errors="raise")
        data.loc[available.isna() | (available > data.date + pd.Timedelta(hours=15)), f] = np.nan
    dates = sorted(data.date.unique())
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination.parent))
    try:
        parts = {}
        for segment in "FEVT":
            start, end = protocol.bounds(segment)
            positions = [i for i, d in enumerate(dates) if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
            if not positions or positions[0] < protocol.warmup:
                raise ValueError(f"{segment}: missing evaluation dates or required past warm-up ({protocol.warmup} sessions)")
            lo = dates[positions[0] - protocol.warmup]
            part = data[(data.date >= lo) & (data.date <= pd.Timestamp(end))]
            path = stage / f"{segment}.parquet"
            part.to_parquet(path, index=False)
            parts[segment] = dict(file=path.name, sha256=file_digest(path), rows=len(part), start=start, end=end,
                                  history_start=str(pd.Timestamp(lo).date()))
        manifest = dict(schema=1, data_digest=protocol.data_digest, synthetic=protocol.synthetic, data_mode=protocol.data_mode,
                        fields=field_metadata, parts=parts, universe_note=protocol.universe_note,
                        execution_note=protocol.execution_note)
        if source_metadata is not None:
            manifest["source_metadata"] = source_metadata
        manifest["snapshot_id"] = digest(manifest)
        atomic_json(stage / "manifest.json", manifest)
        stage.rename(destination)
    except BaseException:
        # Only the freshly created staging directory can be removed.
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return manifest


class DataAccess:
    def __init__(self, root, protocol, role, audit=None):
        if role not in {"train", "selection", "test"}:
            raise ValueError("unknown role")
        self._root, self._protocol, self._role = Path(root), protocol, role
        self.audit = audit if audit is not None else []
        self.manifest = read_json(self._root / "manifest.json")
        body = {k: v for k, v in self.manifest.items() if k != "snapshot_id"}
        if digest(body) != self.manifest["snapshot_id"] or self.manifest["data_digest"] != protocol.data_digest:
            raise DataIntegrityError("manifest/protocol identity mismatch")

    def load(self, segment, authorization=None):
        allowed = segment in {"train": {"F", "E"}, "selection": {"V"}, "test": {"T"}}[self._role]
        if self._role != "train":
            allowed = allowed and isinstance(authorization, dict) and authorization.get("protocol_digest") == self._protocol.digest
            allowed = allowed and authorization.get("kind") == {"selection": "registered_selection", "test": "frozen_model"}[self._role]
        self.audit.append(dict(role=self._role, segment=segment, allowed=bool(allowed),
                               snapshot_id=self.manifest["snapshot_id"]))
        if not allowed:
            raise PermissionError(f"{self._role} cannot access {segment} without the correct lifecycle authorization")
        entry = self.manifest["parts"][segment]
        if entry["file"] != f"{segment}.parquet":
            raise DataIntegrityError("invalid partition path")
        path = self._root / entry["file"]
        if file_digest(path) != entry["sha256"]:
            raise DataIntegrityError(f"partition tampered: {segment}")
        frame = pd.read_parquet(path)
        return SegmentData(segment, entry["start"], entry["end"], frame, self.manifest["snapshot_id"])
