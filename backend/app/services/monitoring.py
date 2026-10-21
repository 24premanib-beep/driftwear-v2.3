"""
Composition of the monitoring views (model health, system monitoring).

Shared by the dashboard, the model registry and the System monitoring routes so
each number is computed one way only. Inputs are a database session and the
running PipelineService; everything returned is derived from stored rows or the
live engine state.
"""
from __future__ import annotations

import platform
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:                       # type hints only: compose_sections() needs no database stack
    from sqlalchemy.orm import Session

from ml import config as ml_config

from app import __version__
from app.services import analytics, health, model_health
from app.services.pipeline import PipelineService

PROCESS_STARTED = time.time()


def model_health_for(s: Session, pipeline: PipelineService, stream: str, *, rows: list[dict] | None = None,
                     events: list[dict] | None = None, versions: list[dict] | None = None) -> dict:
    from app.services import queries   # lazy: compose_sections() stays usable without SQLAlchemy
    status = pipeline.status(stream)
    rows = queries.outcome_rows(s, stream) if rows is None else rows
    events = queries.drift_events(s, stream) if events is None else events
    versions = queries.model_versions(s, stream) if versions is None else versions
    active = next((v for v in versions if v["version"] == status["model_version"]), None)
    return model_health.compute(status=status["status"], adapting=bool(status.get("adapting")), active=active,
                                rows=rows, drift_events=events, versions=versions,
                                records_processed=int(status["records_processed"]))


def current_model(versions: list[dict], rows: list[dict], status: dict) -> dict | None:
    active = next((v for v in versions if v["version"] == status["model_version"]), None)
    if active is None:
        return None
    live = next((m for m in analytics.by_version(rows) if m["version"] == active["version"]), None)
    adaptations = [v for v in versions if v["kind"] != "initial"]
    return {
        "version": active["version"], "algorithm": active["model_type"], "kind": active["kind"],
        "trigger": active["trigger"], "detector": status["detector"], "detector_backend": status["detector_backend"],
        "accuracy": active["accuracy"], "precision": active["precision"], "recall": active["recall"],
        "f1_score": active["f1_score"], "training_records": active["training_records"],
        "last_trained_at": active.get("created_at"),
        "last_adapted_at": adaptations[-1]["created_at"] if adaptations else None,
        "live_metrics": live,
        "metric_note": "accuracy / precision / recall / F1 are out-of-fold validation metrics on the training "
                       "window; live_metrics are measured on real outcomes since deployment.",
    }


def system_monitoring(s: Session, state: Any, stream: str) -> dict:
    from app.services import queries
    pipeline: PipelineService = state.pipeline
    db_check = health.check_database(state.db)
    components = {
        "api": {"status": health.HEALTHY, "message": "Serving requests.",
                "uptime_seconds": round(time.time() - PROCESS_STARTED)},
        "database": db_check,
        "websocket": health.check_websocket(state),
        "ml_pipeline": health.check_pipeline(state),
        "model_storage": health.check_storage(state),
    }
    status = pipeline.status(stream)
    rows = queries.outcome_rows(s, stream)
    events = queries.drift_events(s, stream)
    versions = queries.model_versions(s, stream)
    metrics = queries.pipeline_metrics(s, stream)
    queue = pipeline.queue_stats()
    metrics.update(records_processed=int(status["records_processed"]), failed_jobs=int(queue.get("failed", 0)),
                   rejected_jobs=int(queue.get("rejected", 0)), queue_pending=int(queue.get("pending", 0)),
                   last_failure_at=queue.get("last_failure_at"))
    preds = pipeline.prediction_metrics(stream)
    request_metrics = getattr(state, "metrics", None)
    sampler = getattr(state, "resources", None)
    settings = getattr(state, "settings", None)
    sections = compose_sections(
        status=status, rows=rows, events=events, versions=versions, metrics=metrics, components=components,
        predictions=preds, data=queries.data_channel_counts(s),
        api=request_metrics.snapshot() if request_metrics is not None else None,
        resources=sampler.sample() if sampler is not None else None,
        environment=getattr(settings, "environment", None))
    return {
        **sections,
        "mode": stream,
        "overall": health.overall(*(c["status"] for c in components.values())),
        "components": components,
        "pipeline_metrics": metrics,
        "current_model": current_model(versions, rows, status),
        "model_health": model_health_for(s, pipeline, stream, rows=rows, events=events, versions=versions),
        "detector": {"primary": status["detector"], "status": status["status"],
                     "shadows": status["shadow_detectors"], "adapting": status.get("adapting", False)},
        "runtime": {"python": platform.python_version(), "metrics_note":
                    "failed_jobs / rejected_jobs count since this API process started; every other counter "
                    "comes from the database."},
    }


def compose_sections(*, status: dict, rows: list[dict], events: list[dict], versions: list[dict], metrics: dict,
                     components: dict, predictions: dict, data: dict, api: dict | None, resources: dict | None,
                     environment: str | None = None) -> dict:
    """The grouped view of System monitoring (application · ML · drift · data · performance · system health).

    Pure: every input is already measured (database rows, pipeline counters, health checks, process metrics).
    A value that is not measured stays None and is shown as N/A; nothing is filled in.
    """
    markers = analytics.drift_markers(rows, events, versions)
    overall = analytics.window_metrics(rows)
    recent = analytics.window_metrics(rows, ml_config.PERF_EVAL_WINDOW)
    latency = predictions["latency"]
    db, ws, api_c = components["database"], components["websocket"], components["api"]
    db_view = {"status": db["status"], "connected": db["status"] != health.ERROR, "latency_ms": db.get("latency_ms"),
               "revision": db.get("revision")}
    return {
        "application": {
            "api": {"status": api_c["status"], "uptime_seconds": api_c.get("uptime_seconds"), "version": __version__,
                    "environment": environment},
            "database": db_view,
            "websocket": {"status": ws["status"], "clients": ws.get("clients"),
                          "events_published": ws.get("events_published"), "last_event_at": ws.get("last_event_at")},
        },
        "ml": {
            "total_predictions": metrics.get("predictions_made"), "outcomes_received": metrics.get("outcomes_received"),
            "prediction_success_rate": predictions["success_rate"], "predictions_succeeded": predictions["succeeded"],
            "predictions_failed": predictions["failed"],
            "prediction_error_rate": overall["error_rate"], "prediction_error_rate_recent": recent["error_rate"],
            "avg_latency_ms": latency["avg_ms"], "p95_latency_ms": latency["p95_ms"], "latency_samples": latency["n"],
            "current_model_version": status["model_version"], "adaptations": metrics.get("adaptations"),
            "drift_events": metrics.get("drift_events"), "models_created": metrics.get("models_created"),
            "counters_since": predictions["since"],
            "definitions": {
                "prediction_success_rate": "Predictions completed without an error / predictions attempted "
                                           "(since this API process started)",
                "prediction_error_rate": "Wrong predictions / labeled outcomes (stored data)",
                "latency": "Model inference time per prediction (last 500 in this process)"},
        },
        "drift": {
            "total_drift_events": len(events), "confirmed_drifts": len(events), "warnings": len(markers["warnings"]),
            "adapted": sum(1 for e in events if e.get("new_model_version")),
            "failed_adaptations": metrics.get("failed_adaptations"), "last_drift_at": metrics.get("last_drift_at"),
            "last_warning_step": markers["warnings"][-1]["step"] if markers["warnings"] else None,
            "current_detector": status["detector"], "current_status": status["status"],
            "adapting": bool(status.get("adapting")), "warning_start": status.get("warning_start"),
            "note": "Warnings = times the detector entered the warning zone; confirmed drifts = detector DRIFT "
                    "(each one triggers adaptation).",
        },
        "data": data,
        "performance": {"recent": recent, "overall": overall, "recent_window": ml_config.PERF_EVAL_WINDOW},
        "system_health": {"resources": resources, "api": api, "database": db_view},
    }
