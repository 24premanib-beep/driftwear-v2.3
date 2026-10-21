"""
Audit log: who did what, when, to which resource — plus what the system did on its own.

Two sources write to the `audit_logs` table:

1. API routes record user actions explicitly (sign-in, uploads, predictions,
   detector changes, retrain requests, activation / rollback, simulation
   controls, user administration), with the user id and client IP.
2. `AuditEventRecorder` subscribes to the real-time EventBus and records the
   events the PIPELINE produces by itself (drift detected, retraining started /
   completed / failed, model created, pipeline errors, detector warnings). Those
   events already exist for the WebSocket, so auditing them needs no change to
   the ML loop.

Writing an audit row must never break the action being audited: failures are
logged and swallowed. Details are sanitised (no passwords, tokens or secrets;
long strings truncated) before they are stored.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Protocol

from app.services import events as ev
from app.services.events import Event

log = logging.getLogger(__name__)

SEVERITIES = ("info", "warning", "critical")
_SENSITIVE = re.compile(r"pass(word)?|token|secret|authorization|api[_-]?key|credential|hash", re.I)
_MAX_STR = 300

# event name -> (action, resource, severity) for events the pipeline emits without a user request
SYSTEM_EVENTS = {
    ev.DRIFT_DETECTED: ("drift.detected", "drift_event", "critical"),
    ev.WARNING_DETECTED: ("drift.warning", "detector", "warning"),
    ev.ADAPTATION_STARTED: ("model.retraining_started", "model_version", "info"),
    ev.ADAPTATION_COMPLETED: ("model.retraining_completed", "model_version", "info"),
    ev.ADAPTATION_FAILED: ("model.adaptation_failed", "model_version", "critical"),
    ev.MODEL_VERSION_CREATED: ("model.created", "model_version", "info"),
    ev.PIPELINE_ERROR: ("pipeline.error", "pipeline", "critical"),
}
_DETAIL_KEYS = ("step", "from_version", "to_version", "version", "detector", "severity", "kind", "trigger",
                "error_rate", "records_used", "change_point_step", "detection_delay", "window_start", "window_end",
                "accuracy_stable", "accuracy_degraded", "status", "previous_status", "drift_event_id")


def sanitize(value: Any, depth: int = 0) -> Any:
    """Copy of `value` that is safe to store: sensitive keys removed, strings and lists bounded."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        return {str(k)[:60]: sanitize(v, depth + 1) for k, v in list(value.items())[:50]
                if not _SENSITIVE.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STR]


class AuditSink(Protocol):
    def record(self, action: str, *, resource: str, resource_id: Any = None, user_id: int | None = None,
               severity: str = "info", stream: str | None = None, ip: str | None = None,
               details: dict | None = None) -> None: ...


class AuditService:
    """Writes audit rows to the database (one short transaction per row)."""

    def __init__(self, db):
        self.db = db

    def record(self, action: str, *, resource: str, resource_id: Any = None, user_id: int | None = None,
               severity: str = "info", stream: str | None = None, ip: str | None = None,
               details: dict | None = None) -> None:
        from app.database.models import AuditLog  # lazy: keeps this module importable without SQLAlchemy
        try:
            with self.db.transaction() as s:
                s.add(AuditLog(
                    user_id=user_id, action=action[:60], resource=resource[:40],
                    resource_id=None if resource_id is None else str(resource_id)[:64],
                    severity=severity if severity in SEVERITIES else "info",
                    stream=stream, ip_address=(ip or None) and ip[:45], details=sanitize(details or {})))
        except Exception:  # noqa: BLE001 - auditing must never break the audited action
            log.exception("Could not write audit log entry '%s'", action)

    async def arecord(self, action: str, **kw: Any) -> None:
        await asyncio.to_thread(self.record, action, **kw)


class AuditEventRecorder:
    """EventBus subscriber: stores the pipeline's own (system) events in the audit log."""

    def __init__(self, sink: AuditSink):
        self.sink = sink

    @staticmethod
    def entry(event: Event) -> dict | None:
        mapping = SYSTEM_EVENTS.get(event.name)
        if mapping is None:
            return None
        action, resource, severity = mapping
        p = event.payload
        data = p.get("data") or {}
        if action.startswith("model."):
            resource_id = data.get("to_version") or data.get("version") or p.get("model_version")
        elif action == "drift.detected":
            resource_id = data.get("event_id")
        else:
            resource_id = p.get("model_version")
        details = {k: data[k] for k in _DETAIL_KEYS if k in data}
        details["message"] = p.get("message")
        if p.get("detector"):
            details.setdefault("detector", p["detector"])
        return {"action": action, "resource": resource, "resource_id": resource_id, "severity": severity,
                "stream": p.get("stream"), "user_id": None, "details": details}      # None = "System"

    async def __call__(self, event: Event) -> None:
        e = self.entry(event)
        if e is None:
            return
        action = e.pop("action")
        await asyncio.to_thread(self.sink.record, action, **e)
