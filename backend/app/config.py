"""
Application settings, read from environment variables (see .env.example).

Deliberately dependency-free (no pydantic-settings) so the service layer can be
imported by scripts and tests without the web stack. Nothing deployment-specific
is hard-coded: every value has a safe development default and production
refuses to start without the secrets it needs.
"""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:  # optional: load backend/.env or ./.env during local development
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)
# Development-only default (matches the README's local PostgreSQL container). Production must set DATABASE_URL.
DEFAULT_DATABASE_URL = "postgresql+psycopg://driftwear:driftwear@localhost:5432/driftwear"


def _env(name: str, default: str = "") -> str:
    """Environment variable; empty values count as unset."""
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    app_name: str = "DriftWear API"
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", DEFAULT_DATABASE_URL))
    db_pool_size: int = field(default_factory=lambda: int(_env("DB_POOL_SIZE", "5")))
    auto_create_tables: bool = field(default_factory=lambda: _bool("AUTO_CREATE_TABLES", False))

    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", ""))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = field(default_factory=lambda: int(_env("JWT_EXPIRE_MINUTES", "60")))

    cors_origins: list[str] = field(default_factory=lambda: _list(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))

    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", ""))
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", ""))
    admin_name: str = field(default_factory=lambda: _env("ADMIN_NAME", "Administrator"))

    model_storage_backend: str = field(default_factory=lambda: _env("MODEL_STORAGE_BACKEND", "local"))
    model_storage_dir: str = field(default_factory=lambda: _env(
        "MODEL_STORAGE_DIR", str(PROJECT_ROOT / "models")))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", ""))
    s3_prefix: str = field(default_factory=lambda: _env("S3_PREFIX", "driftwear/models"))
    s3_endpoint_url: str = field(default_factory=lambda: _env("S3_ENDPOINT_URL", ""))
    s3_region: str = field(default_factory=lambda: _env("S3_REGION", ""))

    max_upload_mb: float = field(default_factory=lambda: float(_env("MAX_UPLOAD_MB", "5")))
    max_upload_rows: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_ROWS", "50000")))

    simulation_enabled: bool = field(default_factory=lambda: _bool("SIMULATION_ENABLED", True))
    simulation_tick_seconds: float = field(default_factory=lambda: float(_env("SIMULATION_TICK_SECONDS", "1.0")))
    default_detector: str = field(default_factory=lambda: _env("DEFAULT_DETECTOR", "DDM"))

    login_rate_limit: int = field(default_factory=lambda: int(_env("LOGIN_RATE_LIMIT", "10")))
    login_rate_window_seconds: int = field(default_factory=lambda: int(_env("LOGIN_RATE_WINDOW_SECONDS", "300")))
    # predictions + real-time events per user per minute
    prediction_rate_limit: int = field(default_factory=lambda: int(_env("PREDICTION_RATE_LIMIT", "120")))
    # most events / outcomes accepted in one POST /api/events/batch or /api/events/outcomes request
    event_batch_max: int = field(default_factory=lambda: int(_env("EVENT_BATCH_MAX", "100")))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    def validated(self) -> "Settings":
        """Fail fast on unsafe production configuration; fill dev-only defaults."""
        if self.is_production:
            problems = []
            if len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be set to a random string of at least 32 characters")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must list explicit origins in production")
            if self.model_storage_backend == "s3" and not self.s3_bucket:
                problems.append("S3_BUCKET is required when MODEL_STORAGE_BACKEND=s3")
            if not _env("DATABASE_URL"):
                problems.append("DATABASE_URL must be set explicitly in production")
            if problems:
                raise ConfigError("; ".join(problems))
            return self
        if not self.jwt_secret:
            log.warning("JWT_SECRET is not set: using a random development secret "
                        "(all tokens become invalid when the server restarts).")
            object.__setattr__(self, "jwt_secret", secrets.token_urlsafe(48))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings().validated()
