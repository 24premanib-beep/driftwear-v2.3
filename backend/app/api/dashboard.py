"""Dashboard, performance report and recent real-time events."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_db, get_pipeline, is_staff, require_staff
from app.database.models import User
from app.database.schemas import Stream
from app.errors import PermissionDeniedError
from app.services import analytics, monitoring, queries
from app.services.pipeline import PipelineService

router = APIRouter(prefix="/api", tags=["Dashboard & performance"])


def _check_stream(stream: str, user: User) -> None:
    if stream == "simulation" and not is_staff(user):
        raise PermissionDeniedError("Simulation data is available to analysts and admins.")


@router.get("/dashboard", summary="Live overview: KPIs, accuracy series, drift markers, recent activity")
def dashboard(request: Request, stream: Stream = "live", db: Session = Depends(get_db),
              user: User = Depends(get_current_user), pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    _check_stream(stream, user)
    status = pipeline.status(stream)
    rows = queries.outcome_rows(db, stream)
    events = queries.drift_events(db, stream)
    versions = queries.model_versions(db, stream)
    summary = analytics.summary_metrics(rows)
    recent = analytics.recent_window_metrics(rows)
    adaptations = [v for v in versions if v["kind"] != "initial"]
    markers = analytics.drift_markers(rows, events, versions)
    impact = analytics.drift_impact(rows, events)
    counts = queries.prediction_counts(db, stream, owner_id=None if is_staff(user) else user.id)
    return {
        "mode": stream,
        "kpis": {
            "model_version": status["model_version"], "drift_status": status["status"],
            "status_text": status["status_text"], "detector": status["detector"],
            "records_processed": status["records_processed"],
            "accuracy_recent": recent["accuracy"], "error_rate_recent": recent["error_rate"],
            "accuracy_overall": summary["adaptive"]["accuracy"] if rows else None,
            "baseline_accuracy_overall": summary["baseline"]["accuracy"] if rows else None,
            "drift_events": len(events), "model_versions": len(versions), "adaptations": len(adaptations),
            "predictions": counts["total"],
        },
        "counts": counts,
        "health": monitoring.model_health_for(db, pipeline, stream, rows=rows, events=events, versions=versions),
        "detectors": {"primary": status["detector"], "status": status["status"], "adapting": status.get("adapting"),
                      "shadows": status["shadow_detectors"], "available": status["available_detectors"]},
        "impact": impact[-3:],
        "cycle": analytics.latest_cycle(markers, impact, int(status["records_processed"])),
        "pending_uploaded_records": pipeline.repo.count_pending_records() if stream == "live" else 0,
        "series": analytics.performance_series(rows, max_points=600),
        "markers": markers,
        "last_drift": events[-1] if events else None,
        "last_adaptation": adaptations[-1] if adaptations else None,
        "status": status,
        "recent_events": request.app.state.bus.recent_for(user.id, user.role, limit=15, stream=stream),
    }


@router.get("/performance", summary="Model performance: metrics, confusion matrix, per version/period, before vs after")
def performance(stream: Stream = "live", db: Session = Depends(get_db), user: User = Depends(require_staff),
                pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    rows = queries.outcome_rows(db, stream)
    events = queries.drift_events(db, stream)
    report = analytics.performance_report(rows, events)
    report["series"] = analytics.performance_series(rows, max_points=1000)
    report["feature_importance"] = {
        "current": pipeline.runtimes[stream].engine.feature_importance("current").to_dict("records"),
        "baseline": pipeline.runtimes[stream].engine.feature_importance("baseline").to_dict("records"),
    } if stream in pipeline.runtimes else None
    report["mode"] = stream
    return report


@router.get("/events/recent", summary="Most recent real-time events visible to you (newest first)")
def recent_events(request: Request, stream: Stream | None = None, limit: int = Query(50, ge=1, le=300),
                  user: User = Depends(get_current_user)) -> list[dict]:
    if stream:
        _check_stream(stream, user)
    return request.app.state.bus.recent_for(user.id, user.role, limit=limit, stream=stream)


@router.get("/performance/comparison", summary="Before drift / during drift / after adaptation, with timeline and story")
def drift_comparison(stream: Stream = "live", db: Session = Depends(get_db), _: User = Depends(require_staff),
                     pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    """Accuracy, precision, recall, F1 and error rate in the three phases around every drift event, computed from
    stored labeled outcomes (nothing estimated: a phase without outcomes has n = 0 and null metrics). Also the
    drift timestamp and detector, versions before/after, outcomes handled by each model, the warning and trend
    change before the drift, and the rolling accuracy / error series for the timeline."""
    rows = queries.outcome_rows(db, stream)
    events = queries.drift_events(db, stream)
    versions = queries.model_versions(db, stream)
    markers = analytics.drift_markers(rows, events, versions)
    status = pipeline.status(stream)
    comparison = analytics.drift_comparison(rows, events, versions, warnings=markers["warnings"],
                                            served=queries.prediction_counts_by_version(db, stream))
    return {"mode": stream, **comparison, "series": analytics.performance_series(rows, max_points=1500),
            "markers": markers, "outcomes": len(rows),
            "status": {k: status.get(k) for k in ("model_version", "status", "detector", "records_processed")}}
