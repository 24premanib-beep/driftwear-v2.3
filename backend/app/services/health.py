"""
Component health checks used by /health, /health/db, /health/ml, /health/websocket
and the System monitoring page.

Each check inspects the real component (a database round trip, the pipeline
worker, the event-bus task, the active model file in storage) and returns

    {"status": "healthy" | "warning" | "error", "message": "...", ...details}

Messages are written for operators and never contain connection strings,
file paths or exception text.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

HEALTHY, WARNING, ERROR = "healthy", "warning", "error"
# Alembic head this code expects; tests/test_migrations.py asserts it matches the migration files.
EXPECTED_DB_REVISION = "0003_live_data_rollback"
RECENT_FAILURE = timedelta(minutes=10)
QUEUE_BACKLOG_WARNING = 100


def overall(*statuses: str) -> str:
    if ERROR in statuses:
        return ERROR
    if WARNING in statuses:
        return WARNING
    return HEALTHY


def check_database(db) -> dict:
    start = time.perf_counter()
    try:
        db.ping()
    except Exception:  # noqa: BLE001
        return {"status": ERROR, "message": "The database is not reachable.", "latency_ms": None,
                "revision": None, "expected_revision": EXPECTED_DB_REVISION}
    latency = round((time.perf_counter() - start) * 1000, 1)
    revision = db.migration_revision()
    out = {"latency_ms": latency, "dialect": db.dialect, "revision": revision,
           "expected_revision": EXPECTED_DB_REVISION}
    if revision is None:
        return {**out, "status": HEALTHY if db.dialect == "sqlite" else WARNING,
                "message": "Connected. No Alembic revision recorded (tables created directly)."}
    if revision != EXPECTED_DB_REVISION:
        return {**out, "status": WARNING, "message": f"Connected, but migrations are not at head "
                                                     f"({revision}; expected {EXPECTED_DB_REVISION})."}
    if latency > 500:
        return {**out, "status": WARNING, "message": "Connected, but responses are slow."}
    return {**out, "status": HEALTHY, "message": "Connected; schema is up to date."}


def _recent(ts: str | None, now: datetime) -> bool:
    if not ts:
        return False
    try:
        return now - datetime.fromisoformat(ts) < RECENT_FAILURE
    except ValueError:
        return False


def check_pipeline(state: Any) -> dict:
    pipeline_state = getattr(state, "pipeline_state", "not_started")
    pipeline = getattr(state, "pipeline", None)
    base = {"state": pipeline_state, "streams": {}, "queue": {}}
    if pipeline_state == "standby":
        return {**base, "status": WARNING,
                "message": "Standby: another API process holds the pipeline lock. Reads keep working."}
    if pipeline_state == "starting":
        return {**base, "status": WARNING, "message": "The pipeline is loading its models."}
    if pipeline is None or pipeline_state != "ready" or not pipeline.ready:
        return {**base, "status": ERROR, "message": "The ML pipeline is not running."}
    streams = {}
    for name, rt in pipeline.runtimes.items():
        streams[name] = {"available": name not in pipeline._broken, "model_version": rt.engine.version,
                         "detector": rt.engine.detector_name, "status": rt.engine.status,
                         "records_processed": rt.engine.next_step}
    queue = pipeline.queue_stats()
    base.update(streams=streams, queue=queue)
    now = datetime.now(timezone.utc)
    if pipeline._broken:
        return {**base, "status": ERROR,
                "message": f"Stream(s) unavailable: {', '.join(sorted(pipeline._broken))}."}
    if _recent(queue.get("last_failure_at"), now):
        return {**base, "status": WARNING, "message": f"A pipeline job failed recently ({queue.get('last_failure')})."}
    if queue.get("pending", 0) > QUEUE_BACKLOG_WARNING:
        return {**base, "status": WARNING, "message": f"{queue['pending']} jobs are waiting in the queue."}
    return {**base, "status": HEALTHY, "message": "Models loaded; the worker is processing jobs."}


def check_websocket(state: Any) -> dict:
    bus = getattr(state, "bus", None)
    manager = getattr(state, "ws_manager", None)
    clients = manager.count if manager is not None else 0
    if bus is None or not bus.running:
        return {"status": ERROR, "message": "The real-time event bus is not running.", "clients": clients,
                "events_published": getattr(bus, "published", 0), "last_event_at": getattr(bus, "last_event_at", None)}
    backlog = bus.backlog
    return {"status": WARNING if backlog > 500 else HEALTHY,
            "message": f"Event bus running; {clients} client(s) connected." if backlog <= 500
            else f"Event delivery is behind ({backlog} events queued).",
            "clients": clients, "events_published": bus.published, "last_event_at": bus.last_event_at,
            "backlog": backlog}


def check_storage(state: Any) -> dict:
    storage = getattr(state, "storage", None)
    pipeline = getattr(state, "pipeline", None)
    if storage is None:
        return {"status": ERROR, "message": "Model storage is not configured.", "active_models": {}}
    kind = storage.describe().split(":", 1)[0]
    if pipeline is None or not pipeline.ready:
        return {"status": WARNING, "message": "Waiting for the pipeline to load models.", "backend": kind,
                "active_models": {}}
    found = {}
    try:
        for name, rt in pipeline.runtimes.items():
            row = pipeline.repo.get_version(name, rt.engine.version)
            found[name] = bool(row) and storage.exists(row["model_path"])
    except Exception:  # noqa: BLE001
        return {"status": ERROR, "message": "Model storage could not be read.", "backend": kind,
                "active_models": found}
    missing = [n for n, ok in found.items() if not ok]
    if missing:
        return {"status": ERROR, "message": f"Active model file missing for: {', '.join(missing)}.",
                "backend": kind, "active_models": found}
    return {"status": HEALTHY, "message": "Active model files are present and readable.", "backend": kind,
            "active_models": found}
