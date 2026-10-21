"""The Alembic migration must create exactly the schema the ORM models describe."""
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_migration_matches_models(tmp_path, monkeypatch):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    from alembic.script import ScriptDirectory

    from app.database import models  # noqa: F401
    from app.database.database import Base
    from app.services.health import EXPECTED_DB_REVISION

    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        tables = set(inspect(conn).get_table_names())
    structural = [d for d in diff if isinstance(d, tuple) and d[0] in
                  ("add_table", "remove_table", "add_column", "remove_column")]
    assert structural == []
    assert {"users", "predictions", "drift_events", "model_versions", "data_records", "audit_logs",
            "rejected_events", "model_activations"} <= tables
    # /health/db compares the database against this constant: keep it equal to the newest migration
    assert ScriptDirectory.from_config(cfg).get_current_head() == EXPECTED_DB_REVISION
    with engine.connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("predictions")}
        indexes = {i["name"] for i in inspect(conn).get_indexes("predictions")}
    assert {"event_id", "explanation"} <= cols and "uq_predictions_stream_event" in indexes
    command.downgrade(cfg, "base")
