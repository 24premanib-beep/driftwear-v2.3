"""Reference runs shared by the slow tests (computed once per test session)."""
from __future__ import annotations

import collections
import sys
from functools import lru_cache
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def summarize(steps: list[tuple], drift_steps: list[int], versions: list[str]) -> dict:
    per = collections.defaultdict(lambda: [0, 0, 0])
    for _, correct, base_correct, period in steps:
        per[period][0] += 1
        per[period][1] += int(correct)
        per[period][2] += int(base_correct)
    return {"drift_steps": drift_steps, "versions": versions,
            "by_period": {p: (round(c / n, 3), round(b / n, 3)) for p, (n, c, b) in sorted(per.items())},
            "n": len(steps)}


@lru_cache
def new_engine_run() -> dict:
    """The refactored engine over the full simulated stream, uninterrupted, no persistence."""
    from ml.simulation import SimulationFeed
    from ml.stream_engine import DriftEngine
    feed = SimulationFeed.from_seed()
    eng, v1 = DriftEngine.bootstrap("simulation", feed.training_rows())
    steps, per_step, drifts, versions = [], [], [], [v1.version]
    while (nxt := feed.next_record()) is not None:
        rec, actual = nxt
        p = eng.predict(rec)
        o = eng.record_outcome(rec, actual, p.predicted, p.model_version, p.baseline_prediction, rec["Record_ID"])
        steps.append((o.step, o.is_correct, o.baseline_correct, rec["Period"]))
        per_step.append((p.predicted, round(p.confidence, 4), o.correct, o.baseline_correct, p.model_version,
                         o.status))
        if o.drift_event:
            drifts.append(o.step)
        if o.new_version:
            versions.append(o.new_version.version)
    out = summarize(steps, drifts, versions)
    out["per_step"] = per_step
    return out


@lru_cache
def legacy_engine_run(tmp_dir: str) -> dict:
    """The ORIGINAL Streamlit prototype engine (legacy_streamlit/src), file outputs redirected to tmp."""
    # append, never prepend: legacy_streamlit/app.py must not shadow the backend's `app` package
    legacy = str(PROJECT / "legacy_streamlit")
    if legacy not in sys.path:
        sys.path.append(legacy)
    from src import config as lc
    tmp = Path(tmp_dir)
    for name, val in dict(MODELS_DIR=tmp, ARCHIVE_DIR=tmp / "archive", PREDICTIONS_PATH=tmp / "p.csv",
                          DRIFT_EVENTS_PATH=tmp / "d.csv", MODEL_PATH=tmp / "m.pkl",
                          BASELINE_MODEL_PATH=tmp / "b.pkl", METADATA_PATH=tmp / "meta.json").items():
        setattr(lc, name, val)
    from src.stream_engine import StreamEngine
    e = StreamEngine.load_or_create()
    e.process_batch(100_000)
    h = e.history_df
    steps = [(int(r.step), bool(r.correct), bool(r.baseline_correct), int(r.period)) for r in h.itertuples()]
    out = summarize(steps, [d["step"] for d in e.drift_events], [a["to_version"] for a in e.adaptations])
    out["per_step"] = [(r.predicted, round(float(r.confidence), 4), bool(r.correct), bool(r.baseline_correct),
                        r.model_version, r.detector_status) for r in h.itertuples()]
    out["drift_events"] = e.drift_events
    return out
