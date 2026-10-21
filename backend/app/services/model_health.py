"""
Model health score (0-100): one number that combines what the platform already measures.

Every input comes from stored data; nothing is invented. Components (max points):

    Recent accuracy        40   accuracy of the ACTIVE model on its last <= 50 labeled outcomes
    Recent F1 (macro)      20   same outcomes; catches a model that only gets the frequent category right
    Detector status        20   STABLE 20 · WARNING 10 · DRIFT or adapting 0
    Recent drift events    10   drift alarms in the last 500 outcomes: 0 → 10, 1 → 5, 2+ → 0
    Model freshness        10   outcomes served since it was trained: < 1,000 → 10, < 3,000 → 6, else 3

If the active model has fewer than 10 labeled outcomes, its out-of-fold VALIDATION
accuracy and F1 stand in for the live ones and the result says so (basis = "validation").

Bands: >= 80 HEALTHY · 60-79 AT RISK · < 60 DEGRADED. A confirmed drift or a running
adaptation always reports DEGRADED, and a WARNING caps the band at AT RISK, so the
label never contradicts the detector.
"""
from __future__ import annotations

from datetime import datetime, timezone

RECENT_WINDOW = 50
MIN_LIVE = 10
DRIFT_LOOKBACK = 500

BANDS = {
    "HEALTHY": {"emoji": "🟢", "text": "The active model is accurate and the error stream is stable."},
    "AT_RISK": {"emoji": "🟡", "text": "Performance or the detector suggests the model may be starting to drift."},
    "DEGRADED": {"emoji": "🔴", "text": "The model is underperforming or drift was confirmed; adaptation is required."},
    "UNKNOWN": {"emoji": "⚪", "text": "No active model information is available."},
}


def _iso(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _age_seconds(created_at, now: datetime) -> float | None:
    if created_at is None:
        return None
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created_at).total_seconds())


def compute(*, status: str, adapting: bool, active: dict | None, rows: list[dict], drift_events: list[dict],
            versions: list[dict], records_processed: int, now: datetime | None = None) -> dict:
    """status: detector status; active: active model_versions row; rows: labeled outcomes (oldest first)."""
    from ml.evaluation import classification_metrics

    now = now or datetime.now(timezone.utc)
    if not active:
        return {"score": None, "band": "UNKNOWN", **BANDS["UNKNOWN"], "components": [], "metrics": {},
                "basis": None}
    version = active["version"]
    own = [r for r in rows if r.get("model_version") == version][-RECENT_WINDOW:]
    if len(own) >= MIN_LIVE:
        m = classification_metrics([r["actual"] for r in own], [r["predicted"] for r in own])
        accuracy, f1, basis, n = m["accuracy"], m["f1"], "live", len(own)
    else:
        accuracy, f1, basis, n = active.get("accuracy"), active.get("f1_score"), "validation", len(own)

    components = []

    def add(name, points, max_points, note):
        components.append({"name": name, "points": round(points, 1), "max_points": max_points, "note": note})

    if accuracy is None:
        add("Recent accuracy", 0, 40, "No accuracy measured yet")
    else:
        add("Recent accuracy", 40 * accuracy, 40,
            f"{accuracy:.1%} on the last {n} outcomes" if basis == "live" else
            f"{accuracy:.1%} out-of-fold validation (only {n} live outcomes so far)")
    if f1 is None:
        add("Recent F1", 0, 20, "No F1 measured yet")
    else:
        add("Recent F1", 20 * f1, 20, f"Macro F1 {f1:.1%}")
    det_points = 0 if (adapting or status == "DRIFT") else 10 if status == "WARNING" else 20
    add("Detector status", det_points, 20, "Adaptation running" if adapting else f"Detector reports {status}")
    recent_drifts = [d for d in drift_events if d.get("stream_step", -1) >= records_processed - DRIFT_LOOKBACK]
    add("Recent drift events", 10 if not recent_drifts else 5 if len(recent_drifts) == 1 else 0, 10,
        f"{len(recent_drifts)} in the last {DRIFT_LOOKBACK} outcomes")
    served = max(0, records_processed - (int(active.get("created_step", -1)) + 1))
    add("Model freshness", 10 if served < 1000 else 6 if served < 3000 else 3, 10,
        f"{served} outcomes since it was trained")

    score = round(sum(c["points"] for c in components))
    band = "HEALTHY" if score >= 80 else "AT_RISK" if score >= 60 else "DEGRADED"
    if adapting or status == "DRIFT":
        band = "DEGRADED"
    elif status == "WARNING" and band == "HEALTHY":
        band = "AT_RISK"
    adaptations = [v for v in versions if v.get("kind") != "initial"]
    last_adaptation = adaptations[-1] if adaptations else None
    summary = dict(BANDS[band])
    if band == "DEGRADED":   # say which of the three reasons applies, so the text never claims more than is true
        summary["text"] = (
            "An adaptation is running: drift was confirmed and a replacement model is being trained." if adapting else
            "Drift was confirmed: the pattern the model learned no longer holds for recent data." if status == "DRIFT" else
            "The model is underperforming on recent outcomes. It is only retrained once the detector confirms drift.")
    return {
        "score": score, "band": band, **summary, "basis": basis, "components": components,
        "metrics": {
            "accuracy": None if accuracy is None else round(accuracy, 4),
            "f1": None if f1 is None else round(f1, 4),
            "recent_error": None if accuracy is None else round(1 - accuracy, 4),
            "outcomes_measured": n, "drift_status": status, "model_version": version,
            "adaptation": "running" if adapting else "idle",
            "last_adaptation_at": _iso(last_adaptation.get("created_at")) if last_adaptation else None,
            "last_adaptation_version": last_adaptation["version"] if last_adaptation else None,
            "model_created_at": _iso(active.get("created_at")),
            "model_age_seconds": _age_seconds(active.get("created_at"), now),
            "outcomes_served": served,
            "recent_drift_events": len(recent_drifts),
        },
    }
