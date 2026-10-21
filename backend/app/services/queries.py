"""Read-side queries for the API (lists, filters, statistics). Writes go through the pipeline."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import Select, and_, case, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.database.models import (AuditLog, DataRecord, DriftEvent, ModelVersion, Prediction, RejectedEvent, Upload,
                                 User)
from app.services.analytics import drift_severity
from app.services.sql_repository import activation_rows, row_dict

ANALYTICS_LIMIT = 20_000      # most recent labeled outcomes used for charts and metrics


def _like(term: str) -> str:
    """A LIKE pattern that matches `term` literally (user input cannot inject % or _ wildcards)."""
    escaped = term.strip()[:40].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _iso(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


# ----------------------------------------------------------------------------- predictions
def _prediction_filters(stmt: Select, *, owner_id: int | None, stream: str | None, predicted: str | None,
                        actual: str | None, correct: bool | None, model_version: str | None, labeled: bool | None,
                        search: str | None, date_from: datetime | None, date_to: datetime | None,
                        source: str | None) -> Select:
    conds = []
    if owner_id is not None:
        conds.append(Prediction.user_id == owner_id)
    if stream:
        conds.append(Prediction.stream == stream)
    if predicted:
        conds.append(Prediction.predicted_category == predicted)
    if actual:
        conds.append(Prediction.actual_category == actual)
    if correct is not None:
        conds.append(Prediction.is_correct.is_(correct))
    if model_version:
        conds.append(Prediction.model_version == model_version)
    if labeled is True:
        conds.append(Prediction.actual_category.is_not(None))
    elif labeled is False:
        conds.append(Prediction.actual_category.is_(None))
    if search:
        term = search.strip()[:40]
        clauses = [Prediction.customer_id.ilike(_like(term), escape="\\"), Prediction.event_id == term]
        if term.isdigit():
            clauses.append(Prediction.id == int(term))
        conds.append(or_(*clauses))
    if date_from:
        conds.append(Prediction.created_at >= date_from)
    if date_to:
        conds.append(Prediction.created_at <= date_to)
    if source:
        conds.append(Prediction.source == source)
    return stmt.where(and_(*conds)) if conds else stmt


def list_predictions(s: Session, *, page: int, page_size: int, sort: str = "newest", **filters) -> tuple[list[dict], int]:
    base = _prediction_filters(select(Prediction), **filters)
    total = int(s.scalar(_prediction_filters(select(func.count()).select_from(Prediction), **filters)) or 0)
    order = {"newest": Prediction.id.desc(), "oldest": Prediction.id.asc(),
             "confidence": Prediction.confidence.desc()}.get(sort, Prediction.id.desc())
    rows = s.scalars(base.order_by(order).offset((page - 1) * page_size).limit(page_size)).all()
    return [row_dict(r) for r in rows], total


def get_prediction(s: Session, prediction_id: int) -> dict | None:
    return row_dict(s.get(Prediction, prediction_id))


def prediction_counts(s: Session, stream: str, owner_id: int | None = None) -> dict:
    stmt = select(func.count(), func.count(Prediction.actual_category),
                  func.sum(case((Prediction.is_correct.is_(True), 1), else_=0))).where(Prediction.stream == stream)
    if owner_id is not None:
        stmt = stmt.where(Prediction.user_id == owner_id)
    total, labeled, correct = s.execute(stmt).one()
    return {"total": int(total or 0), "labeled": int(labeled or 0), "awaiting_outcome": int((total or 0) - (labeled or 0)),
            "correct": int(correct or 0)}


# ----------------------------------------------------------------------------- analytics rows
def outcome_rows(s: Session, stream: str, limit: int = ANALYTICS_LIMIT) -> list[dict]:
    stmt = (select(Prediction.step, Prediction.outcome_at, Prediction.predicted_category, Prediction.actual_category,
                   Prediction.is_correct, Prediction.baseline_prediction, Prediction.baseline_correct,
                   Prediction.model_version, Prediction.detector_status, Prediction.detector_error,
                   Prediction.shadow_states, Prediction.features)
            .where(Prediction.stream == stream, Prediction.step.is_not(None))
            .order_by(Prediction.step.desc()).limit(limit))
    out = []
    for r in reversed(s.execute(stmt).all()):
        f = r.features or {}
        out.append({"step": r.step, "ts": r.outcome_at.isoformat() if r.outcome_at else None,
                    "predicted": r.predicted_category, "actual": r.actual_category, "correct": bool(r.is_correct),
                    "baseline_predicted": r.baseline_prediction, "baseline_correct": bool(r.baseline_correct),
                    "model_version": r.model_version, "status": r.detector_status, "error": r.detector_error,
                    "shadow": r.shadow_states or {}, "period": f.get("Period"), "trend": f.get("Trend")})
    return out


def drift_events(s: Session, stream: str, limit: int | None = None, newest_first: bool = False) -> list[dict]:
    stmt = select(DriftEvent).where(DriftEvent.stream == stream)
    stmt = stmt.order_by(DriftEvent.stream_step.desc() if newest_first else DriftEvent.stream_step.asc())
    if limit:
        stmt = stmt.limit(limit)
    rows = [row_dict(d) for d in s.scalars(stmt).all()]
    for d in rows:
        d["detected_at"] = d["detected_at"].isoformat() if d.get("detected_at") else None
        d["severity"] = (d.get("details") or {}).get("severity") or drift_severity(
            d.get("accuracy_stable"), d.get("accuracy_degraded"), d.get("error_rate"))
    return rows


def count_drift_events(s: Session, stream: str) -> int:
    return int(s.scalar(select(func.count()).select_from(DriftEvent).where(DriftEvent.stream == stream)) or 0)


def model_versions(s: Session, stream: str) -> list[dict]:
    rows = [row_dict(v) for v in s.scalars(select(ModelVersion).where(ModelVersion.stream == stream)
                                           .order_by(ModelVersion.id)).all()]
    for v in rows:
        v["created_at"] = v["created_at"].isoformat() if v.get("created_at") else None
    return rows


def model_version(s: Session, stream: str, version: str) -> dict | None:
    return row_dict(s.scalar(select(ModelVersion).where(ModelVersion.stream == stream,
                                                        ModelVersion.version == version)))


# ----------------------------------------------------------------------------- data
def list_uploads(s: Session, page: int, page_size: int) -> tuple[list[dict], int]:
    total = int(s.scalar(select(func.count()).select_from(Upload)) or 0)
    rows = s.scalars(select(Upload).order_by(Upload.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    out = []
    for u in rows:
        d = row_dict(u)
        d.pop("report", None)
        out.append(d)
    return out, total


def get_upload(s: Session, upload_id: int) -> dict | None:
    return row_dict(s.get(Upload, upload_id))


def list_records(s: Session, *, page: int, page_size: int, status: str | None, upload_id: int | None,
                 category: str | None, search: str | None) -> tuple[list[dict], int]:
    conds = []
    if status:
        conds.append(DataRecord.status == status)
    if upload_id:
        conds.append(DataRecord.upload_id == upload_id)
    if category:
        conds.append(DataRecord.target_category == category)
    if search:
        conds.append(DataRecord.customer_id.ilike(_like(search), escape="\\"))
    where = and_(*conds) if conds else None
    count_stmt = select(func.count()).select_from(DataRecord)
    stmt = select(DataRecord).order_by(DataRecord.purchase_date.desc(), DataRecord.id.desc())
    if where is not None:
        count_stmt, stmt = count_stmt.where(where), stmt.where(where)
    total = int(s.scalar(count_stmt) or 0)
    rows = s.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return [row_dict(r) for r in rows], total


def data_statistics(s: Session) -> dict:
    by_status = dict(s.execute(select(DataRecord.status, func.count()).group_by(DataRecord.status)).all())
    by_category = dict(s.execute(select(DataRecord.target_category, func.count())
                                 .group_by(DataRecord.target_category)).all())
    agg = s.execute(select(func.count(), func.avg(DataRecord.price), func.avg(DataRecord.discount),
                           func.min(DataRecord.purchase_date), func.max(DataRecord.purchase_date))).one()
    up = s.execute(select(func.count(), func.coalesce(func.sum(Upload.total_rows), 0),
                          func.coalesce(func.sum(Upload.valid_rows), 0),
                          func.coalesce(func.sum(Upload.invalid_rows), 0),
                          func.coalesce(func.sum(Upload.duplicate_rows), 0))).one()
    missing: dict[str, int] = {}
    for (mv,) in s.execute(select(Upload.missing_values)).all():
        for k, v in (mv or {}).items():
            missing[k] = missing.get(k, 0) + int(v or 0)
    return {
        "records": {"total": int(agg[0] or 0), "pending": int(by_status.get("pending", 0)),
                    "processed": int(by_status.get("processed", 0))},
        "by_target_category": {k: int(v) for k, v in by_category.items()},
        "avg_price": round(float(agg[1]), 2) if agg[1] is not None else None,
        "avg_discount": round(float(agg[2]), 2) if agg[2] is not None else None,
        "date_range": [agg[3].isoformat() if agg[3] else None, agg[4].isoformat() if agg[4] else None],
        "uploads": {"count": int(up[0]), "total_rows": int(up[1]), "valid_rows": int(up[2]),
                    "invalid_rows": int(up[3]), "duplicate_rows": int(up[4])},
        "missing_values": missing,
    }


# ----------------------------------------------------------------------------- users
def list_users(s: Session) -> list[User]:
    return list(s.scalars(select(User).order_by(User.id)).all())


# ----------------------------------------------------------------------------- data drift & monitoring
def recent_inputs(s: Session, stream: str, limit: int) -> tuple[list[dict], dict]:
    """The most recent `limit` model inputs on a stream, labeled or not (data drift needs no labels)."""
    rows = s.execute(select(Prediction.features, Prediction.created_at)
                     .where(Prediction.stream == stream)
                     .order_by(Prediction.id.desc()).limit(limit)).all()
    feats = [dict(r.features or {}) for r in rows]
    stamps = [r.created_at for r in rows if r.created_at is not None]
    return feats, {"window": limit, "label": f"Last {len(feats)} inputs",
                   "from": _iso(min(stamps)) if stamps else None, "to": _iso(max(stamps)) if stamps else None}


def pipeline_metrics(s: Session, stream: str) -> dict:
    """Counters and timestamps for System monitoring, straight from the stored rows."""
    total, labeled, last_pred, last_outcome = s.execute(
        select(func.count(), func.count(Prediction.actual_category), func.max(Prediction.created_at),
               func.max(Prediction.outcome_at)).where(Prediction.stream == stream)).one()
    by_source = dict(s.execute(select(Prediction.source, func.count()).where(Prediction.stream == stream)
                               .group_by(Prediction.source)).all())
    drifts, last_drift, failed = s.execute(
        select(func.count(), func.max(DriftEvent.detected_at),
               func.coalesce(func.sum(case((DriftEvent.action == "Adaptation failed", 1), else_=0)), 0))
        .where(DriftEvent.stream == stream)).one()
    versions, adaptations, last_adapt = s.execute(
        select(func.count(), func.coalesce(func.sum(case((ModelVersion.kind != "initial", 1), else_=0)), 0),
               func.max(case((ModelVersion.kind != "initial", ModelVersion.created_at))))
        .where(ModelVersion.stream == stream)).one()
    return {
        "predictions_made": int(total or 0), "outcomes_received": int(labeled or 0),
        "awaiting_outcome": int((total or 0) - (labeled or 0)),
        "predictions_by_source": {k: int(v) for k, v in by_source.items()},
        "drift_events": int(drifts or 0), "failed_adaptations": int(failed or 0),
        "models_created": int(versions or 0), "adaptations": int(adaptations or 0),
        "last_prediction_at": _iso(last_pred), "last_drift_check_at": _iso(last_outcome),
        "last_drift_at": _iso(last_drift), "last_adaptation_at": _iso(last_adapt),
    }


# ----------------------------------------------------------------------------- audit log
def _audit_filters(stmt: Select, *, action: str | None, user_id: int | None, resource: str | None,
                   severity: str | None, stream: str | None, date_from: datetime | None,
                   date_to: datetime | None, system: bool | None) -> Select:
    conds = []
    if action:
        conds.append(AuditLog.action.like(action[:-1] + "%") if action.endswith("*") else AuditLog.action == action)
    if user_id is not None:
        conds.append(AuditLog.user_id == user_id)
    if system is True:
        conds.append(AuditLog.user_id.is_(None))
    if resource:
        conds.append(AuditLog.resource == resource)
    if severity:
        conds.append(AuditLog.severity == severity)
    if stream:
        conds.append(AuditLog.stream == stream)
    if date_from:
        conds.append(AuditLog.created_at >= date_from)
    if date_to:
        conds.append(AuditLog.created_at <= date_to)
    return stmt.where(and_(*conds)) if conds else stmt


def list_audit_logs(s: Session, *, page: int, page_size: int, **filters) -> tuple[list[dict], int]:
    total = int(s.scalar(_audit_filters(select(func.count()).select_from(AuditLog), **filters)) or 0)
    stmt = _audit_filters(select(AuditLog, User.name, User.email).outerjoin(User, User.id == AuditLog.user_id),
                          **filters)
    rows = s.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for log_row, name, email in rows:
        d = row_dict(log_row)
        d["user"] = None if d["user_id"] is None else {"id": d["user_id"], "name": name, "email": email}
        d["actor"] = "System" if d["user_id"] is None else (name or f"User #{d['user_id']}")
        items.append(d)
    return items, total


def audit_facets(s: Session) -> dict:
    actions = [a for (a,) in s.execute(select(distinct(AuditLog.action)).order_by(AuditLog.action)).all()]
    resources = [r for (r,) in s.execute(select(distinct(AuditLog.resource)).order_by(AuditLog.resource)).all()]
    users = [{"id": uid, "name": name, "email": email} for uid, name, email in s.execute(
        select(User.id, User.name, User.email).where(User.id.in_(select(distinct(AuditLog.user_id))))
        .order_by(User.name)).all()]
    return {"actions": actions, "resources": resources, "users": users, "severities": ["info", "warning", "critical"]}


# ----------------------------------------------------------------------------- live data, validation, rollback
def prediction_counts_by_version(s: Session, stream: str) -> dict[str, int]:
    """Every prediction (labeled or not) per model version: how much traffic each model served."""
    return {v: int(n) for v, n in s.execute(select(Prediction.model_version, func.count())
                                            .where(Prediction.stream == stream)
                                            .group_by(Prediction.model_version)).all()}


def model_activations(s: Session, stream: str, limit: int = 200) -> list[dict]:
    return activation_rows(s, stream, limit)


def event_summary(s: Session, owner_id: int | None = None) -> dict:
    """Live purchase events (source = event): received, labeled, correct, awaiting, rejected."""
    conds = [Prediction.stream == "live", Prediction.source == "event"]
    if owner_id is not None:
        conds.append(Prediction.user_id == owner_id)
    total, labeled, correct, last = s.execute(
        select(func.count(), func.count(Prediction.actual_category),
               func.sum(case((Prediction.is_correct.is_(True), 1), else_=0)), func.max(Prediction.created_at))
        .where(*conds)).one()
    rq = select(func.count(), func.max(RejectedEvent.created_at)).select_from(RejectedEvent)
    if owner_id is not None:
        rq = rq.where(RejectedEvent.user_id == owner_id)
    rejected, last_rejection = s.execute(rq).one()
    total, labeled, correct = int(total or 0), int(labeled or 0), int(correct or 0)
    return {"scope": "own" if owner_id is not None else "all", "received": total, "labeled": labeled,
            "awaiting_outcome": total - labeled, "correct": correct, "wrong": labeled - correct,
            "accuracy": round(correct / labeled, 4) if labeled else None, "rejected": int(rejected or 0),
            "last_event_at": _iso(last), "last_rejection_at": _iso(last_rejection)}


def list_rejections(s: Session, *, page: int, page_size: int, owner_id: int | None = None) -> tuple[list[dict], int]:
    count = select(func.count()).select_from(RejectedEvent)
    stmt = select(RejectedEvent, User.name).outerjoin(User, User.id == RejectedEvent.user_id)
    if owner_id is not None:
        count, stmt = count.where(RejectedEvent.user_id == owner_id), stmt.where(RejectedEvent.user_id == owner_id)
    total = int(s.scalar(count) or 0)
    items = []
    for row, name in s.execute(stmt.order_by(RejectedEvent.id.desc()).offset((page - 1) * page_size)
                               .limit(page_size)).all():
        d = row_dict(row)
        d["created_at"] = _iso(d["created_at"])
        d["user_name"] = name
        items.append(d)
    return items, total


def rejection_reasons(s: Session, limit: int = 500, top: int = 8) -> list[dict]:
    """Most common validation problems among the most recent rejected events."""
    counter: Counter = Counter()
    for errors in s.scalars(select(RejectedEvent.errors).order_by(RejectedEvent.id.desc()).limit(limit)).all():
        for e in errors or []:
            counter[(e.get("field"), e.get("message"))] += 1
    return [{"field": f, "message": m, "count": n} for (f, m), n in counter.most_common(top)]


def data_channel_counts(s: Session) -> dict:
    """Every way data enters the platform, from stored rows (both streams; simulation kept separate)."""
    by = {(st, src): int(n) for st, src, n in s.execute(
        select(Prediction.stream, Prediction.source, func.count()).group_by(Prediction.stream, Prediction.source)).all()}
    rejected, last_rejection = s.execute(select(func.count(), func.max(RejectedEvent.created_at))
                                         .select_from(RejectedEvent)).one()
    records, pending = s.execute(select(func.count(), func.coalesce(func.sum(
        case((DataRecord.status == "pending", 1), else_=0)), 0)).select_from(DataRecord)).one()
    uploads, uploads_rejected, rows_invalid, rows_dup = s.execute(select(
        func.count(), func.coalesce(func.sum(case((Upload.status == "rejected", 1), else_=0)), 0),
        func.coalesce(func.sum(Upload.invalid_rows), 0), func.coalesce(func.sum(Upload.duplicate_rows), 0))
        .select_from(Upload)).one()
    live_events = by.get(("live", "event"), 0)
    live_total = sum(n for (st, _), n in by.items() if st == "live")
    simulation = sum(n for (st, _), n in by.items() if st == "simulation")
    rejected = int(rejected or 0)
    return {
        "total_events_processed": live_total + simulation, "live_predictions": live_total,
        "live_events": live_events, "valid_events": live_events, "rejected_events": rejected,
        "event_rejection_rate": round(rejected / (live_events + rejected), 4) if live_events + rejected else None,
        "prediction_form": by.get(("live", "api"), 0),
        "uploaded_records": int(records or 0), "uploaded_records_pending": int(pending or 0),
        "uploaded_records_processed": by.get(("live", "upload"), 0),
        "uploads": int(uploads or 0), "uploads_rejected": int(uploads_rejected or 0),
        "upload_rows_rejected": int(rows_invalid or 0), "upload_rows_duplicate": int(rows_dup or 0),
        "simulation_events": simulation, "last_rejection_at": _iso(last_rejection),
    }
