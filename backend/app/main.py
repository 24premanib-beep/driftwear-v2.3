"""
DriftWear API – FastAPI application.

Run (development):   uvicorn app.main:app --reload            (from backend/)
Run (production):    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
API docs:            /docs (Swagger UI)  ·  /redoc
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import audit as audit_api
from app.api import auth, dashboard, data, drift, events_ingest, models, predictions, simulation, system, users, websocket
from app.auth.rate_limit import SlidingWindowLimiter
from app.config import Settings, get_settings
from app.database.database import Database
from app.errors import AppError
from app.logging_config import configure_logging, request_id_var
from app.services.audit import AuditEventRecorder, AuditService
from app.services.bootstrap import ensure_admin, wait_for_database
from app.services.events import EventBus
from app.services.ingestion import IngestionService, SqlRejectionStore
from app.services.instance_lock import InstanceLock
from app.services.metrics import RequestMetrics, ResourceSampler
from app.services.model_storage import build_model_storage
from app.services.pipeline import PipelineService
from app.services.sql_repository import SqlRepository
from app.websocket.manager import ConnectionManager

API_VERSION = __version__
log = logging.getLogger("app")
STANDBY_RETRY_SECONDS = 3.0
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

DESCRIPTION = """
Real-time **concept drift detection and model adaptation** platform; fashion category prediction is the use case.

`event → features → prediction → actual outcome → error → DDM / ADWIN / Page-Hinkley → STABLE / WARNING / DRIFT
→ retrain on the post-change window → new model version → model registry → WebSocket events`

* **Live data**: `POST /api/events` (or `/purchase`, `/batch`) → validation → prediction; `POST /api/events/outcome(s)`
  when the real category is known. Invalid events are rejected with every problem listed and stored for review.
* **Drift performance**: `GET /api/performance/comparison` (before / during / after drift, measured).
* **Rollback**: `POST /api/models/rollback` (admin), history at `GET /api/models/activations`.
* **Live** stream: real predictions (`POST /api/predict`), real outcomes, uploaded labeled CSVs.
* **Data drift** (`GET /api/drift/data`) is reported separately from **concept drift**; only concept drift adapts.
* Health: `GET /health`, `/health/db`, `/health/ml`, `/health/websocket` (also under `/api/health/*`).
* **Simulation mode** (`/api/simulation/*`): replays the synthetic dataset; stored separately (`stream=simulation`).

Authenticate with **Authorize** (email as username). Roles: *user* (predict, own history),
*analyst* (monitoring, performance), *admin* (uploads, adaptation, model management, users).
Real-time events: WebSocket `/ws` (send `{"type": "auth", "token": "<JWT>"}` first).
"""

TAGS = [
    {"name": "Authentication"},
    {"name": "Real-time events", "description": "Purchase events in, predictions out; outcomes feed the drift detector."},
    {"name": "Predictions"}, {"name": "Dashboard & performance"},
    {"name": "Concept drift"}, {"name": "Model registry"}, {"name": "Data management"},
    {"name": "Audit log", "description": "Admin-only history of user and pipeline actions."},
    {"name": "Simulation mode", "description": "Synthetic replay, clearly separate from live data."},
    {"name": "Users"}, {"name": "System"},
]


# ============================================================================ middleware
class RequestContextMiddleware:
    """Request id, access log, security headers and an early request-size guard (pure ASGI)."""

    def __init__(self, app, max_body_bytes: int, production: bool, metrics: RequestMetrics | None = None):
        self.app = app
        self.metrics = metrics
        self.max_body = max_body_bytes
        self.production = production
        self.access = logging.getLogger("app.access")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _REQUEST_ID_RE.match(incoming or "") else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        path = scope.get("path", "")
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = rid
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                if not path.startswith(("/docs", "/redoc", "/openapi.json")):
                    h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
                if path.startswith("/api"):
                    h["Cache-Control"] = "no-store"
                if self.production:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        try:
            length = headers.get(b"content-length")
            if length is not None and length.isdigit() and int(length) > self.max_body:
                resp = JSONResponse(status_code=413, content=_error_body(
                    "payload_too_large", f"The request is larger than {self.max_body // (1024 * 1024)} MB."))
                await resp(scope, receive, send_wrapper)
                return
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            self.access.info("%s %s %s %.0fms", scope.get("method"), path, status_holder["code"], elapsed)
            if self.metrics is not None:
                self.metrics.record(scope.get("method") or "", path, status_holder["code"], elapsed)
            request_id_var.reset(token)


# ============================================================================ errors
def _error_body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details,
                      "request_id": request_id_var.get()}}


def _validation_details(errors: list[dict]) -> list[dict]:
    out = []
    for e in errors:
        loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
        msg = str(e.get("msg", "Invalid value"))
        for prefix in ("Value error, ", "Assertion failed, "):
            msg = msg.removeprefix(prefix)
        out.append({"field": ".".join(loc) or None, "message": msg})
    return out


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details),
                            headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = _validation_details(exc.errors())
        first = details[0] if details else {"field": None, "message": "Invalid request"}
        message = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
        return JSONResponse(status_code=422, content=_error_body("validation_failed", message, details))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "not_authenticated"}.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        if exc.status_code == 404 and message == "Not Found":
            message = "This endpoint does not exist."
        return JSONResponse(status_code=exc.status_code, content=_error_body(code, message),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_: Request, exc: SQLAlchemyError):
        log.exception("Database error", exc_info=exc)
        return JSONResponse(status_code=503, content=_error_body(
            "database_unavailable", "The database is temporarily unavailable. Please try again."))

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content=_error_body(
            "internal_error", "Something went wrong on our side. The error has been logged."))


# ============================================================================ lifespan
async def _become_leader(app: FastAPI) -> None:
    """Standby → leader: wait for the pipeline lock, then load the engines from the database."""
    lock: InstanceLock = app.state.instance_lock
    while not await asyncio.to_thread(lock.try_acquire):
        await asyncio.sleep(STANDBY_RETRY_SECONDS)
    log.info("Pipeline lock acquired; leaving standby")
    app.state.pipeline_state = "starting"
    try:
        await app.state.pipeline.start()
        app.state.pipeline_state = "ready"
    except Exception:  # noqa: BLE001
        log.exception("Pipeline failed to start after leaving standby")
        app.state.pipeline_state = "failed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    db = Database(settings.database_url, settings.db_pool_size)
    await asyncio.to_thread(wait_for_database, db)
    if settings.auto_create_tables:
        await asyncio.to_thread(db.create_all)
    await asyncio.to_thread(ensure_admin, db, settings)

    storage = build_model_storage(settings)
    bus = EventBus()
    manager = ConnectionManager()
    audit = AuditService(db)
    bus.subscribe(manager.broadcast)
    bus.subscribe(AuditEventRecorder(audit))        # drift / adaptation / model events the pipeline emits itself
    await bus.start()
    pipeline = PipelineService(SqlRepository(db), storage, bus, simulation_enabled=settings.simulation_enabled,
                               default_detector=settings.default_detector,
                               tick_seconds=settings.simulation_tick_seconds)
    lock = InstanceLock(db)
    app.state.ingestion = IngestionService(pipeline, SqlRejectionStore(db), max_batch=settings.event_batch_max)
    app.state.db, app.state.bus, app.state.ws_manager, app.state.audit = db, bus, manager, audit
    app.state.pipeline, app.state.storage, app.state.instance_lock = pipeline, storage, lock
    standby_task = None
    try:
        if await asyncio.to_thread(lock.try_acquire):
            app.state.pipeline_state = "starting"
            await pipeline.start()            # fail fast: a broken live model must stop the deploy
            app.state.pipeline_state = "ready"
        else:
            app.state.pipeline_state = "standby"
            log.warning("Another process holds the pipeline lock; starting in standby (read-only) mode")
            standby_task = asyncio.create_task(_become_leader(app), name="standby")
        log.info("DriftWear API %s started (%s, storage=%s, simulation=%s)", API_VERSION, settings.environment,
                 storage.describe(), settings.simulation_enabled)
        yield
    finally:
        if standby_task:
            standby_task.cancel()
        await pipeline.stop()                 # safe if it never started
        await bus.stop()
        await asyncio.to_thread(lock.release)
        db.dispose()
        log.info("DriftWear API stopped")


# ============================================================================ factory
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="DriftWear API", version=API_VERSION, description=DESCRIPTION, openapi_tags=TAGS,
                  lifespan=lifespan, docs_url="/docs", redoc_url="/redoc")
    app.state.settings = settings
    app.state.pipeline_state = "not_started"
    app.state.login_limiter = SlidingWindowLimiter(settings.login_rate_limit, settings.login_rate_window_seconds)
    app.state.prediction_limiter = SlidingWindowLimiter(settings.prediction_rate_limit, 60)
    app.state.metrics = RequestMetrics()          # API request status / latency (System monitoring)
    app.state.resources = ResourceSampler()       # process CPU and memory (N/A where the OS does not report them)

    # the last middleware added is the outermost: CORS wraps everything, so even early 413s carry CORS headers
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_upload_bytes + 1024 * 1024,
                       production=settings.is_production, metrics=app.state.metrics)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                       expose_headers=["X-Request-ID"], max_age=600)
    register_exception_handlers(app)

    for r in (system.router, auth.router, events_ingest.router, predictions.router, dashboard.router, drift.router,
              models.router, data.router, simulation.router, users.router, audit_api.router, websocket.router):
        app.include_router(r)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"name": "DriftWear API", "version": API_VERSION, "docs": "/docs", "health": "/health"}

    return app


app = create_app()
