"""Startup helpers: wait for the database, create the first admin account."""
from __future__ import annotations

import logging
import time

from sqlalchemy import func, select

from app.auth.security import hash_password, password_problems
from app.config import ConfigError, Settings
from app.database.database import Database
from app.database.models import User

log = logging.getLogger(__name__)


def wait_for_database(db: Database, attempts: int = 30, delay: float = 2.0) -> None:
    for i in range(1, attempts + 1):
        try:
            db.ping()
            return
        except Exception as exc:  # noqa: BLE001
            if i == attempts:
                raise RuntimeError(f"Database is not reachable: {exc.__class__.__name__}") from exc
            log.warning("Database not ready (attempt %d/%d); retrying in %.0fs", i, attempts, delay)
            time.sleep(delay)


def ensure_admin(db: Database, settings: Settings) -> None:
    """Create the admin from ADMIN_EMAIL / ADMIN_PASSWORD if that account does not exist.

    Never changes an existing account's password (change it in the app instead).
    """
    with db.transaction() as s:
        if not settings.admin_email or not settings.admin_password:
            if not s.scalar(select(func.count()).select_from(User).where(User.role == "admin")):
                log.warning("No admin account exists. Set ADMIN_EMAIL and ADMIN_PASSWORD to create one "
                            "(uploads, adaptation and model management need an admin).")
            return
        email = settings.admin_email.strip().lower()
        user = s.scalar(select(User).where(User.email == email))
        if user is None:
            problems = password_problems(settings.admin_password)
            if problems:
                msg = "ADMIN_PASSWORD is too weak: it needs " + " and ".join(problems)
                if settings.is_production:
                    raise ConfigError(msg)
                log.warning(msg)
            s.add(User(name=settings.admin_name, email=email, password_hash=hash_password(settings.admin_password),
                       role="admin"))
            log.info("Created admin account %s", email)
        elif user.role != "admin":
            user.role = "admin"
            log.warning("Account %s promoted to admin (it is ADMIN_EMAIL)", email)
