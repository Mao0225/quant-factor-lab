import numpy as np
import pandas as pd
import pytest

from .helpers import protocol, snapshot
from .test_foundation import trading_frame, signals
from closed_loop_research.backtest import backtest, prepare_market
from closed_loop_research.versions.first_edition.closed_loop_research.backtest import backtest as reference_backtest
from closed_loop_research.data import DataAccess
from closed_loop_research.evaluation import SegmentEvaluator
from closed_loop_research.scoring import score
from closed_loop_research.storage import read_json


def test_prepared_path_matches_original_share_cash_trade_ledger():
    p = protocol(top_k=1, buy_fee=.003, sell_fee=.004, minimum_fee=1., slippage=.001)
    frame = trading_frame()
    s = signals(frame)
    s.loc[(s.date == pd.Timestamp("2020-01-06")) & (s.code == "b"), "score"] = 5
    for blocked in [True, False]:
        frame.loc[(frame.date == pd.Timestamp("2020-01-07")) & (frame.code == "a"), "can_sell_open"] = not blocked
        ref = reference_backtest(frame, s, "2020-01-06", "2020-01-07", p).to_dict()
        out = backtest(frame, s, "2020-01-06", "2020-01-07", p, prepared=prepare_market(frame)).to_dict()
        assert out == ref


def test_cached_scoring_and_rankings_match_reference_with_ties_missing_and_negative(tmp_path):
    p, path = snapshot(tmp_path)
    f = SegmentEvaluator(DataAccess(path,p,"train").load("F"),p,tmp_path/"artifacts")
    for weights in [{"close": 1.}, {"close": -.7, "volume": .3}]:
        values = {k:f.factor(k) for k in weights}
        reference_scores = score(f.signal_frame, values, weights, p)
        np.testing.assert_allclose(f.scores(weights).score,reference_scores.score)
        expected = reference_backtest(f.data.frame,reference_scores,f.data.start,f.data.end,p).to_dict()
        actual = f.evaluate(weights)
        saved = read_json(tmp_path/"artifacts"/f"{actual['artifact_id']}.json")
        assert saved["result"] == expected
    assert f.normalization_computations == 2


def test_compressed_artifacts_keep_complete_evidence_and_detect_corruption(tmp_path):
    p,path = snapshot(tmp_path,protocol(compress_artifacts=True))
    data=DataAccess(path,p,"train").load("F")
    f=SegmentEvaluator(data,p,tmp_path/"artifacts")
    r=f.evaluate({"close":1.})
    artifact=tmp_path/"artifacts"/f"{r['artifact_id']}.json.gz"
    assert artifact.exists()
    saved=read_json(artifact)
    assert saved['result']['positions'] and saved['result']['trades']
    assert read_json(artifact.with_suffix(''))==saved
    fresh=SegmentEvaluator(data,p,tmp_path/"artifacts")
    assert fresh.evaluate({"close":1.})['cache_hit']
    artifact.write_bytes(b'not gzip')
    with pytest.raises((OSError,ValueError)):
        SegmentEvaluator(data,p,tmp_path/"artifacts").evaluate({"close":1.})
