"""
End-to-end test against a RUNNING stack (docker compose up), through the
frontend's nginx: browser routes → API → PostgreSQL → model storage → WebSocket.

    docker compose up -d --build
    pip install -r e2e/requirements.txt
    ADMIN_PASSWORD=... pytest e2e -v          # E2E_BASE_URL defaults to http://localhost:8080
"""
import asyncio
import json
import os
import time
import uuid

import httpx
import pytest
import websockets

BASE = os.getenv("E2E_BASE_URL", "http://localhost:8080").rstrip("/")
WS_URL = ("wss" if BASE.startswith("https") else "ws") + BASE[BASE.index("://"):] + "/ws"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
PURCHASE = {"customer_id": "E2E1", "previous_category": "Tops", "purchase_frequency": 6, "recency": 21,
            "price": 1499, "discount": 10, "customer_preference": "Casual"}


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=BASE, timeout=120) as c:
        deadline = time.time() + 240
        while True:
            try:
                r = c.get("/api/health")
                if r.status_code == 200 and r.json().get("pipeline") == "ready":
                    break
            except httpx.HTTPError:
                pass
            if time.time() > deadline:
                pytest.fail(f"The stack at {BASE} did not become ready")
            time.sleep(2)
        yield c


def _login(http, email, password):
    r = http.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


@pytest.fixture(scope="module")
def admin(http):
    assert ADMIN_PASSWORD, "Set ADMIN_PASSWORD to the stack's admin password"
    return _login(http, ADMIN_EMAIL, ADMIN_PASSWORD)[0]


def _new_user(http):
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    assert http.post("/api/auth/register", json={"name": "E2E User", "email": email, "password": "E2ePass123"}).status_code == 201
    return _login(http, email, "E2ePass123")


def test_frontend_and_docs_are_served(http):
    for path in ("/", "/app/drift", "/login"):            # SPA routes fall back to index.html
        r = http.get(path)
        assert r.status_code == 200 and '<div id="root">' in r.text
    assert http.get("/docs").status_code == 200
    assert "/api/predict" in http.get("/openapi.json").json()["paths"]
    assert http.get("/api/meta").json()["categories"]


def test_prediction_outcome_and_realtime_events(http):
    headers, token = _new_user(http)

    async def flow():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({"type": "auth", "token": token}))
            hello = json.loads(await asyncio.wait_for(ws.recv(), 15))
            assert hello["event"] == "CONNECTED" and hello["data"]["role"] == "user"
            async with httpx.AsyncClient(base_url=BASE, timeout=60) as ac:
                r = await ac.post("/api/predict", json={**PURCHASE, "actual_category": "Bottoms"}, headers=headers)
                assert r.status_code == 201, r.text
                pid = r.json()["prediction"]["id"]
            seen = set()
            deadline = time.time() + 30
            while not {"PREDICTION_CREATED", "PREDICTION_RESULT"} <= seen:
                assert time.time() < deadline, f"events received: {seen}"
                ev = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if ev.get("data", {}).get("prediction_id") == pid:
                    seen.add(ev["event"])
    asyncio.run(flow())
    hist = http.get("/api/predictions", headers=headers).json()
    assert hist["total"] == 1 and hist["items"][0]["actual_category"] == "Bottoms"


def test_upload_validate_and_process(http, admin):
    rows = "\n".join(f"E2E{i},2026-02-1{i} 10:00,Tops,3,10,Winter,2,{900 + i},5,Sporty,Footwear" for i in range(5))
    csv = ("Customer_ID,Purchase_Date,Previous_Category,Purchase_Frequency,Recency,Season,Month,Price,Discount,"
           "Customer_Preference,Target_Category\n" + rows + "\nBAD,not-a-date,Tops,3,10,Winter,2,900,5,Sporty,Footwear\n")
    r = http.post("/api/data/upload", files={"file": ("e2e.csv", csv.encode(), "text/csv")}, headers=admin)
    assert r.status_code == 201, r.text
    assert r.json()["report"]["valid_rows"] == 5 and r.json()["report"]["invalid_rows"] == 1
    r = http.post("/api/drift/process", json={"stream": "live", "count": 500}, headers=admin)
    assert r.status_code == 200 and r.json()["processed"] >= 5 and r.json()["remaining"] == 0


def test_simulated_drift_creates_a_new_model_version(http, admin):
    if not http.get("/api/meta").json()["simulation_enabled"]:
        pytest.skip("Simulation mode is disabled on this stack")
    assert http.post("/api/simulation/reset", json={}, headers=admin).status_code == 200
    assert http.post("/api/simulation/trend-change", headers=admin).status_code == 200
    for _ in range(40):
        r = http.post("/api/simulation/step", json={"count": 25, "stop_on_drift": True}, headers=admin).json()
        if r["drift_events"]:
            break
    else:
        pytest.fail("No drift detected after the trend change")
    models = http.get("/api/models", params={"stream": "simulation"}, headers=admin).json()["items"]
    v2 = next(m for m in models if m["version"] == "v2.0")
    assert v2["is_active"] and v2["drift_event_id"]
    detail = http.get("/api/models/v2.0", params={"stream": "simulation"}, headers=admin).json()
    assert detail["feature_importance"]                      # model file loads back from storage
    events = http.get("/api/drift/events", params={"stream": "simulation"}, headers=admin).json()
    assert events and events[0]["new_model_version"] == "v2.0"
    dash = http.get("/api/dashboard", params={"stream": "simulation"}, headers=admin).json()
    assert dash["kpis"]["drift_events"] >= 1 and dash["markers"]["drifts"]


def test_logout_revokes_the_token(http):
    headers, _ = _new_user(http)
    assert http.get("/api/auth/me", headers=headers).status_code == 200
    assert http.post("/api/auth/logout", headers=headers).status_code == 204
    assert http.get("/api/auth/me", headers=headers).status_code == 401


def test_health_endpoints_through_nginx(http):
    for path in ("/health", "/health/db", "/health/ml", "/health/websocket", "/api/health/db"):
        r = http.get(path)
        assert r.status_code == 200, (path, r.text)
    assert http.get("/health/db").json()["revision"] == http.get("/health/db").json()["expected_revision"]


def test_realtime_event_ingestion_and_audit(http, admin):
    headers, _ = _new_user(http)
    eid = f"e2e-{uuid.uuid4().hex[:10]}"
    event = {**PURCHASE, "event_id": eid, "season": "Summer", "month": 6}
    r = http.post("/api/events/purchase", json=event, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["explanation"]["contributions"] and r.json()["prediction"]["source"] == "event"
    assert http.post("/api/events/purchase", json=event, headers=headers).status_code == 409
    out = http.post("/api/events/outcome", json={"event_id": eid, "actual_category": "Tops"}, headers=headers)
    assert out.status_code == 200 and out.json()["outcome"]["step"] >= 0
    logs = http.get("/api/audit-logs?action=event.ingested", headers=admin).json()["items"]
    assert any(i["details"].get("event_id") == eid for i in logs)
    mon = http.get("/api/system/monitoring", headers=admin).json()
    assert mon["components"]["database"]["status"] == "healthy" and mon["pipeline_metrics"]["predictions_made"] >= 1


def test_live_data_validation_comparison_and_monitoring(http, admin):
    """Live event → validation (accepted and rejected) → outcome; comparison, activations and monitoring
    respond through nginx; the database is at the newest migration."""
    headers, _ = _new_user(http)
    eid = f"e2e-{uuid.uuid4().hex[:10]}"
    r = http.post("/api/events", json={**PURCHASE, "event_id": eid}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["validation"]["passed"] and r.json()["prediction"]["model_version"]
    bad = http.post("/api/events", json={**PURCHASE, "price": -500, "season": "XYZ"}, headers=headers)
    assert bad.status_code == 422 and {d["field"] for d in bad.json()["error"]["details"]} >= {"price", "season"}
    assert http.post("/api/events/outcome", json={"event_id": eid, "actual_category": "Tops"},
                     headers=headers).status_code == 200
    s = http.get("/api/events/summary", headers=headers).json()
    assert (s["received"], s["labeled"], s["rejected"]) == (1, 1, 1)
    m = http.get("/api/system/monitoring", headers=admin).json()
    assert m["application"]["database"]["connected"] and m["data"]["rejected_events"] >= 1
    assert http.get("/api/performance/comparison?stream=simulation", headers=admin).status_code == 200
    assert http.get("/api/models/activations", headers=admin).status_code == 200
    assert http.get("/api/health/db").json()["revision"] == "0003_live_data_rollback"
