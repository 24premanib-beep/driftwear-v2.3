"""Helpers shared by the API routers: client IP, audit entries and the per-user prediction rate limit."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Request

from app.database.models import User
from app.errors import RateLimitedError


def client_ip(request: Request) -> str | None:
    # uvicorn runs with --proxy-headers behind nginx, so this is the browser's address, not the proxy's
    return request.client.host if request.client else None


def audit(request: Request, action: str, *, resource: str, user: User | None = None, user_id: int | None = None,
          resource_id: Any = None, severity: str = "info", stream: str | None = None,
          details: dict | None = None) -> None:
    """Record an audit entry (sync: call from sync routes or worker threads). Never raises."""
    sink = getattr(request.app.state, "audit", None)
    if sink is None:
        return
    sink.record(action, resource=resource, resource_id=resource_id,
                user_id=user.id if user is not None else user_id, severity=severity, stream=stream,
                ip=client_ip(request), details=details)


async def audit_async(request: Request, action: str, **kw: Any) -> None:
    await asyncio.to_thread(audit, request, action, **kw)


def enforce_prediction_rate(request: Request, user: User, n: int = 1) -> None:
    """Per-user limit on predictions / ingested events (PREDICTION_RATE_LIMIT per minute); a batch counts each event."""
    limiter = getattr(request.app.state, "prediction_limiter", None)
    if limiter is None:
        return
    for _ in range(max(1, int(n))):
        if not limiter.hit(f"user:{user.id}"):
            raise RateLimitedError("Too many predictions in a short time. Please slow down and retry in a minute.")
