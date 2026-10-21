"""Live predictions, prediction history and late-arriving outcomes."""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.common import audit_async, enforce_prediction_rate
from app.auth.dependencies import get_current_user, get_db, get_pipeline, is_staff
from app.database.models import User
from app.database.schemas import (Category, OutcomeInput, OutcomeOut, PredictionInput, PredictionOut,
                                  PredictionPage, PredictResponse, Stream, page_meta)
from app.errors import NotFoundError, PermissionDeniedError
from app.services import queries
from app.services.pipeline import LIVE, PipelineService

router = APIRouter(prefix="/api", tags=["Predictions"])


@router.post("/predict", response_model=PredictResponse, status_code=status.HTTP_201_CREATED,
             summary="Predict the next clothing category (live stream)")
async def predict(body: PredictionInput, request: Request, user: User = Depends(get_current_user),
                  pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    """Stores the prediction with its explanation (which inputs drove it). If `actual_category` is
    included, it is recorded as the outcome immediately and fed to the drift detector; otherwise
    send it later with `POST /api/predictions/{id}/outcome`."""
    enforce_prediction_rate(request, user)
    res = await pipeline.predict(user_id=user.id, record=body.to_record(), actual=body.actual_category)
    drift_status = pipeline.status(LIVE)["status"]
    p, out = res["prediction"], res["outcome"]
    if out is None:
        message = (f"Predicted {p['predicted_category']} with {p['confidence']:.0%} confidence using "
                   f"{p['model_version']}. Send the actual category later to update drift monitoring.")
    else:
        message = (f"Predicted {p['predicted_category']}; actual {out['actual_category']} "
                   f"({'correct' if out['is_correct'] else 'wrong'}). Detector status: {out['status']}.")
        if out["new_model_version"]:
            message += f" The model adapted to {out['new_model_version']}."
    await audit_async(request, "prediction.created", user=user, resource="prediction", resource_id=p["id"],
                      stream=LIVE, details={"predicted": p["predicted_category"], "model_version": p["model_version"],
                                            "with_outcome": out is not None})
    return {"prediction": p, "outcome": out, "explanation": res.get("explanation"), "drift_status": drift_status,
            "message": message}


@router.get("/predictions", response_model=PredictionPage, summary="Prediction history (search & filter)")
def list_predictions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
    stream: Stream = Query("live", description="Analysts/admins may view 'simulation'"),
    predicted: Category | None = None, actual: Category | None = None,
    correct: bool | None = None, model_version: str | None = Query(None, max_length=20),
    labeled: bool | None = Query(None, description="true = has actual outcome, false = awaiting outcome"),
    source: str | None = Query(None, pattern="^(api|event|upload|simulation)$"),
    search: str | None = Query(None, max_length=40, description="Customer ID, prediction ID or event ID"),
    date_from: datetime | None = None, date_to: datetime | None = None,
    sort: str = Query("newest", pattern="^(newest|oldest|confidence)$"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
) -> dict:
    staff = is_staff(user)
    if stream == "simulation" and not staff:
        raise PermissionDeniedError("Simulation data is available to analysts and admins.")
    items, total = queries.list_predictions(
        db, page=page, page_size=page_size, sort=sort, owner_id=None if staff else user.id, stream=stream,
        predicted=predicted, actual=actual, correct=correct, model_version=model_version, labeled=labeled,
        search=search, date_from=date_from, date_to=date_to, source=source)
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/predictions/{prediction_id}", response_model=PredictionOut, summary="One prediction")
def get_prediction(prediction_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    p = queries.get_prediction(db, prediction_id)
    if p is None or (not is_staff(user) and p["user_id"] != user.id):
        raise NotFoundError("Prediction not found.")      # same answer for "not yours" (no ID probing)
    return p


@router.post("/predictions/{prediction_id}/outcome", response_model=OutcomeOut,
             summary="Record the actual category for an earlier prediction")
async def record_outcome(prediction_id: int, body: OutcomeInput, request: Request,
                         user: User = Depends(get_current_user),
                         pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    p = await asyncio.to_thread(pipeline.repo.get_prediction, prediction_id)
    if p is None or (user.role != "admin" and p["user_id"] != user.id):
        raise NotFoundError("Prediction not found.")
    out = await pipeline.record_outcome(prediction_id, body.actual_category)
    await audit_async(request, "prediction.outcome_recorded", user=user, resource="prediction",
                      resource_id=prediction_id, stream=LIVE, severity="critical" if out["drift_detected"] else "info",
                      details={"actual": out["actual_category"], "is_correct": out["is_correct"],
                               "status": out["status"], "new_model_version": out["new_model_version"]})
    return out
