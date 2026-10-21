"""Live data pathway, data validation and model rollback.

* rejected_events: live events that failed validation, with their errors (rejections are counted, not lost)
* model_activations: who activated / rolled back which model version, from which, when and why
  (written in the same transaction as the switch, so history always matches what served predictions)
* data_records.record_hash: fingerprint of a validated record; rows an earlier upload already queued are
  skipped instead of being fed to the drift detector twice. Existing rows are back-filled here.

Additive only: no existing column changes, so older code keeps working against this schema.

Revision ID: 0003_live_data_rollback
Revises: 0002_audit_events
Create Date: 2026-10-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_live_data_rollback"
down_revision = "0002_audit_events"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
BATCH = 1000


def _backfill_record_hashes() -> None:
    from ml.validation import record_hash   # the same fingerprint the upload route computes

    t = sa.table("data_records", sa.column("id", sa.Integer), sa.column("customer_id", sa.String),
                 sa.column("purchase_date", sa.DateTime), sa.column("previous_category", sa.String),
                 sa.column("purchase_frequency", sa.Integer), sa.column("recency", sa.Integer),
                 sa.column("season", sa.String), sa.column("month", sa.Integer), sa.column("price", sa.Float),
                 sa.column("discount", sa.Float), sa.column("customer_preference", sa.String),
                 sa.column("target_category", sa.String), sa.column("record_hash", sa.String))
    conn = op.get_bind()
    last = 0
    while True:
        rows = conn.execute(sa.select(t).where(t.c.id > last).order_by(t.c.id).limit(BATCH)).mappings().all()
        if not rows:
            break
        updates = [{"rid": r["id"], "h": record_hash({
            "Customer_ID": r["customer_id"], "Purchase_Date": r["purchase_date"],
            "Previous_Category": r["previous_category"], "Purchase_Frequency": r["purchase_frequency"],
            "Recency": r["recency"], "Season": r["season"], "Month": r["month"], "Price": r["price"],
            "Discount": r["discount"], "Customer_Preference": r["customer_preference"],
            "Target_Category": r["target_category"]})} for r in rows]
        conn.execute(t.update().where(t.c.id == sa.bindparam("rid")).values(record_hash=sa.bindparam("h")), updates)
        last = rows[-1]["id"]


def upgrade() -> None:
    op.add_column("data_records", sa.Column("record_hash", sa.String(64), nullable=True))
    op.create_index("ix_data_records_record_hash", "data_records", ["record_hash"])
    _backfill_record_hashes()

    op.create_table(
        "rejected_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=True),
        sa.Column("batch_index", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("errors", JSONType, nullable=False),
        sa.Column("payload", JSONType, nullable=True),
    )
    op.create_index("ix_rejected_events_created", "rejected_events", ["created_at"])

    op.create_table(
        "model_activations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("from_version", sa.String(20), nullable=False),
        sa.Column("to_version", sa.String(20), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("at_step", sa.Integer(), nullable=True),
        sa.CheckConstraint("action IN ('rollback', 'activate')", name="ck_model_activations_action"),
    )
    op.create_index("ix_model_activations_stream_created", "model_activations", ["stream", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_model_activations_stream_created", table_name="model_activations")
    op.drop_table("model_activations")
    op.drop_index("ix_rejected_events_created", table_name="rejected_events")
    op.drop_table("rejected_events")
    op.drop_index("ix_data_records_record_hash", table_name="data_records")
    with op.batch_alter_table("data_records") as batch:     # batch: SQLite cannot always DROP COLUMN in place
        batch.drop_column("record_hash")
