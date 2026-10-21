"""Audit log, real-time event ids and per-prediction explanations.

* audit_logs: who did what (and what the pipeline did on its own)
* predictions.event_id: producer id of a real-time purchase event; unique per stream (idempotent ingestion)
* predictions.explanation: feature contributions behind the prediction
* ix_predictions_stream_outcome: "last drift check" / outcome-time queries for System monitoring

Revision ID: 0002_audit_events
Revises: 0001_initial
Create Date: 2026-10-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_audit_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("predictions", sa.Column("event_id", sa.String(64), nullable=True))
    op.add_column("predictions", sa.Column("explanation", JSONType, nullable=True))
    op.create_index("uq_predictions_stream_event", "predictions", ["stream", "event_id"], unique=True)
    op.create_index("ix_predictions_stream_outcome", "predictions", ["stream", "outcome_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("resource", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("stream", sa.String(20), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("details", JSONType, nullable=True),
        sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_audit_logs_severity"),
    )
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_resource_created", "audit_logs", ["resource", "created_at"])


def downgrade() -> None:
    for ix in ("ix_audit_logs_resource_created", "ix_audit_logs_user_created", "ix_audit_logs_action_created",
               "ix_audit_logs_created"):
        op.drop_index(ix, table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_predictions_stream_outcome", table_name="predictions")
    op.drop_index("uq_predictions_stream_event", table_name="predictions")
    with op.batch_alter_table("predictions") as batch:     # batch: SQLite cannot always DROP COLUMN in place
        batch.drop_column("explanation")
        batch.drop_column("event_id")
