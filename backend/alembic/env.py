"""Alembic environment: uses the app's models and DATABASE_URL."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend/

from app.database import models  # noqa: E402,F401 - register tables
from app.database.database import Base, normalize_database_url  # noqa: E402

try:  # local development: read backend/.env like the API does
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

from app.config import DEFAULT_DATABASE_URL  # noqa: E402

url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url") or DEFAULT_DATABASE_URL
config.set_main_option("sqlalchemy.url", normalize_database_url(url).replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                         prefix="sqlalchemy.", poolclass=pool.NullPool)
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
