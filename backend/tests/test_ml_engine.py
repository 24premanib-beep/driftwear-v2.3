"""
The refactored ML engine (ml/) against the original prototype, plus the new
engine behaviours (prediction/outcome split, late labels, restore, versioning).
"""
import tempfile

import pytest

from ml import config
from ml.adaptation import bump_version, next_version
from ml.simulation import SimulationFeed
from ml.stream_engine import DriftEngine, EngineError, EngineSnapshot
from tests.reference import legacy_engine_run, new_engine_run


@pytest.mark.slow
def test_refactored_engine_matches_original_prototype_record_by_record():
    """Same data, same environment: every prediction, version and drift event must be identical."""
    legacy = legacy_engine_run(tempfile.mkdtemp())
    new = new_engine_run()
    assert new["n"] == legacy["n"] == 1800
    mismatches = [i for i, (a, b) in enumerate(zip(legacy["per_step"], new["per_step"])) if a != b]
    assert mismatches == [], f"first differing steps: {mismatches[:5]}"
    assert new["drift_steps"] == legacy["drift_steps"]
    assert new["versions"] == legacy["versions"]
    assert new["by_period"] == legacy["by_period"]
    # the adaptive model must clearly beat the frozen v1.0 baseline once fashion trends change
    later = [p for p in new["by_period"] if p > 1]
    assert all(new["by_period"][p][0] > new["by_period"][p][1] + 0.3 for p in later)


def _engine():
    feed = SimulationFeed.from_seed()
    eng, _ = DriftEngine.bootstrap("test", feed.training_rows())
    return eng, feed


def test_predict_does_not_touch_the_detector():
    eng, feed = _engine()
    rec, _ = feed.next_record()
    before = (eng.next_step, eng.monitor.n_seen, eng.status)
    for _ in range(5):
        p = eng.predict(rec)
    assert (eng.next_step, eng.monitor.n_seen, eng.status) == before
    assert p.model_version == "v1.0" and 0 < p.confidence <= 1
    assert set(p.probabilities) <= set(config.CATEGORIES)


def test_outcome_from_older_model_is_rescored_by_current_model():
    eng, feed = _engine()
    for _ in range(30):
        rec, actual = feed.next_record()
        p = eng.predict(rec)
        eng.record_outcome(rec, actual, p.predicted, p.model_version, p.baseline_prediction)
    rec, actual = feed.next_record()
    old = eng.predict(rec)                       # made by v1.0
    eng.adapt_now("test")                        # v1.1 becomes current before the label arrives
    o = eng.record_outcome(rec, actual, old.predicted, old.model_version, old.baseline_prediction)
    assert o.rescored and o.scored_version == "v1.1"
    assert o.predicted == old.predicted          # the stored prediction is not rewritten


def test_restore_from_snapshot_continues_identically():
    eng_a, feed_a = _engine()
    eng_b, feed_b = _engine()
    for _ in range(40):
        for eng, feed in ((eng_a, feed_a), (eng_b, feed_b)):
            rec, actual = feed.next_record()
            p = eng.predict(rec)
            eng.record_outcome(rec, actual, p.predicted, p.model_version, p.baseline_prediction)
    snap = EngineSnapshot(stream="test", detector=eng_b.detector_name, current=eng_b.current,
                          baseline=eng_b.baseline, history=list(eng_b.history), next_step=eng_b.next_step,
                          detector_reset_step=eng_b.detector_reset_step, refresh_anchor=eng_b.refresh_anchor,
                          pending_refresh=list(eng_b.pending_refresh), n_drifts=eng_b.n_drifts,
                          open_backfills=list(eng_b.open_backfills), known_versions=set(eng_b.known_versions))
    eng_b = DriftEngine.restore(snap)
    assert eng_b.status_info() == eng_a.status_info()
    for _ in range(40):
        outs = []
        for eng, feed in ((eng_a, feed_a), (eng_b, feed_b)):
            rec, actual = feed.next_record()
            p = eng.predict(rec)
            o = eng.record_outcome(rec, actual, p.predicted, p.model_version, p.baseline_prediction)
            outs.append((p.predicted, o.status, o.correct))
        assert outs[0] == outs[1]


def test_manual_adapt_needs_enough_labeled_data():
    eng, _ = _engine()
    with pytest.raises(EngineError):
        eng.adapt_now()


def test_version_names_are_never_reused():
    assert next_version("v1.0", True, {"v1.0"}) == bump_version("v1.0", True) == "v2.0"
    assert next_version("v2.0", False, {"v1.0", "v2.0"}) == "v2.1"
    assert next_version("v2.0", True, {"v1.0", "v2.0", "v2.1", "v3.0"}) == "v4.0"   # after a rollback
    assert next_version("v2.1", False, {"v2.1", "v2.2"}) == "v2.3"


def test_simulation_trend_change_jumps_to_next_period():
    feed = SimulationFeed.from_seed()
    assert feed.current_period == 1
    info = feed.trend_change()
    assert info["ok"] and info["to_period"] == 2 and feed.current_period == 2
    assert feed.trend_change()["to_period"] == 3
    assert not feed.trend_change()["ok"]
