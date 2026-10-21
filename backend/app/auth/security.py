"""
Password hashing and JWT handling (no web-framework imports).

Passwords: scrypt from the Python standard library (memory-hard KDF; OWASP-listed).
Stored format:  scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>
so the cost parameters can be raised later without breaking existing hashes.

Tokens: HS256 JWTs with `sub` (user id), `role`, `tv` (token version), `iat`,
`exp`. The server re-reads the user on every request, so a role change or a
logout (which bumps the user's token_version) takes effect immediately even for
tokens that have not expired.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 8


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=_SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), n=int(n), r=int(r),
                                p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(expected))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


# A real hash of a random string, used to keep login timing the same for unknown emails.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > 128:
        problems.append("at most 128 characters")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("both letters and numbers")
    return problems


class TokenError(Exception):
    pass


def create_access_token(*, user_id: int, role: str, token_version: int, secret: str,
                        expires_minutes: int, algorithm: str = "HS256") -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes)
    payload = {"sub": str(user_id), "role": role, "tv": int(token_version),
               "iat": int(now.timestamp()), "exp": int(exp.timestamp()), "type": "access"}
    return jwt.encode(payload, secret, algorithm=algorithm), expires_minutes * 60


def decode_access_token(token: str, *, secret: str, algorithm: str = "HS256") -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm], options={"require": ["exp", "sub", "iat"]})
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Your session has expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid authentication token.") from exc
    if payload.get("type") != "access":
        raise TokenError("Invalid authentication token.")
    try:
        payload["user_id"] = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("Invalid authentication token.") from exc
    return payload
