"""
Live data pathway: real purchase events from any external application.

    event (JSON) → DATA VALIDATION (ml.validation.validate_event: same rules as CSV uploads)
         ├─ invalid → stored in rejected_events with its errors → 422; it never reaches the model
         └─ valid   → feature record → PipelineService.predict (features → model → prediction stored with
                      model version and timestamps) → optional immediate outcome → error → drift detector
    later: outcome (event_id or prediction_id) → error → detector → adaptation if drift is confirmed

Single events, batches (valid items are processed, invalid items rejected individually) and batches of late
outcomes all go through the one PipelineService, so there is still exactly one concept-drift loop. No data is
generated here: everything processed was sent by a caller.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any, Protocol

from ml.validation import EventCheck, Issue, event_to_record, validate_event, validate_outcome

from app.errors import AppError, ConflictError, ValidationFailedError
from app.services.audit import sanitize
from app.services.pipeline import LIVE, PipelineService

log = logging.getLogger(__name__)


class RejectionStore(Protocol):
    def record(self, rows: list[dict]) -> None: ...


class SqlRejectionStore:
    """Writes rejected events to the rejected_events table. Never raises: the caller still gets its 422."""

    def __init__(self, db):
        self.db = db

    def record(self, rows: list[dict]) -> None:
        if not rows:
            return
        from app.database.models import RejectedEvent   # lazy: keeps this module importable without SQLAlchemy
        try:
            with self.db.transaction() as s:
                s.add_all([RejectedEvent(**r) for r in rows])
        except Exception:  # noqa: BLE001
            log.exception("Could not store %d rejected event(s)", len(rows))


class EventRejected(ValidationFailedError):
    """422: the event failed validation. details = [{field, value, message}]."""


def rejection_row(details: list[dict], payload: Any, *, user_id: int | None, source: str,
                  batch_index: int | None = None) -> dict:
    eid = payload.get("event_id") if isinstance(payload, dict) else None
    return {"user_id": user_id, "stream": LIVE, "source": source,
            "event_id": eid[:64] if isinstance(eid, str) else None, "batch_index": batch_index,
            "error_count": len(details), "errors": sanitize(details[:50]),
            "payload": sanitize(payload) if isinstance(payload, dict) else None}


def rejection_message(details: list[dict]) -> str:
    first = details[0]
    head = f"{first['field']}: {first['message']}" if first.get("field") else first["message"]
    more = len(details) - 1
    return f"Event rejected: {head}" + (f" (+{more} more problem{'s' if more > 1 else ''})" if more else "")


def _iso(v) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _outcome_brief(out: dict | None) -> dict | None:
    if out is None:
        return None
    brief = {k: out[k] for k in ("actual_category", "is_correct", "drift_detected", "new_model_version",
                                 "scored_version", "rescored")}
    brief["detector_status"] = out["status"]          # not "status": batch items use that key for their own result
    return brief


class IngestionService:
    def __init__(self, pipeline: PipelineService, rejections: RejectionStore, *, max_batch: int = 100):
        self.pipeline = pipeline
        self.rejections = rejections
        self.max_batch = max(1, int(max_batch))

    async def _reject(self, rows: list[dict]) -> None:
        if rows:
            await asyncio.to_thread(self.rejections.record, rows)

    # ------------------------------------------------------------------ one event
    async def ingest(self, payload: Any, *, user_id: int | None, source: str = "single") -> dict:
        """Validate → predict → store. Raises EventRejected (422) after storing the rejection."""
        check = validate_event(payload)
        if not check.ok:
            details = check.details()
            await self._reject([rejection_row(details, payload, user_id=user_id, source=source)])
            raise EventRejected(rejection_message(details), details=details)
        record, actual, event_id = event_to_record(check.values)
        res = await self.pipeline.predict(user_id=user_id, record=record, actual=actual, source="event",
                                          event_id=event_id)
        res["event_id"] = event_id
        res["validation"] = {"passed": True, "warnings": check.warning_details()}
        return res

    # ------------------------------------------------------------------ batches
    def check_size(self, items: Any, what: str) -> None:
        if not isinstance(items, list) or not items:
            raise ValidationFailedError(f"Send a non-empty JSON array of {what}.")
        if len(items) > self.max_batch:
            raise ValidationFailedError(f"A batch can contain at most {self.max_batch} {what}; got {len(items)}.",
                                        details={"max_batch": self.max_batch, "received": len(items)})

    async def ingest_batch(self, items: Any, *, user_id: int | None) -> dict:
        """Every item is validated on its own. Invalid items are rejected (and stored); valid ones are predicted
        in order. A repeated event_id (in the batch or already ingested) is reported, never predicted twice.
        If the pipeline becomes unavailable mid-batch, the remaining items are reported as not processed."""
        self.check_size(items, "events")
        checks: list[EventCheck] = [validate_event(it) for it in items]
        seen: dict[str, int] = {}
        for i, c in enumerate(checks):
            eid = c.values.get("event_id") if c.ok else None
            if eid in seen:
                c.errors.append(Issue(None, "event_id", eid, f"Duplicate of item {seen[eid]} in this batch."))
            elif eid:
                seen[eid] = i
        await self._reject([rejection_row(c.details(), items[i], user_id=user_id, source="batch", batch_index=i)
                            for i, c in enumerate(checks) if not c.ok])
        results, stop = [], None
        for i, c in enumerate(checks):
            if not c.ok:
                results.append({"index": i, "status": "rejected", "event_id": items[i].get("event_id")
                                if isinstance(items[i], dict) else None, "errors": c.details()})
                continue
            record, actual, eid = event_to_record(c.values)
            if stop:
                results.append({"index": i, "status": "not_processed", "event_id": eid, "message": stop})
                continue
            try:
                res = await self.pipeline.predict(user_id=user_id, record=record, actual=actual, source="event",
                                                  event_id=eid)
            except ConflictError as exc:
                results.append({"index": i, "status": "duplicate", "event_id": eid, "message": exc.message,
                                "prediction_id": (exc.details or {}).get("prediction_id")})
                continue
            except AppError as exc:
                results.append({"index": i, "status": "failed", "event_id": eid, "message": exc.message})
                if exc.status_code >= 500:
                    stop = "Not processed: the pipeline became unavailable during this batch. Send it again."
                continue
            p = res["prediction"]
            results.append({"index": i, "status": "accepted", "event_id": eid, "prediction_id": p["id"],
                            "predicted_category": p["predicted_category"], "confidence": p["confidence"],
                            "model_version": p["model_version"], "created_at": _iso(p.get("created_at")),
                            "warnings": c.warning_details(), "outcome": _outcome_brief(res["outcome"])})
        counts = Counter(r["status"] for r in results)
        return {"received": len(items), "accepted": counts["accepted"], "rejected": counts["rejected"],
                "duplicates": counts["duplicate"], "failed": counts["failed"],
                "not_processed": counts["not_processed"], "results": results}

    async def record_outcomes(self, items: Any, *, user_id: int, is_admin: bool) -> dict:
        """Late outcomes in bulk (e.g. a nightly fulfilment export). Same ownership rule as one outcome: users
        label their own events, admins any live event; someone else's event is reported as not found."""
        self.check_size(items, "outcomes")
        repo = self.pipeline.repo
        results, stop = [], None
        for i, item in enumerate(items):
            c = validate_outcome(item)
            if not c.ok:
                results.append({"index": i, "status": "rejected", "errors": c.details()})
                continue
            if stop:
                results.append({"index": i, "status": "not_processed", "message": stop})
                continue
            v = c.values
            p = await asyncio.to_thread(repo.find_prediction_by_event, LIVE, v["event_id"]) if "event_id" in v \
                else await asyncio.to_thread(repo.get_prediction, v["prediction_id"])
            if p is None or (not is_admin and p.get("user_id") != user_id):
                results.append({"index": i, "status": "not_found", "event_id": v.get("event_id"),
                                "prediction_id": v.get("prediction_id"), "message": "Event not found."})
                continue
            try:
                out = await self.pipeline.record_outcome(p["id"], v["actual_category"])
            except ConflictError as exc:
                results.append({"index": i, "status": "conflict", "prediction_id": p["id"],
                                "event_id": p.get("event_id"), "message": exc.message})
                continue
            except AppError as exc:
                results.append({"index": i, "status": "failed", "prediction_id": p["id"], "message": exc.message})
                if exc.status_code >= 500:
                    stop = "Not processed: the pipeline became unavailable during this batch. Send it again."
                continue
            results.append({"index": i, "status": "recorded", "prediction_id": p["id"], "event_id": p.get("event_id"),
                            "model_version": p.get("model_version"), **_outcome_brief(out)})
        counts = Counter(r["status"] for r in results)
        return {"received": len(items), "recorded": counts["recorded"], "rejected": counts["rejected"],
                "not_found": counts["not_found"], "conflicts": counts["conflict"], "failed": counts["failed"],
                "not_processed": counts["not_processed"],
                "drift_detected": sum(1 for r in results if r.get("drift_detected")),
                "new_model_versions": [r["new_model_version"] for r in results if r.get("new_model_version")],
                "results": results}
