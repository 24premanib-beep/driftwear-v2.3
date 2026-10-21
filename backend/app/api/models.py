"""Model registry and adaptation."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.api.common import audit_async
from app.auth.dependencies import get_current_user, get_db, get_pipeline, is_staff, require_admin, require_staff
from app.database.models import User
from app.database.schemas import MIN_ROLLBACK_REASON, ActivateRequest, AdaptRequest, RollbackRequest, Stream
from app.errors import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.services import analytics, monitoring, queries
from app.services.pipeline import PipelineService, is_rollback

router = APIRouter(prefix="/api/models", tags=["Model registry"])
VERSION_PATTERN = r"^v\d{1,4}\.\d{1,4}$"
HIDDEN = ("model_path", "calibration_errors", "run_id")


def _public(v: dict) -> dict:
    return {k: val for k, val in v.items() if k not in HIDDEN}


def _with_live_metrics(versions: list[dict], rows: list[dict]) -> list[dict]:
    live = {m["version"]: m for m in analytics.by_version(rows)}
    return [{**_public(v), "live_metrics": live.get(v["version"])} for v in versions]


@router.get("", summary="All model versions with validation and live metrics")
def list_models(stream: Stream = "live", db: Session = Depends(get_db), _: User = Depends(require_staff)) -> dict:
    versions = queries.model_versions(db, stream)
    return {"mode": stream, "items": _with_live_metrics(versions, queries.outcome_rows(db, stream)),
            "metric_note": "accuracy/precision/recall/f1_score are out-of-fold validation metrics on the "
                           "training window; live_metrics are measured on real outcomes after deployment."}


@router.get("/health", summary="Model health score of the active model (accuracy, F1, drift, age, adaptation)")
def model_health(stream: Stream = "live", db: Session = Depends(get_db), user: User = Depends(get_current_user),
                 pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    if stream == "simulation" and not is_staff(user):
        raise PermissionDeniedError("Simulation data is available to analysts and admins.")
    return {"mode": stream, **monitoring.model_health_for(db, pipeline, stream)}


METRICS = ("accuracy", "precision", "recall", "f1", "error_rate")


def _card(v: dict, live: dict | None) -> dict:
    acc = v.get("accuracy")
    validation = {"accuracy": acc, "precision": v.get("precision"), "recall": v.get("recall"),
                  "f1": v.get("f1_score"), "error_rate": None if acc is None else round(1 - acc, 4)}
    live_m = None
    if live:
        live_m = {k: live.get(k) for k in ("accuracy", "precision", "recall", "f1", "n")}
        live_m["error_rate"] = None if live.get("accuracy") is None else round(1 - live["accuracy"], 4)
    return {**{k: v.get(k) for k in ("version", "parent_version", "kind", "trigger", "detector", "model_type",
                                     "training_records", "window_start", "window_end", "data_period",
                                     "created_step", "created_at", "is_active", "accuracy_before",
                                     "accuracy_after", "drift_event_id")},
            "validation": validation, "live": live_m}


def _diff(a: dict | None, b: dict | None) -> dict:
    out = {}
    for m in METRICS:
        va, vb = (a or {}).get(m), (b or {}).get(m)
        if va is None or vb is None:
            out[m] = {"delta": None, "better": None}
            continue
        delta = round(vb - va, 4)
        improved = delta < 0 if m == "error_rate" else delta > 0
        out[m] = {"delta": delta, "better": None if delta == 0 else ("b" if improved else "a")}
    return out


@router.get("/compare", summary="Compare two model versions (validation and live metrics, lineage)")
def compare_models(a: str = Query(pattern=VERSION_PATTERN), b: str = Query(pattern=VERSION_PATTERN),
                   stream: Stream = "live", db: Session = Depends(get_db), _: User = Depends(require_staff)) -> dict:
    versions = {v["version"]: v for v in queries.model_versions(db, stream)}
    missing = [x for x in (a, b) if x not in versions]
    if missing:
        raise NotFoundError(f"Model version {missing[0]} not found on the {stream} stream.")
    live = {m["version"]: m for m in analytics.by_version(queries.outcome_rows(db, stream))}
    ca, cb = _card(versions[a], live.get(a)), _card(versions[b], live.get(b))
    return {"mode": stream, "a": ca, "b": cb,
            "diff": {"validation": _diff(ca["validation"], cb["validation"]), "live": _diff(ca["live"], cb["live"])},
            "note": "Validation metrics are out-of-fold on each model's own training window, so they are not "
                    "measured on the same records. Live metrics are measured on the outcomes each model predicted. "
                    "Missing values mean no data, never zero."}


@router.get("/activations", summary="Activation and rollback history: who, from which version, to which, when, why")
def activations(stream: Stream = "live", db: Session = Depends(get_db), _: User = Depends(require_staff)) -> dict:
    acts = queries.model_activations(db, stream)
    return {"mode": stream, "items": acts,
            "timeline": analytics.activation_timeline(queries.model_versions(db, stream), acts)}


async def _activation_reply(pipeline: PipelineService, stream: str, res: dict, reason: str | None) -> dict:
    latest = await asyncio.to_thread(pipeline.activation_history, stream)
    rollback = is_rollback(res["previous_version"], res["active_version"])
    return {**res, "rollback": rollback, "reason": reason, "activation": latest[0] if latest else None,
            "message": (f"Rollback completed: {res['active_version']} is active (was {res['previous_version']}). "
                        if rollback else f"{res['active_version']} is active (was {res['previous_version']}). ")
            + "Every new prediction uses it; the detector restarted for it; no version was deleted."}


@router.post("/rollback", summary="Roll back to an earlier model version (admin; the current one is kept)")
async def rollback(body: RollbackRequest, request: Request, admin: User = Depends(require_admin),
                   pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    """Verifies the version exists and is older than the active one, loads its stored file (checksum checked),
    makes it active, records who / from / to / when / why in the activation history and the audit log, and
    notifies connected clients. 404: unknown version · 409: already active or newer · 503: file unreadable."""
    res = await pipeline.activate_version(body.stream, body.to_version, actor=admin.email, user_id=admin.id,
                                          reason=body.reason, rollback_only=True)
    await audit_async(request, "model.rollback", user=admin, resource="model_version", resource_id=body.to_version,
                      stream=body.stream, severity="warning",
                      details={"from_version": res["previous_version"], "to_version": res["active_version"],
                               "reason": body.reason})
    return await _activation_reply(pipeline, body.stream, res, body.reason)


@router.get("/current", summary="The active model with feature importance")
async def current_model(stream: Stream = "live", _: User = Depends(require_staff),
                        pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    version = pipeline.status(stream)["model_version"]
    return await _detail(pipeline, stream, version)


@router.get("/{version}", summary="One model version")
async def get_model(version: str = Path(pattern=VERSION_PATTERN), stream: Stream = "live",
                    _: User = Depends(require_staff), pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    return await _detail(pipeline, stream, version)


async def _detail(pipeline: PipelineService, stream: str, version: str) -> dict:
    db = pipeline.repo.db

    def load() -> tuple[dict | None, list[dict], dict | None]:
        with db.session() as s:
            row = queries.model_version(s, stream, version)
            rows = queries.outcome_rows(s, stream)
            event = None
            if row and row.get("drift_event_id"):
                event = next((e for e in queries.drift_events(s, stream) if e["id"] == row["drift_event_id"]), None)
            return row, rows, event
    row, rows, event = await asyncio.to_thread(load)
    if row is None:
        raise NotFoundError(f"Model version {version} not found on the {stream} stream.")
    live = next((m for m in analytics.by_version(rows) if m["version"] == version), None)
    importance = await pipeline.version_importance(stream, version)
    return {**_public(row), "live_metrics": live, "drift_event": event, "feature_importance": importance}


@router.post("/adapt", summary="Retrain now on recent labeled data (admin)")
async def adapt(body: AdaptRequest, request: Request, admin: User = Depends(require_admin),
                pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    res = await pipeline.adapt_now(body.stream, actor=admin.email)
    await audit_async(request, "model.retrain_requested", user=admin, resource="model_version",
                      resource_id=res["version"], stream=body.stream,
                      details={"from_version": res.get("parent_version"), "to_version": res["version"],
                               "records_used": res.get("records_used")})
    return res


@router.post("/{version}/activate", summary="Make an earlier version active again (rollback, admin)")
async def activate(body: ActivateRequest, request: Request, version: str = Path(pattern=VERSION_PATTERN),
                   admin: User = Depends(require_admin), pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    current = pipeline.status(body.stream)["model_version"]
    if is_rollback(current, version) and len((body.reason or "").strip()) < MIN_ROLLBACK_REASON:
        # activating an OLDER version is a rollback, which (like POST /rollback) must say why
        raise ValidationFailedError(f"{version} is older than the active {current}, so this is a rollback: give a reason.",
                                    details=[{"field": "reason", "message": f"Required for a rollback (at least {MIN_ROLLBACK_REASON} characters)."}])
    res = await pipeline.activate_version(body.stream, version, actor=admin.email, user_id=admin.id,
                                          reason=body.reason)
    rollback = is_rollback(res["previous_version"], res["active_version"])
    await audit_async(request, "model.rollback" if rollback else "model.activated", user=admin,
                      resource="model_version", resource_id=version, stream=body.stream,
                      severity="warning" if rollback else "info",
                      details={"from_version": res["previous_version"], "to_version": res["active_version"],
                               "reason": body.reason})
    return await _activation_reply(pipeline, body.stream, res, body.reason)
