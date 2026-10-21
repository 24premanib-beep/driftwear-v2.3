"""Chart series, drift markers and metrics (app/services/analytics.py)."""
from app.services import analytics as A


def _rows(n=20):
    return [{"step": i, "ts": f"t{i}", "predicted": "Tops" if i % 3 else "Bottoms", "actual": "Tops",
             "correct": i % 3 != 0, "baseline_predicted": "Tops" if i < 10 else "Dresses", "baseline_correct": i < 10,
             "model_version": "v1.0" if i < 12 else "v2.0",
             "status": "WARNING" if 8 <= i < 11 else ("DRIFT" if i == 11 else "STABLE"), "error": int(i % 3 == 0),
             "shadow": {"ADWIN": "DRIFT"} if i == 10 else {}, "period": 1 if i < 12 else 2,
             "trend": "A" if i < 12 else "B"} for i in range(n)]


def test_series_and_markers():
    rows = _rows()
    series = A.performance_series(rows, window=5)
    assert len(series) == 20 and series[11]["status"] == "DRIFT" and 0 <= series[11]["accuracy"] <= 1
    m = A.drift_markers(rows, [{"stream_step": 11, "event_key": "Drift 1", "detector": "DDM", "change_point_step": 7,
                                "previous_model_version": "v1.0", "new_model_version": "v2.0",
                                "action": "Model Updated"}],
                        [{"created_step": 11, "version": "v2.0", "kind": "drift"},
                         {"created_step": -1, "version": "v1.0", "kind": "initial"}])
    assert [w["step"] for w in m["warnings"]] == [8]
    assert m["drifts"][0]["step"] == 11 and [a["version"] for a in m["adaptations"]] == ["v2.0"]
    assert m["shadow_drifts"] == {"ADWIN": [10]}
    assert A.status_counts(rows) == {"STABLE": 16, "WARNING": 3, "DRIFT": 1}


def test_metrics_and_breakdowns():
    rows = _rows()
    s = A.summary_metrics(rows)
    assert s["n"] == 20 and s["adaptive"]["accuracy"] == 0.65 and s["baseline"]["accuracy"] == 0.5
    assert [v["version"] for v in A.by_version(rows)] == ["v1.0", "v2.0"]
    periods = A.by_period(rows)
    assert periods[1]["static_accuracy"] == 0.0 and periods[1]["trend"] == "B"
    cm = A.confusion(rows)
    assert sum(map(sum, cm["matrix"])) == 20
    assert A.recent_window_metrics(rows, 5)["n"] == 5


def test_empty_and_long_inputs():
    assert A.performance_series([]) == [] and A.summary_metrics([])["n"] == 0
    long = [dict(r, step=i) for i, r in enumerate(_rows() * 100)]
    sampled = A.performance_series(long, max_points=50)
    assert len(sampled) <= 51 and sampled[-1]["step"] == len(long) - 1
