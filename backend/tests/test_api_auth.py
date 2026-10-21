"""Authentication, roles, logout and error format (FastAPI + SQLite)."""
from tests.conftest import auth


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"name": "Asha Rao", "email": "Asha@Example.com",
                                                 "password": "Passw0rd123"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "asha@example.com" and body["role"] == "user" and "password_hash" not in body
    r = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "Passw0rd123"})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer" and r.json()["expires_in"] > 0
    me = client.get("/api/auth/me", headers=auth(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["name"] == "Asha Rao"


def test_registration_errors(client):
    payload = {"name": "Dup", "email": "dup@example.com", "password": "Passw0rd123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    r = client.post("/api/auth/register", json={**payload, "email": "weak@example.com", "password": "onlyletters"})
    assert r.status_code == 422 and "numbers" in r.json()["error"]["message"]
    r = client.post("/api/auth/register", json={**payload, "email": "not-an-email"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "email"


def test_login_failures_do_not_reveal_accounts(client, make_user):
    u = make_user()
    wrong = client.post("/api/auth/login", json={"email": u["email"], "password": "Wrong12345"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong12345"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.headers.get("www-authenticate") == "Bearer"


def test_token_required_and_validated(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth("not.a.jwt")).status_code == 401
    assert client.get("/api/predictions").json()["error"]["code"] == "not_authenticated"


def test_role_based_access(client, make_user):
    user, analyst = make_user("user"), make_user("analyst")
    assert client.get("/api/users", headers=user["headers"]).status_code == 403
    assert client.get("/api/drift/events", headers=user["headers"]).status_code == 403
    assert client.get("/api/performance", headers=user["headers"]).status_code == 403
    assert client.get("/api/simulation/state", headers=user["headers"]).status_code == 403
    assert client.get("/api/drift/events", headers=analyst["headers"]).status_code == 200
    assert client.get("/api/performance", headers=analyst["headers"]).status_code == 200
    assert client.post("/api/models/adapt", json={"stream": "live"}, headers=analyst["headers"]).status_code == 403
    assert client.get("/api/users", headers=analyst["headers"]).status_code == 403
    assert client.get("/api/dashboard", headers=user["headers"]).status_code == 200


def test_logout_revokes_tokens(client, make_user):
    u = make_user()
    assert client.get("/api/auth/me", headers=u["headers"]).status_code == 200
    assert client.post("/api/auth/logout", headers=u["headers"]).status_code == 204
    r = client.get("/api/auth/me", headers=u["headers"])
    assert r.status_code == 401 and "session" in r.json()["error"]["message"].lower()


def test_admin_user_management(client, admin, make_user):
    u = make_user()
    r = client.patch(f"/api/users/{u['id']}", json={"is_active": False}, headers=admin["headers"])
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/auth/me", headers=u["headers"]).status_code == 401
    assert client.post("/api/auth/login", json={"email": u["email"], "password": u["password"]}).status_code == 401
    r = client.patch(f"/api/users/{admin['id']}", json={"role": "user"}, headers=admin["headers"])
    assert r.status_code == 422                                   # cannot lock yourself out
    assert client.patch("/api/users/999999", json={"role": "user"}, headers=admin["headers"]).status_code == 404


def test_health_docs_headers_and_404(client):
    h = client.get("/api/health")
    assert h.status_code == 200 and h.json()["pipeline"] == "ready" and h.json()["database"] is True
    assert h.headers["x-content-type-options"] == "nosniff" and h.headers.get("x-request-id")
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/predict", "/api/predictions", "/api/drift/status", "/api/models/current", "/api/data/upload"):
        assert p in paths
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_meta_is_public_and_matches_ml_config(client):
    from ml import config
    m = client.get("/api/meta").json()
    assert m["categories"] == config.CATEGORIES and m["bounds"]["Discount"] == [0, 90]
    assert m["month_to_season"]["7"] == "Monsoon" and "DDM" in m["detectors"]
