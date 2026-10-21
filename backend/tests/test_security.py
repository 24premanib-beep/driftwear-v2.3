"""Password hashing, JWTs, login rate limiting and production settings checks."""
import pytest

from app.auth.rate_limit import SlidingWindowLimiter
from app.auth.security import (TokenError, create_access_token, decode_access_token, hash_password,
                               password_problems, verify_password)
from app.config import ConfigError, Settings

SECRET = "x" * 48


def test_password_hashing_roundtrip_and_salting():
    h1, h2 = hash_password("Secret123"), hash_password("Secret123")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("Secret123", h1) and not verify_password("secret123", h1)
    assert not verify_password("anything", "not-a-hash")


def test_password_rules():
    assert password_problems("Secret123") == []
    assert password_problems("short1") and password_problems("lettersonly") and password_problems("12345678")


def test_tokens():
    tok, ttl = create_access_token(user_id=5, role="analyst", token_version=3, secret=SECRET, expires_minutes=10)
    p = decode_access_token(tok, secret=SECRET)
    assert (p["user_id"], p["role"], p["tv"], ttl) == (5, "analyst", 3, 600)
    with pytest.raises(TokenError):
        decode_access_token(tok, secret="y" * 48)
    expired, _ = create_access_token(user_id=5, role="user", token_version=0, secret=SECRET, expires_minutes=-1)
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(expired, secret=SECRET)
    with pytest.raises(TokenError):
        decode_access_token("garbage", secret=SECRET)


def test_login_rate_limiter():
    lim = SlidingWindowLimiter(3, 60)
    assert [lim.hit("k") for _ in range(4)] == [True, True, True, False]
    lim.reset("k")
    assert lim.hit("k")


def test_production_refuses_unsafe_settings(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ConfigError):
        Settings().validated()
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ConfigError):
        Settings().validated()
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    assert Settings().validated().cors_origins == ["https://app.example.com"]
