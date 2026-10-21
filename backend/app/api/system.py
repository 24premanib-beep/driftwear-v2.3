"""
System endpoints: health checks, vocabulary, and the System monitoring view.

Health endpoints exist at the root (/health, /health/db, /health/ml, /health/websocket) for
load balancers and container checks, and under /api/health/* so they also work through the
frontend's nginx proxy, which only forwards /api. They need no authentication and return
503 when the component is in error, 200 otherwise (including "warning").
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import __version__
from app.auth.dependencies import get_db, get_pipeline, require_staff
from app.database.models import User
from app.database.schemas import Stream
from app.services import health, monitoring
from app.services.pipeline import PipelineService

router = APIRouter(tags=["System"])


def _reply(body: dict) -> JSONResponse:
    return JSONResponse(body, status_code=503 if body.get("status") == health.ERROR else 200)


@router.get("/health", summary="Liveness and readiness of the whole service (no authentication)")
@router.get("/api/health", summary="Same as /health (reachable through the frontend proxy)")
async def health_all(request: Request) -> JSONResponse:
    state = request.app.state
    db = await asyncio.to_thread(health.check_database, state.db)
    ml = await asyncio.to_thread(health.check_pipeline, state)
    ws = health.check_websocket(state)
    storage = await asyncio.to_thread(health.check_storage, state)
    pipeline_state = getattr(state, "pipeline_state", "not_started")
    ready = db["status"] != health.ERROR and pipeline_state in ("ready", "standby", "starting")
    body = {"status": "ok" if ready else "degraded", "version": __version__,
            "database": db["status"] != health.ERROR, "pipeline": pipeline_state,
            "simulation_enabled": state.settings.simulation_enabled, "websocket_clients": ws.get("clients", 0),
            "components": {"database": db["status"], "ml_pipeline": ml["status"], "websocket": ws["status"],
                           "model_storage": storage["status"]}}
    return JSONResponse(body, status_code=200 if ready else 503)


@router.get("/health/db", summary="Database connectivity, latency and migration revision")
@router.get("/api/health/db", summary="Same as /health/db")
async def health_db(request: Request) -> JSONResponse:
    return _reply(await asyncio.to_thread(health.check_database, request.app.state.db))


@router.get("/health/ml", summary="ML pipeline worker, loaded models and model storage")
@router.get("/api/health/ml", summary="Same as /health/ml")
async def health_ml(request: Request) -> JSONResponse:
    state = request.app.state
    pipe = await asyncio.to_thread(health.check_pipeline, state)
    storage = await asyncio.to_thread(health.check_storage, state)
    return _reply({"status": health.overall(pipe["status"], storage["status"]), "pipeline": pipe,
                   "model_storage": storage})


@router.get("/health/websocket", summary="Real-time event bus and connected clients")
@router.get("/api/health/websocket", summary="Same as /health/websocket")
async def health_websocket(request: Request) -> JSONResponse:
    return _reply(health.check_websocket(request.app.state))


@router.get("/api/meta", summary="Categories, seasons, input bounds and detectors (no authentication)")
async def meta(request: Request) -> dict:
    from ml import config as ml_config
    from ml.drift_detector import DETECTOR_INFO, available_detectors
    from ml.validation import BOUNDS
    settings = request.app.state.settings
    return {"version": __version__, "categories": ml_config.CATEGORIES, "seasons": ml_config.SEASONS,
            "preferences": ml_config.PREFERENCES,
            "month_to_season": {str(k): v for k, v in ml_config.MONTH_TO_SEASON.items()},
            "bounds": {k: list(v) for k, v in BOUNDS.items()}, "detectors": available_detectors(),
            "detector_info": DETECTOR_INFO, "simulation_enabled": settings.simulation_enabled,
            "max_upload_mb": settings.max_upload_mb}


@router.get("/api/system/monitoring", summary="System + ML monitoring: component health, pipeline metrics, "
                                               "current model and model health (analyst, admin)")
def system_monitoring(request: Request, stream: Stream = "live", db: Session = Depends(get_db),
                      _: User = Depends(require_staff), pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    return monitoring.system_monitoring(db, request.app.state, stream)
