"""Model health score (app/services/model_health.py)."""
from app.services import model_health as MH

ACTIVE = {"version": "v2.0", "accuracy": 0.8, "f1_score": 0.75, "created_step": 99, "created_at": "2026-10-01T00:00:00+00:00",
          "kind": "drift"}
VERSIONS = [{"version": "v1.0", "kind": "initial", "created_at": "2026-09-01T00:00:00+00:00"}, ACTIVE]


def _rows(n, acc, version="v2.0", start=100):
    return [{"step": start + i, "model_version": version, "actual": "Tops",
             "predicted": "Tops" if i < round(acc * n) else "Dresses"} for i in range(n)]


def test_accurate_stable_model_is_healthy():
    h = MH.compute(status="STABLE", adapting=False, active=ACTIVE, rows=_rows(50, 0.96), drift_events=[],
                   versions=VERSIONS, records_processed=150)
    assert h["band"] == "HEALTHY" and h["score"] >= 80 and h["basis"] == "live"
    assert h["metrics"]["accuracy"] == 0.96 and h["metrics"]["recent_error"] == 0.04
    assert h["metrics"]["last_adaptation_version"] == "v2.0"
    assert sum(c["max_points"] for c in h["components"]) == 100


def test_drift_or_adaptation_is_always_degraded():
    for status, adapting in (("DRIFT", False), ("STABLE", True)):
        h = MH.compute(status=status, adapting=adapting, active=ACTIVE, rows=_rows(50, 0.96), drift_events=[],
                       versions=VERSIONS, records_processed=150)
        assert h["band"] == "DEGRADED"
    h = MH.compute(status="STABLE", adapting=True, active=ACTIVE, rows=_rows(50, 0.96), drift_events=[],
                   versions=VERSIONS, records_processed=150)
    assert h["metrics"]["adaptation"] == "running"


def test_warning_caps_at_risk_and_low_accuracy_degrades():
    h = MH.compute(status="WARNING", adapting=False, active=ACTIVE, rows=_rows(50, 1.0), drift_events=[],
                   versions=VERSIONS, records_processed=150)
    assert h["band"] == "AT_RISK"
    h = MH.compute(status="STABLE", adapting=False, active=ACTIVE, rows=_rows(50, 0.3),
                   drift_events=[{"stream_step": 120}, {"stream_step": 140}], versions=VERSIONS, records_processed=150)
    assert h["band"] == "DEGRADED" and h["metrics"]["recent_drift_events"] == 2


def test_degraded_text_names_the_actual_reason():
    def text(status, adapting, acc):
        return MH.compute(status=status, adapting=adapting, active=ACTIVE, rows=_rows(50, acc), drift_events=[],
                          versions=VERSIONS, records_processed=150)["text"]
    assert text("STABLE", True, 0.96).startswith("An adaptation is running")
    assert text("DRIFT", False, 0.96).startswith("Drift was confirmed")
    low = text("STABLE", False, 0.2)                 # degraded by accuracy alone: nothing claims drift or retraining
    assert low.startswith("The model is underperforming") and "only retrained once the detector confirms drift" in low


def test_falls_back_to_validation_metrics_and_says_so():
    h = MH.compute(status="STABLE", adapting=False, active=ACTIVE, rows=_rows(3, 1.0), drift_events=[],
                   versions=VERSIONS, records_processed=103)
    assert h["basis"] == "validation" and h["metrics"]["accuracy"] == 0.8 and h["metrics"]["outcomes_measured"] == 3
    other = MH.compute(status="STABLE", adapting=False, active=ACTIVE, rows=_rows(50, 1.0, version="v1.0"),
                       drift_events=[], versions=VERSIONS, records_processed=150)
    assert other["basis"] == "validation"          # outcomes of OTHER versions are not this model's accuracy


def test_no_active_model_is_unknown():
    h = MH.compute(status="STABLE", adapting=False, active=None, rows=[], drift_events=[], versions=[],
                   records_processed=0)
    assert h["band"] == "UNKNOWN" and h["score"] is None
