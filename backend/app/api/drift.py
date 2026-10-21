"""Drift monitoring and drift-pipeline controls."""
from __future__ import annotations

import statistics
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.common import audit_async
from app.auth.dependencies import get_current_user, get_db, get_pipeline, require_admin, require_staff
from app.database.models import User
from app.database.schemas import DetectorRequest, DriftEventOut, ProcessRequest, Stream
from app.services import analytics, data_drift, queries
from app.services.pipeline import LIVE, PipelineService

router = APIRouter(prefix="/api/drift", tags=["Concept drift"])


@router.get("/status", summary="Current detector status (STABLE / WARNING / DRIFT) and model")
def drift_status(stream: Stream = "live", user: User = Depends(get_current_user),
                 pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    if stream == "simulation" and user.role not in ("analyst", "admin"):
        stream = LIVE
    return pipeline.status(stream)


@router.get("/events", response_model=list[DriftEventOut], summary="Detected drift events (newest first)")
def drift_events(stream: Stream = "live", limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db),
                 _: User = Depends(require_staff)) -> list[dict]:
    return queries.drift_events(db, stream, limit=limit, newest_first=True)


@router.get("/statistics", summary="Error-rate series with warning/drift markers, detector comparison, delays")
def drift_statistics(stream: Stream = "live", db: Session = Depends(get_db), _: User = Depends(require_staff),
                     pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    rows = queries.outcome_rows(db, stream)
    events = queries.drift_events(db, stream)
    versions = queries.model_versions(db, stream)
    status = pipeline.status(stream)
    delays = [e["detection_delay"] for e in events if e.get("detection_delay") is not None]
    windows = [e["window_size"] for e in events if e.get("window_size")]
    markers = analytics.drift_markers(rows, events, versions)
    return {
        "mode": stream,
        "status": status,
        "series": analytics.performance_series(rows, max_points=1500),
        "markers": markers,
        "status_counts": analytics.status_counts(rows),
        "detectors": {
            "primary": status["detector"], "description": status["detector_description"],
            "backend": status["detector_backend"], "available": status["available_detectors"],
            "shadow_status": status["shadow_detectors"],
            "shadow_drift_counts": {k: len(v) for k, v in markers["shadow_drifts"].items()},
            "note": "Shadow detectors watch the same error stream for comparison only; "
                    "the primary detector alone triggers adaptation.",
        },
        "summary": {
            "drift_events": len(events), "warnings": len(markers["warnings"]),
            "mean_detection_delay": round(statistics.mean(delays), 1) if delays else None,
            "mean_window_size": round(statistics.mean(windows), 1) if windows else None,
            "records_monitored": len(rows),
        },
        "before_after": analytics.before_after(events),
        "impact": analytics.drift_impact(rows, events),
        "definition": data_drift.EXPLANATION["concept_drift"],
    }


@router.get("/data", summary="DATA drift: input feature distributions, reference vs recent inputs")
def data_drift_report(stream: Stream = "live", window: int = Query(200, ge=30, le=2000,
                                                                   description="Most recent inputs to compare"),
                      reference: Literal["baseline", "active"] = Query(
                          "baseline", description="baseline = data v1.0 was trained on; active = the active "
                                                  "model's training window"),
                      db: Session = Depends(get_db), _: User = Depends(require_staff),
                      pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    """Population Stability Index per feature (and a KS test for numeric features). Uses every recent
    input, labeled or not. This is diagnostic: only CONCEPT drift (the error stream) triggers adaptation."""
    current, cur_info = queries.recent_inputs(db, stream, window)
    ref, ref_info = pipeline.reference_inputs(stream, reference)
    return {"mode": stream, **data_drift.compare(ref, current, reference_info=ref_info, current_info=cur_info)}


@router.post("/process", summary="Run labeled records through the pipeline (admin)")
async def process(body: ProcessRequest, request: Request, admin: User = Depends(require_admin),
                  pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    """`stream=live`: process the next uploaded (validated, labeled) records in purchase-date order.
    `stream=simulation`: advance the simulated stream by `count` records."""
    if body.stream == LIVE:
        res = {"mode": "live", **await pipeline.process_uploaded(body.count)}
    else:
        res = {"mode": "simulation", **await pipeline.simulate(body.count, body.stop_on_drift)}
    await audit_async(request, "data.processed", user=admin, resource="stream", resource_id=body.stream,
                      stream=body.stream, details={"requested": body.count, "processed": res.get("processed"),
                                                   "drift_events": len(res.get("drift_events") or []),
                                                   "new_versions": res.get("new_versions")})
    return res


@router.post("/detector", summary="Switch the primary drift detector (admin)")
async def set_detector(body: DetectorRequest, request: Request, admin: User = Depends(require_admin),
                       pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    previous = pipeline.status(body.stream)["detector"]
    res = await pipeline.set_detector(body.stream, body.detector)
    await audit_async(request, "config.detector_changed", user=admin, resource="detector", resource_id=body.detector,
                      stream=body.stream, severity="warning",
                      details={"previous": previous, "detector": body.detector, "status": res.get("status")})
    return res
