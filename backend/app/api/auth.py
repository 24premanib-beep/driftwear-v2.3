"""Authentication: register, login (JSON and OAuth2 form for Swagger), current user, logout."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import audit, audit_async
from app.auth.dependencies import get_current_user, get_db, get_settings_dep
from app.auth.security import DUMMY_HASH, create_access_token, hash_password, password_problems, verify_password
from app.config import Settings
from app.database.models import User, utcnow
from app.database.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.errors import AuthError, ConflictError, RateLimitedError, ValidationFailedError

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _authenticate(request: Request, db: Session, settings: Settings, email: str, password: str) -> TokenResponse:
    limiter = request.app.state.login_limiter
    email = email.strip().lower()
    ip = _client_ip(request)
    if not (limiter.hit(f"ip:{ip}") and limiter.hit(f"email:{email}")):
        audit(request, "auth.rate_limited", resource="user", severity="warning")
        raise RateLimitedError("Too many sign-in attempts. Please wait a few minutes and try again.")
    user = db.scalar(select(User).where(User.email == email))
    # verify against a dummy hash for unknown emails so response time does not reveal which emails exist
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok:
        # the attempted email is not stored (people sometimes type a password into it)
        audit(request, "auth.login_failed", resource="user", user_id=user.id if user else None,
              resource_id=user.id if user else None, severity="warning",
              details={"reason": "wrong password" if user else "unknown account"})
        raise AuthError("Incorrect email or password.")
    if not user.is_active:
        audit(request, "auth.login_failed", resource="user", user_id=user.id, resource_id=user.id,
              severity="warning", details={"reason": "account disabled"})
        raise AuthError("This account has been disabled. Contact an administrator.")
    limiter.reset(f"email:{email}")
    user.last_login_at = utcnow()
    db.commit()
    token, ttl = create_access_token(user_id=user.id, role=user.role, token_version=user.token_version,
                                     secret=settings.jwt_secret, expires_minutes=settings.jwt_expire_minutes,
                                     algorithm=settings.jwt_algorithm)
    audit(request, "auth.login", resource="user", user=user, resource_id=user.id, details={"role": user.role})
    return TokenResponse(access_token=token, expires_in=ttl, user=UserOut.model_validate(user))


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             summary="Create an account (role: user)")
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> User:
    problems = password_problems(body.password)
    if problems:
        raise ValidationFailedError("Password must have " + " and ".join(problems) + ".",
                                    details=[{"field": "password", "message": ", ".join(problems)}])
    email = body.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("An account with this email already exists.")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password), role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(request, "auth.registered", resource="user", user=user, resource_id=user.id)
    return user


@router.post("/login", response_model=TokenResponse, summary="Sign in with email and password")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings_dep)) -> TokenResponse:
    return _authenticate(request, db, settings, body.email, body.password)


@router.post("/token", response_model=TokenResponse, include_in_schema=True,
             summary="OAuth2 form login (used by the Swagger 'Authorize' button; username = email)")
def token(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings_dep)) -> TokenResponse:
    return _authenticate(request, db, settings, form.username, form.password)


@router.get("/me", response_model=UserOut, summary="The signed-in user")
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             summary="Sign out everywhere (revokes all of this user's tokens)")
async def logout(request: Request, user: User = Depends(get_current_user)) -> Response:
    db = request.app.state.db

    def bump() -> None:
        with db.transaction() as s:
            u = s.get(User, user.id)
            u.token_version += 1
    await asyncio.to_thread(bump)
    await audit_async(request, "auth.logout", resource="user", user=user, resource_id=user.id)
    await request.app.state.ws_manager.close_user(user.id, reason="Signed out")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
