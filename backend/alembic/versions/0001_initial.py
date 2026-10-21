"""Initial schema: users, uploads, data_records, predictions, drift_events, model_versions, stream_state.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_login_at", TS, nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("missing_values", JSONType, nullable=True),
        sa.Column("report", JSONType, nullable=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_uploads_created_at", "uploads", ["created_at"])

    op.create_table(
        "data_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.String(40), nullable=False),
        sa.Column("purchase_date", sa.DateTime(timezone=False), nullable=False),
        sa.Column("previous_category", sa.String(30), nullable=False),
        sa.Column("purchase_frequency", sa.Integer(), nullable=False),
        sa.Column("recency", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(20), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("discount", sa.Float(), nullable=False),
        sa.Column("customer_preference", sa.String(20), nullable=False),
        sa.Column("target_category", sa.String(30), nullable=False),
        sa.Column("period", sa.Integer(), nullable=True),
        sa.Column("trend", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("processed_at", TS, nullable=True),
    )
    op.create_index("ix_data_records_upload_id", "data_records", ["upload_id"])
    op.create_index("ix_data_records_customer_id", "data_records", ["customer_id"])
    op.create_index("ix_data_records_queue", "data_records", ["status", "purchase_date", "id"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("data_record_id", sa.Integer(), sa.ForeignKey("data_records.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("customer_id", sa.String(40), nullable=True),
        sa.Column("features", JSONType, nullable=False),
        sa.Column("predicted_category", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("probabilities", JSONType, nullable=False),
        sa.Column("baseline_prediction", sa.String(30), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("status_at_prediction", sa.String(10), nullable=False),
        sa.Column("actual_category", sa.String(30), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("step", sa.Integer(), nullable=True),
        sa.Column("detector_status", sa.String(10), nullable=True),
        sa.Column("detector_error", sa.Integer(), nullable=True),
        sa.Column("scored_version", sa.String(20), nullable=True),
        sa.Column("baseline_correct", sa.Boolean(), nullable=True),
        sa.Column("shadow_states", JSONType, nullable=True),
        sa.Column("rescored", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("outcome_at", TS, nullable=True),
        sa.UniqueConstraint("stream", "step", name="uq_predictions_stream_step"),
    )
    op.create_index("ix_predictions_customer_id", "predictions", ["customer_id"])
    op.create_index("ix_predictions_stream_created", "predictions", ["stream", "created_at"])
    op.create_index("ix_predictions_user_created", "predictions", ["user_id", "created_at"])

    op.create_table(
        "drift_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("event_key", sa.String(30), nullable=False),
        sa.Column("detector", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=True),
        sa.Column("stream_step", sa.Integer(), nullable=False),
        sa.Column("change_point_step", sa.Integer(), nullable=True),
        sa.Column("detection_delay", sa.Integer(), nullable=True),
        sa.Column("window_size", sa.Integer(), nullable=True),
        sa.Column("window_start", sa.Integer(), nullable=True),
        sa.Column("accuracy_stable", sa.Float(), nullable=True),
        sa.Column("accuracy_degraded", sa.Float(), nullable=True),
        sa.Column("accuracy_after", sa.Float(), nullable=True),
        sa.Column("previous_model_version", sa.String(20), nullable=False),
        sa.Column("new_model_version", sa.String(20), nullable=True),
        sa.Column("details", JSONType, nullable=True),
        sa.Column("detected_at", TS, nullable=False),
        sa.UniqueConstraint("stream", "event_key", name="uq_drift_events_stream_key"),
    )
    op.create_index("ix_drift_events_stream_step", "drift_events", ["stream", "stream_step"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("parent_version", sa.String(20), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("model_type", sa.String(60), nullable=False),
        sa.Column("trigger", sa.String(200), nullable=False),
        sa.Column("detector", sa.String(20), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column("train_accuracy", sa.Float(), nullable=True),
        sa.Column("training_records", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.Integer(), nullable=True),
        sa.Column("window_end", sa.Integer(), nullable=True),
        sa.Column("change_point_step", sa.Integer(), nullable=True),
        sa.Column("created_step", sa.Integer(), nullable=False),
        sa.Column("accuracy_before", sa.Float(), nullable=True),
        sa.Column("accuracy_after", sa.Float(), nullable=True),
        sa.Column("data_period", sa.String(120), nullable=True),
        sa.Column("calibration_errors", JSONType, nullable=True),
        sa.Column("model_path", sa.String(300), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("model_size", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("drift_event_id", sa.Integer(), sa.ForeignKey("drift_events.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("stream", "version", name="uq_model_versions_stream_version"),
    )
    op.create_index("uq_model_versions_one_active", "model_versions", ["stream"], unique=True,
                    postgresql_where=sa.text("is_active"), sqlite_where=sa.text("is_active = 1"))

    op.create_table(
        "stream_state",
        sa.Column("stream", sa.String(20), primary_key=True),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("detector", sa.String(20), nullable=False),
        sa.Column("next_step", sa.Integer(), nullable=False),
        sa.Column("detector_reset_step", sa.Integer(), nullable=False),
        sa.Column("refresh_anchor", sa.Integer(), nullable=False),
        sa.Column("pending_refresh", JSONType, nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("pointer", sa.Integer(), nullable=True),
        sa.Column("trend_changes", JSONType, nullable=True),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stream_state")
    op.drop_index("uq_model_versions_one_active", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_index("ix_drift_events_stream_step", table_name="drift_events")
    op.drop_table("drift_events")
    for ix in ("ix_predictions_user_created", "ix_predictions_stream_created", "ix_predictions_customer_id"):
        op.drop_index(ix, table_name="predictions")
    op.drop_table("predictions")
    for ix in ("ix_data_records_queue", "ix_data_records_customer_id", "ix_data_records_upload_id"):
        op.drop_index(ix, table_name="data_records")
    op.drop_table("data_records")
    op.drop_index("ix_uploads_created_at", table_name="uploads")
    op.drop_table("uploads")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
