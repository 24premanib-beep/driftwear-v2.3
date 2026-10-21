"""
Application errors. Raised anywhere in the service layer and converted into a
consistent JSON shape by the handlers in main.py:

    {"error": {"code": "...", "message": "...", "details": ...}}

Messages are written for end users. Stack traces and internal details are only
logged, never returned.
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code, code = 404, "not_found"


class ConflictError(AppError):
    status_code, code = 409, "conflict"


class AuthError(AppError):
    status_code, code = 401, "not_authenticated"


class PermissionDeniedError(AppError):
    status_code, code = 403, "forbidden"


class ValidationFailedError(AppError):
    status_code, code = 422, "validation_failed"


class PayloadTooLargeError(AppError):
    status_code, code = 413, "payload_too_large"


class RateLimitedError(AppError):
    status_code, code = 429, "rate_limited"


class ServiceUnavailableError(AppError):
    status_code, code = 503, "service_unavailable"


class MLError(AppError):
    """The ML engine could not complete a request (e.g. not enough labeled data)."""
    status_code, code = 409, "ml_error"
