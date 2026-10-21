"""
Live data pathway: real purchase events from any external application (shop backend, POS, message consumer).

    POST /api/events             one event (same as /api/events/purchase)
    POST /api/events/purchase    event → DATA VALIDATION → features → prediction → stored with model version
                                 and timestamps → (outcome if already known) → WebSocket
    POST /api/events/batch       up to EVENT_BATCH_MAX events; each one validated and processed on its own
    POST /api/events/outcome     the actual category for one event (event_id or prediction_id) → error → detector
    POST /api/events/outcomes    many late outcomes at once
    GET  /api/events/summary     received / labeled / awaiting outcome / rejected
    GET  /api/events/rejections  rejected events with their validation errors (analyst, admin)

Validation (app/services/ingestion.py, rules in ml/validation.py shared with CSV uploads) runs before the
pipeline: a rejected event is stored with its errors and never reaches the model. Accepted events reuse the
same PipelineService as the prediction form, CSV uploads and the simulation, so there is exactly one
implementation of the concept-drift loop. The response's `pipeline` trace shows which stages ran.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.common import audit_async, enforce_prediction_rate
from app.auth.dependencies import get_current_user, get_db, get_pipeline, is_staff, require_staff
from app.database.models import User
from app.database.schemas import (EventIngestResponse, EventOutcomeInput, EventOutcomeResponse, PurchaseEvent,
                                  page_meta)
from app.errors import NotFoundError, ServiceUnavailableError, ValidationFailedError
from app.services import queries
from app.services.ingestion import IngestionService
from app.services.pipeline import LIVE, PipelineService

router = APIRouter(prefix="/api/events", tags=["Real-time events"])

_EVENT_SCHEMA = PurchaseEvent.model_json_schema()
_OUTCOME_SCHEMA = EventOutcomeInput.model_json_schema()


def _body(schema: dict) -> dict:
    """Request body documentation for routes that read and validate the JSON themselves."""
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}


def get_ingestion(request: Request) -> IngestionService:
    svc = getattr(request.app.state, "ingestion", None)
    if svc is None:
        raise ServiceUnavailableError("The ingestion service is starting up. Please try again in a moment.")
    return svc


async def _read_json(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:          # not JSON / not UTF-8: validation then reports "must be a JSON object"
        return None


def _outcome_stages(out: dict, detector: str) -> list[dict]:
    error = 0 if out["is_correct"] else 1
    stages = [
        {"stage": "outcome", "status": "done", "detail": f"Actual category: {out['actual_category']}"},
        {"stage": "error", "status": "done",
         "detail": f"Error = {error} ({'correct' if error == 0 else 'wrong'})"
                   + (f"; re-scored by {out['scored_version']} for monitoring" if out["rescored"] else "")},
        {"stage": "drift_check", "status": "done",
         "detail": f"{detector}: {out['previous_status']} → {out['status']}"},
    ]
    if out["new_model_version"]:
        stages.append({"stage": "adaptation", "status": "done",
                       "detail": f"Concept drift confirmed; {out['new_model_version']} trained and activated"})
    elif out["adaptation_error"]:
        stages.append({"stage": "adaptation", "status": "failed", "detail": out["adaptation_error"]})
    else:
        stages.append({"stage": "adaptation", "status": "skipped", "detail": "Not needed: no drift confirmed"})
    return stages


def _validation_stage(validation: dict | None) -> dict:
    warnings = (validation or {}).get("warnings") or []
    detail = "Required fields, types, ranges (no negatives), categories, seasons, preferences and dates checked"
    if warnings:
        detail += f"; {len(warnings)} warning(s): " + "; ".join(f"{w['field']}: {w['message']}" for w in warnings[:2])
    return {"stage": "validated", "status": "done", "detail": detail}


def _ingest_stages(p: dict, out: dict | None, detector: str, validation: dict | None = None) -> list[dict]:
    stages = [
        _validation_stage(validation),
        {"stage": "stored", "status": "done", "detail": f"Stored as prediction #{p['id']}"
                                                       + (f" (event {p['event_id']})" if p.get("event_id") else "")},
        {"stage": "features", "status": "done", "detail": "Final price and cyclical month encoding derived"},
        {"stage": "prediction", "status": "done",
         "detail": f"{p['predicted_category']} ({p['confidence']:.0%}) by {p['model_version']}"},
    ]
    if out is None:
        stages += [
            {"stage": "outcome", "status": "pending", "detail": "Send the actual category to POST /api/events/outcome"},
            {"stage": "error", "status": "pending", "detail": "Computed when the outcome arrives"},
            {"stage": "drift_check", "status": "pending", "detail": "The detector only reads labeled outcomes"},
            {"stage": "adaptation", "status": "skipped", "detail": "No outcome yet"},
        ]
    else:
        stages += _outcome_stages(out, detector)
    stages.append({"stage": "notified", "status": "done", "detail": "Pushed to connected clients over WebSocket"})
    return stages


@router.post("", response_model=EventIngestResponse, status_code=status.HTTP_201_CREATED,
             summary="Ingest one live purchase event (same as /api/events/purchase)", openapi_extra=_body(_EVENT_SCHEMA))
@router.post("/purchase", response_model=EventIngestResponse, status_code=status.HTTP_201_CREATED,
             summary="Ingest a real-time purchase event (predict now, learn when the outcome arrives)",
             openapi_extra=_body(_EVENT_SCHEMA))
async def ingest_purchase(request: Request, user: User = Depends(get_current_user),
                          pipeline: PipelineService = Depends(get_pipeline),
                          ingestion: IngestionService = Depends(get_ingestion)) -> dict:
    """Validates the event (422 with every problem listed; the rejection is stored), stores it with its
    prediction, model version and explanation, and announces it over WebSocket. Include `actual_category` if
    it is already known; otherwise send it later to `POST /api/events/outcome`. Re-sending an `event_id`
    returns **409** (idempotent ingestion)."""
    enforce_prediction_rate(request, user)
    received_at = datetime.now(timezone.utc)
    res = await ingestion.ingest(await _read_json(request), user_id=user.id)
    p, out = res["prediction"], res["outcome"]
    status_info = pipeline.status(LIVE)
    await audit_async(request, "event.ingested", user=user, resource="prediction", resource_id=p["id"], stream=LIVE,
                      details={"event_id": res["event_id"], "predicted": p["predicted_category"],
                               "model_version": p["model_version"], "with_outcome": out is not None})
    message = f"Event stored and predicted as {p['predicted_category']} ({p['confidence']:.0%})."
    if out is not None:
        message += f" Outcome recorded; detector status {out['status']}."
        if out["new_model_version"]:
            message += f" Concept drift confirmed: the model adapted to {out['new_model_version']}."
    return {"event_id": res["event_id"], "prediction": p, "explanation": res.get("explanation"), "outcome": out,
            "drift_status": status_info["status"], "validation": res["validation"], "received_at": received_at,
            "pipeline": _ingest_stages(p, out, status_info["detector"], res["validation"]), "message": message}


@router.post("/batch", summary="Ingest several live purchase events (each validated and processed on its own)",
             openapi_extra=_body({"type": "object", "required": ["events"], "additionalProperties": False,
                                  "properties": {"events": {"type": "array", "items": _EVENT_SCHEMA}}}))
async def ingest_batch(request: Request, user: User = Depends(get_current_user),
                       ingestion: IngestionService = Depends(get_ingestion)) -> dict:
    """Body: `{"events": [...]}` (at most EVENT_BATCH_MAX). Valid events are predicted in order; invalid ones are
    rejected individually (and stored with their errors); duplicate event ids are reported. Returns per-item
    results. 422 only if no event in the batch passed validation."""
    body = await _read_json(request)
    if not isinstance(body, dict) or set(body) != {"events"}:
        raise ValidationFailedError('Send {"events": [ ... ]} with the purchase events to ingest.')
    ingestion.check_size(body["events"], "events")
    enforce_prediction_rate(request, user, n=len(body["events"]))
    res = await ingestion.ingest_batch(body["events"], user_id=user.id)
    await audit_async(request, "event.batch_ingested", user=user, resource="event_batch", stream=LIVE,
                      severity="warning" if res["rejected"] or res["failed"] else "info",
                      details={k: res[k] for k in ("received", "accepted", "rejected", "duplicates", "failed",
                                                   "not_processed")})
    if res["accepted"] == 0 and res["rejected"] and not res["duplicates"]:
        raise ValidationFailedError(f"Batch rejected: none of the {res['received']} events passed validation.",
                                    details=res)
    res["message"] = (f"{res['accepted']} of {res['received']} events accepted"
                      + (f"; {res['rejected']} rejected by validation" if res["rejected"] else "")
                      + (f"; {res['duplicates']} duplicates" if res["duplicates"] else "")
                      + (f"; {res['failed'] + res['not_processed']} not processed" if res["failed"] or res["not_processed"] else "")
                      + ".")
    return res


@router.post("/outcome", response_model=EventOutcomeResponse,
             summary="Report the actual category for an ingested event (feeds the drift detector)")
async def event_outcome(body: EventOutcomeInput, request: Request, user: User = Depends(get_current_user),
                        pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    if body.event_id is not None:
        p = await asyncio.to_thread(pipeline.repo.find_prediction_by_event, LIVE, body.event_id)
    else:
        p = await asyncio.to_thread(pipeline.repo.get_prediction, body.prediction_id)
    if p is None or (user.role != "admin" and p["user_id"] != user.id):
        raise NotFoundError("Event not found.")            # same answer for "not yours" (no id probing)
    out = await pipeline.record_outcome(p["id"], body.actual_category)
    detector = pipeline.status(LIVE)["detector"]
    await audit_async(request, "prediction.outcome_recorded", user=user, resource="prediction", resource_id=p["id"],
                      stream=LIVE, severity="critical" if out["drift_detected"] else "info",
                      details={"event_id": p.get("event_id"), "actual": out["actual_category"],
                               "is_correct": out["is_correct"], "status": out["status"],
                               "new_model_version": out["new_model_version"]})
    message = f"Outcome recorded ({'correct' if out['is_correct'] else 'wrong'}). Detector status: {out['status']}."
    if out["new_model_version"]:
        message += f" Concept drift confirmed: the model adapted to {out['new_model_version']}."
    return {"event_id": p.get("event_id"), "prediction_id": p["id"], "outcome": out,
            "pipeline": _outcome_stages(out, detector), "message": message}


@router.post("/outcomes", summary="Report many late outcomes at once (each one feeds the drift detector)",
             openapi_extra=_body({"type": "object", "required": ["outcomes"], "additionalProperties": False,
                                  "properties": {"outcomes": {"type": "array", "items": _OUTCOME_SCHEMA}}}))
async def event_outcomes(request: Request, user: User = Depends(get_current_user),
                         ingestion: IngestionService = Depends(get_ingestion)) -> dict:
    body = await _read_json(request)
    if not isinstance(body, dict) or set(body) != {"outcomes"}:
        raise ValidationFailedError('Send {"outcomes": [{"event_id": "...", "actual_category": "..."}, ...]}.')
    res = await ingestion.record_outcomes(body["outcomes"], user_id=user.id, is_admin=user.role == "admin")
    await audit_async(request, "prediction.outcomes_recorded", user=user, resource="event_batch", stream=LIVE,
                      severity="critical" if res["drift_detected"] else "info",
                      details={k: res[k] for k in ("received", "recorded", "rejected", "not_found", "conflicts",
                                                   "failed", "drift_detected", "new_model_versions")})
    return res


@router.get("/summary", summary="Live events: received, labeled, awaiting outcome, rejected (own for users)")
def events_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return queries.event_summary(db, owner_id=None if is_staff(user) else user.id)


@router.get("/rejections", summary="Rejected live events with their validation errors (analyst, admin)")
def rejections(db: Session = Depends(get_db), _: User = Depends(require_staff),
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict:
    items, total = queries.list_rejections(db, page=page, page_size=page_size)
    return {"items": items, **page_meta(total, page, page_size)}
