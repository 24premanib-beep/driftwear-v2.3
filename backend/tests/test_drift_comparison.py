"""Before / during / after drift comparison and the activation timeline (app/services/analytics.py)."""
from app.services import analytics as A


def _rows():
    rows = []
    for s in range(160):
        if s < 60:
            ok = s % 10 != 0                    # 90% before the change
        elif s < 80:
            ok = s % 4 == 0                     # 25% while drifting (change point 60, detection 79)
        else:
            ok = s % 10 not in (0, 1)           # 80% after adaptation
        rows.append({"step": s, "ts": f"2026-10-01T10:{s // 60:02d}:{s % 60:02d}+00:00", "actual": "Tops",
                     "predicted": "Tops" if ok else "Bottoms", "correct": ok, "baseline_predicted": "Tops",
                     "baseline_correct": True, "model_version": "v1.0" if s <= 79 else "v2.0",
                     "status": "WARNING" if 70 <= s < 79 else ("DRIFT" if s == 79 else "STABLE"),
                     "error": int(not ok), "shadow": {}, "period": 1 if s < 58 else 2,
                     "trend": "Classic" if s < 58 else "Baggy"})
    return rows


EVENT = {"id": 1, "event_key": "Drift 1", "stream_step": 79, "change_point_step": 60, "detector": "DDM",
         "accuracy_stable": 0.9, "accuracy_degraded": 0.25, "error_rate": 0.75, "previous_model_version": "v1.0",
         "new_model_version": "v2.0", "action": "Model Updated", "detected_at": "2026-10-01T10:01:19+00:00"}
VERSIONS = [
    {"version": "v1.0", "kind": "initial", "parent_version": None, "created_at": "2026-10-01T09:00:00+00:00",
     "training_records": 300, "created_step": -1, "trigger": "Historical data", "accuracy": 0.8},
    {"version": "v2.0", "kind": "drift", "parent_version": "v1.0", "created_at": "2026-10-01T10:01:20+00:00",
     "training_records": 20, "window_start": 60, "window_end": 79, "created_step": 79, "trigger": "Drift 1 (DDM)",
     "accuracy": 0.7},
]


def test_comparison_phases_story_and_counts_are_measured():
    rows = _rows()
    out = A.drift_comparison(rows, [EVENT], VERSIONS, served={"v1.0": 85, "v2.0": 90})
    (ev,) = out["events"]
    assert (ev["before"]["n"], ev["during"]["n"], ev["after"]["n"]) == (50, 20, 50)
    assert ev["before"]["accuracy"] == 0.9 and ev["during"]["error_rate"] == 0.75 and ev["after"]["accuracy"] == 0.8
    for phase in ("before", "during", "after"):
        assert {"precision", "recall", "f1", "error_rate"} <= set(ev[phase])
    assert ev["before"]["from_ts"] == rows[10]["ts"] and ev["after"]["to_ts"] == rows[129]["ts"]
    assert ev["predictions"]["before_adaptation"] == 80 and ev["predictions"]["after_adaptation"] == 80
    assert ev["predictions"]["served_by_version"] == {"v1.0": 85, "v2.0": 90}
    assert ev["deltas"]["during_vs_before"]["accuracy"] == -0.65 and ev["deltas"]["after_vs_during"]["accuracy"] == 0.55
    assert ev["warning"]["step"] == 70
    assert ev["trend_change"]["step"] == 58 and ev["trend_change"]["to_trend"] == "Baggy"
    assert ev["adaptation"]["version"] == "v2.0" and ev["adaptation"]["records_used"] == 20
    assert ev["detected_at"] == EVENT["detected_at"] and ev["detector"] == "DDM" and ev["drift_event_id"] == 1
    assert [s["key"] for s in ev["story"]] == ["normal", "trend_change", "errors_rise", "drift", "adaptation",
                                                "recovery"]
    assert all(s["status"] == "done" for s in ev["story"]) and ev["recovered"] is True
    assert out["pooled"]["before"]["n"] == 50 and out["pooled"]["after"]["accuracy"] == 0.8
    assert ev["focus"] == {"from_step": 10, "to_step": 129}


def test_comparison_never_invents_missing_phases():
    ev = A.drift_comparison(_rows()[:82], [EVENT], VERSIONS)["events"][0]
    assert ev["after"]["n"] == 2 and ev["recovered"] is None and ev["story"][-1]["status"] == "pending"
    assert A.drift_comparison(_rows(), [], VERSIONS)["events"] == []
    failed = A.drift_comparison(_rows(), [{**EVENT, "new_model_version": None, "action": "Adaptation failed"}],
                                VERSIONS)["events"][0]
    assert failed["adaptation"] is None and failed["story"][4]["status"] == "failed"
    empty = A.window_metrics([])
    assert empty["n"] == 0 and empty["accuracy"] is None


def test_activation_timeline_merges_training_and_rollbacks():
    acts = [{"created_at": "2026-10-01T12:00:00+00:00", "action": "rollback", "from_version": "v2.0",
             "to_version": "v1.0", "reason": "bad outerwear predictions", "user_id": 1, "user_name": "Ada",
             "at_step": 120}]
    t = A.activation_timeline(VERSIONS, acts)
    assert [x["action"] for x in t] == ["rollback", "adapted", "trained"]
    assert t[0]["actor"] == "Ada" and t[0]["reason"] == "bad outerwear predictions" and t[1]["actor"] == "System"
