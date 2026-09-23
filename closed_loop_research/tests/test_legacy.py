import pandas as pd

from .helpers import panel
from closed_loop_research.legacy import import_legacy
from closed_loop_research.data import DataAccess
from closed_loop_research.protocol import Protocol
from closed_loop_research.storage import read_json, file_digest


def test_legacy_copy_explicitly_marks_assumptions_and_leaves_source(tmp_path):
    source = tmp_path / "old.parquet"
    data = panel()
    data["Ifsuspend"] = 0
    data.to_parquet(source, index=False)
    before = file_digest(source)
    target = tmp_path / "new"
    import_legacy(source, target, sessions=30, warmup=8, seed=3)
    p = Protocol.from_dict(read_json(target / "protocol.json"))
    assert p.data_mode == "legacy_prototype" and not p.synthetic
    assert file_digest(source) == before
    access = DataAccess(target / "snapshot", p, "train")
    assert access.manifest["data_mode"] == "legacy_prototype"
    assert access.manifest["fields"]["close"]["verified"] is False
    assert len(access.load("F").frame) > 0
    assert read_json(target / "import_report.json")["source_sha256"] == before


def test_missing_open_mark_uses_strictly_previous_close(tmp_path):
    source = tmp_path / "old.parquet"
    data = panel()
    data["Ifsuspend"] = 0
    date = pd.Timestamp("2020-01-07")
    row = (data.date == date) & (data.code == "000001")
    previous = data.loc[(data.date < date) & (data.code == "000001"), "close"].iloc[-1]
    data.loc[row, "open"] = float("nan")
    data.loc[row, "close"] = 999.
    data.to_parquet(source, index=False)
    target = tmp_path / "new"
    import_legacy(source, target, sessions=30, warmup=8)
    p = Protocol.from_dict(read_json(target / "protocol.json"))
    access = DataAccess(target / "snapshot", p, "train")
    frame = pd.concat([access.load(s).frame for s in "FE"])
    found = frame.loc[(frame.date == date) & (frame.code == "000001"), "exec_open"]
    assert len(found) and (found == previous).all()
