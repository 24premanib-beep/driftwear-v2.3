"""FastAPI dependencies: database session, pipeline, current user and role checks."""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import TokenError, decode_access_token
from app.config import Settings
from app.database.models import User
from app.errors import AuthError, PermissionDeniedError, ServiceUnavailableError
from app.services.pipeline import PipelineService

# tokenUrl powers Swagger's "Authorize" button (form login at /api/auth/token)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

STAFF = ("analyst", "admin")


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.session() as session:
        yield session


def get_pipeline(request: Request) -> PipelineService:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None or not pipeline.ready:
        raise ServiceUnavailableError("The drift pipeline is starting up. Please try again in a moment.")
    return pipeline


def user_from_token(token: str, db: Session, settings: Settings) -> User:
    try:
        payload = decode_access_token(token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm)
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    user = db.get(User, payload["user_id"])
    if user is None or not user.is_active:
        raise AuthError("This account does not exist or has been disabled.")
    if payload.get("tv") != user.token_version:
        raise AuthError("Your session has ended. Please sign in again.")
    return user


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings_dep)) -> User:
    if not token:
        raise AuthError("Please sign in to continue.")
    return user_from_token(token, db, settings)


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("You do not have permission to do this.")
        return user
    return checker


require_staff = require_roles(*STAFF)
require_admin = require_roles("admin")


def is_staff(user: User) -> bool:
    return user.role in STAFF
