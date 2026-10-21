"""
Test configuration.

Environment is set before the app is imported: SQLite database and model
directory in a temp folder, a test JWT secret, a test admin, a small upload
limit and a fast simulation tick. FastAPI is only imported inside fixtures, so
the pure ML/pipeline tests also run without the web stack installed.
"""
import itertools
import os
import tempfile
import uuid
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="driftwear-tests-"))
ADMIN_EMAIL, ADMIN_PASSWORD = "admin@example.com", "AdminPass123"
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
    "AUTO_CREATE_TABLES": "true",
    "JWT_SECRET": "test-secret-" + "x" * 40,
    "MODEL_STORAGE_BACKEND": "local",
    "MODEL_STORAGE_DIR": str(TMP / "models"),
    "ADMIN_EMAIL": ADMIN_EMAIL,
    "ADMIN_PASSWORD": ADMIN_PASSWORD,
    "SIMULATION_TICK_SECONDS": "0.01",
    "MAX_UPLOAD_MB": "0.05",
    "LOGIN_RATE_LIMIT": "1000",
    "PREDICTION_RATE_LIMIT": "100000",
    "CORS_ORIGINS": "http://testserver",
    "LOG_LEVEL": "WARNING",
})


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    app = create_app(Settings().validated())
    with TestClient(app) as c:          # runs the lifespan: tables, admin, v1.0 models, pipeline
        yield c


@pytest.fixture(scope="session")
def admin(client):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"id": r.json()["user"]["id"], "token": tok, "headers": auth(tok)}


@pytest.fixture(scope="session")
def make_user(client, admin):
    counter = itertools.count()

    def _make(role: str = "user") -> dict:
        email = f"{role}{next(counter)}-{uuid.uuid4().hex[:6]}@example.com"
        password = "Passw0rd123"
        r = client.post("/api/auth/register", json={"name": f"Test {role}", "email": email, "password": password})
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        if role != "user":
            r = client.patch(f"/api/users/{uid}", json={"role": role}, headers=admin["headers"])
            assert r.status_code == 200, r.text
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        tok = r.json()["access_token"]
        return {"id": uid, "email": email, "password": password, "token": tok, "headers": auth(tok)}
    return _make


VALID_INPUT = {"customer_id": "C1042", "previous_category": "Tops", "purchase_frequency": 6, "recency": 21,
               "purchase_date": "2026-04-10T12:00:00", "price": 1499, "discount": 10,
               "customer_preference": "Casual"}
