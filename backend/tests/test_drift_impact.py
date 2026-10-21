"""Before / during / after drift metrics and the latest detect → adapt → recover cycle."""
from app.services import analytics as A


def _rows():
    rows = []
    for s in range(0, 160):
        if s < 60:
            ok = s % 10 != 0                    # 90% before the change
        elif s < 80:
            ok = s % 4 == 0                     # 25% while drifting (change point 60, detection 79)
        else:
            ok = s % 10 not in (0, 1)           # 80% after adaptation
        rows.append({"step": s, "ts": None, "actual": "Tops", "predicted": "Tops" if ok else "Bottoms",
                     "correct": ok, "baseline_predicted": "Tops", "baseline_correct": True,
                     "model_version": "v1.0" if s <= 79 else "v2.0", "status": "STABLE", "error": int(not ok),
                     "shadow": {}, "period": None, "trend": None})
    return rows


EVENT = {"event_key": "Drift 1", "stream_step": 79, "change_point_step": 60, "detector": "DDM",
         "accuracy_stable": 0.9, "accuracy_degraded": 0.25, "error_rate": 0.75, "previous_model_version": "v1.0",
         "new_model_version": "v2.0", "action": "Model Updated", "detected_at": None}


def test_impact_measures_real_segments():
    (imp,) = A.drift_impact(_rows(), [EVENT])
    assert imp["before"]["n"] == 50 and imp["before"]["accuracy"] == 0.9
    assert imp["during"]["n"] == 20 and imp["during"]["accuracy"] == 0.25 and imp["during"]["error_rate"] == 0.75
    assert imp["after"]["n"] == 50 and imp["after"]["accuracy"] == 0.8
    for seg in ("before", "during", "after"):
        assert {"precision", "recall", "f1"} <= set(imp[seg])
    assert imp["recovered"] is True and imp["severity"] == "High"


def test_impact_without_after_data_is_pending_not_invented():
    (imp,) = A.drift_impact(_rows()[:82], [EVENT])
    assert imp["after"]["n"] == 2 and imp["recovered"] is None


def test_latest_cycle_stages():
    rows = _rows()
    markers = {"warnings": [{"step": 70}], "drifts": [], "adaptations": []}
    stages = A.latest_cycle(markers, A.drift_impact(rows, [EVENT]), 160)
    assert [s["key"] for s in stages] == ["prediction", "warning", "drift", "retraining", "new_model", "recovery"]
    assert all(s["status"] == "done" for s in stages)
    empty = A.latest_cycle({"warnings": []}, [], 0)
    assert empty[0]["status"] == "none" and all(s["status"] == "none" for s in empty[2:])


def test_severity_levels():
    assert A.drift_severity(0.9, 0.5) == "High"
    assert A.drift_severity(0.8, 0.62) == "Medium"
    assert A.drift_severity(0.8, 0.72) == "Low"
    assert A.drift_severity(None, None, 0.7) == "High"
