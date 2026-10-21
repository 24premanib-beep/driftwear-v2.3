"""
Single-writer guard.

The drift detector must have exactly one writer. On PostgreSQL the API process
that holds a session-level advisory lock runs the pipeline; any other process
(a second uvicorn worker, or the new instance during a zero-downtime deploy)
starts in *standby*: it serves read endpoints and health checks, and takes over
the pipeline as soon as the lock is released. SQLite (tests, local dev) has no
lock: run a single process.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

log = logging.getLogger(__name__)
LOCK_KEY = 7_172_026_001


class InstanceLock:
    def __init__(self, db):
        self.db = db
        self._conn = None

    @property
    def supported(self) -> bool:
        return self.db.dialect == "postgresql"

    @property
    def held(self) -> bool:
        return self._conn is not None or not self.supported

    def try_acquire(self) -> bool:
        if not self.supported or self._conn is not None:
            return True
        conn = self.db.engine.connect()
        try:
            ok = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
            conn.commit()           # the lock is session-level; don't sit idle in a transaction
        except Exception:
            conn.close()
            raise
        if not ok:
            conn.close()
            return False
        self._conn = conn
        return True

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            self._conn.commit()
        except Exception:  # noqa: BLE001 - closing the connection releases it anyway
            log.warning("Could not release the pipeline lock cleanly")
        finally:
            self._conn.close()
            self._conn = None
