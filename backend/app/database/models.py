"""
ORM models.

Required tables: users, predictions, drift_events, model_versions, data_records.
Supporting tables: uploads (one row per CSV upload with its validation report),
stream_state (what the drift engine needs to resume after a restart),
audit_logs (who did what, plus what the pipeline did on its own),
rejected_events (live events that failed validation, with their errors) and
model_activations (who activated / rolled back which version, when and why).

A real-time purchase event is stored as its prediction row (source = "event",
event_id = the producer's id), so features are never duplicated in a second table.

Every drift-related table has a `stream` column ('live' | 'simulation') so real
and simulated data never mix.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))            # accepted | rejected
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    missing_values: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DataRecord(Base):
    """A validated, labeled purchase record waiting for (or already through) the live stream."""
    __tablename__ = "data_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    row_number: Mapped[int] = mapped_column(Integer)
    customer_id: Mapped[str] = mapped_column(String(40), index=True)
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    previous_category: Mapped[str] = mapped_column(String(30))
    purchase_frequency: Mapped[int] = mapped_column(Integer)
    recency: Mapped[int] = mapped_column(Integer)
    season: Mapped[str] = mapped_column(String(20))
    month: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    discount: Mapped[float] = mapped_column(Float)
    customer_preference: Mapped[str] = mapped_column(String(20))
    target_category: Mapped[str] = mapped_column(String(30))
    period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trend: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")   # pending | processed
    prediction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # fingerprint of the validated record (ml.validation.record_hash): re-uploaded rows are detected and skipped
    record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (Index("ix_data_records_queue", "status", "purchase_date", "id"),)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))            # api | upload | simulation
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    data_record_id: Mapped[int | None] = mapped_column(ForeignKey("data_records.id", ondelete="SET NULL"),
                                                        nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    features: Mapped[dict] = mapped_column(JSONType)
    predicted_category: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float)
    probabilities: Mapped[dict] = mapped_column(JSONType)
    baseline_prediction: Mapped[str] = mapped_column(String(30))
    model_version: Mapped[str] = mapped_column(String(20))
    status_at_prediction: Mapped[str] = mapped_column(String(10))
    # filled when the actual category arrives
    actual_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detector_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    detector_error: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    baseline_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    shadow_states: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    rescored: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # real-time event ingestion: the producer's event id (idempotency) and why the model predicted what it did
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        UniqueConstraint("stream", "step", name="uq_predictions_stream_step"),
        Index("ix_predictions_stream_created", "stream", "created_at"),
        Index("ix_predictions_user_created", "user_id", "created_at"),
        Index("ix_predictions_stream_outcome", "stream", "outcome_at"),
        # NULLs never collide, so only events that carry an id are deduplicated
        Index("uq_predictions_stream_event", "stream", "event_id", unique=True),
    )


class DriftEvent(Base):
    __tablename__ = "drift_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream: Mapped[str] = mapped_column(String(20))
    event_key: Mapped[str] = mapped_column(String(30))        # "Drift 1", "Drift 2", ...
    detector: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40))
    error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    stream_step: Mapped[int] = mapped_column(Integer)
    change_point_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detection_delay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accuracy_stable: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_degraded: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_model_version: Mapped[str] = mapped_column(String(20))
    new_model_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("stream", "event_key", name="uq_drift_events_stream_key"),
        Index("ix_drift_events_stream_step", "stream", "stream_step"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream: Mapped[str] = mapped_column(String(20))
    run_id: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    parent_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))              # initial | drift | refresh | manual
    model_type: Mapped[str] = mapped_column(String(60))
    trigger: Mapped[str] = mapped_column(String(200))
    detector: Mapped[str] = mapped_column(String(20))
    # out-of-fold validation metrics on the training window (not training-set accuracy)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_records: Mapped[int] = mapped_column(Integer)
    window_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_point_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_step: Mapped[int] = mapped_column(Integer)
    accuracy_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_period: Mapped[str | None] = mapped_column(String(120), nullable=True)
    calibration_errors: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    model_path: Mapped[str] = mapped_column(String(300))
    checksum: Mapped[str] = mapped_column(String(64))
    model_size: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    drift_event_id: Mapped[int | None] = mapped_column(ForeignKey("drift_events.id", ondelete="SET NULL"),
                                                        nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("stream", "version", name="uq_model_versions_stream_version"),
        # at most one active model per stream, enforced by the database
        Index("uq_model_versions_one_active", "stream", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active = 1")),
    )


class StreamState(Base):
    __tablename__ = "stream_state"

    stream: Mapped[str] = mapped_column(String(20), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40))
    detector: Mapped[str] = mapped_column(String(20))
    next_step: Mapped[int] = mapped_column(Integer, default=0)
    detector_reset_step: Mapped[int] = mapped_column(Integer, default=0)
    refresh_anchor: Mapped[int] = mapped_column(Integer, default=0)
    pending_refresh: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pointer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trend_changes: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """One audited action. user_id is NULL for actions the pipeline took on its own ("system")."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))              # e.g. auth.login, drift.detected, model.rollback
    resource: Mapped[str] = mapped_column(String(40))            # e.g. user, prediction, model_version
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(10), default="info")   # info | warning | critical
    stream: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_audit_logs_severity"),
        Index("ix_audit_logs_created", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_resource_created", "resource", "created_at"),
    )


class RejectedEvent(Base):
    """A live purchase event that failed validation. It never reached the model; it is kept so rejections are
    counted and explained (Data validation, System monitoring) instead of disappearing as a 422."""
    __tablename__ = "rejected_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    stream: Mapped[str] = mapped_column(String(20), default="live")
    source: Mapped[str] = mapped_column(String(20))                  # single | batch
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer)
    errors: Mapped[list] = mapped_column(JSONType)                   # [{field, value, message}]
    payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)   # sanitised, bounded copy

    __table_args__ = (Index("ix_rejected_events_created", "created_at"),)


class ModelActivation(Base):
    """An admin activating a stored model version (rollback = an older one). Written in the same transaction
    that switches is_active, so the history always matches what actually served predictions."""
    __tablename__ = "model_activations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stream: Mapped[str] = mapped_column(String(20))
    from_version: Mapped[str] = mapped_column(String(20))
    to_version: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))                  # rollback | activate
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    at_step: Mapped[int | None] = mapped_column(Integer, nullable=True)   # outcomes processed when it happened

    __table_args__ = (
        CheckConstraint("action IN ('rollback', 'activate')", name="ck_model_activations_action"),
        Index("ix_model_activations_stream_created", "stream", "created_at"),
    )
