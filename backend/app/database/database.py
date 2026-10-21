"""Database engine and session handling (SQLAlchemy 2.0, sync, psycopg 3)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Hosting providers hand out postgres:// URLs; SQLAlchemy needs the driver name."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str, pool_size: int = 5) -> Engine:
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - sqlite only
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=pool_size, max_overflow=pool_size * 2,
                         pool_recycle=1800)


class Database:
    def __init__(self, url: str, pool_size: int = 5):
        self.engine = make_engine(url, pool_size)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=False)

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    def session(self) -> Session:
        return self.SessionLocal()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Commit on success, roll back on any exception."""
        with self.SessionLocal() as s, s.begin():
            yield s

    def create_all(self) -> None:
        from app.database import models  # noqa: F401 - register tables
        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    def migration_revision(self) -> str | None:
        """The Alembic revision the database is at, or None (no alembic_version table, e.g. create_all)."""
        try:
            with self.engine.connect() as conn:
                return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001 - missing table or no permission: report "unknown"
            return None

    def dispose(self) -> None:
        self.engine.dispose()
