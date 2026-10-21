"""HTTP: real-time events, health endpoints, System monitoring, data drift, model comparison and health,
audit log, rate limiting and the authorization of every new endpoint (FastAPI + SQLite)."""
import time
import uuid

from tests.conftest import VALID_INPUT

EVENT = {"customer_id": "C1023", "previous_category": "Tops", "purchase_frequency": 4, "recency": 12,
         "season": "Summer", "month": 6, "price": 1299, "discount": 20, "customer_preference": "Casual"}


def _eid():
    return f"evt-{uuid.uuid4().hex[:12]}"


def test_ingest_event_then_outcome(client, make_user):
    u = make_user()
    eid = _eid()
    r = client.post("/api/events/purchase", json={**EVENT, "event_id": eid}, headers=u["headers"])
    assert r.status_code == 201, r.text
    body = r.json()
    p = body["prediction"]
    assert body["event_id"] == eid and p["source"] == "event" and p["event_id"] == eid and body["outcome"] is None
    assert p["features"]["Season"] == "Summer" and p["features"]["Month"] == 6        # explicit values respected
    assert body["explanation"]["predicted"] == p["predicted_category"] and len(body["explanation"]["contributions"]) == 8
    assert [s["stage"] for s in body["pipeline"]][:4] == ["validated", "stored", "features", "prediction"]
    assert next(s for s in body["pipeline"] if s["stage"] == "outcome")["status"] == "pending"

    dup = client.post("/api/events/purchase", json={**EVENT, "event_id": eid}, headers=u["headers"])
    assert dup.status_code == 409 and dup.json()["error"]["details"]["prediction_id"] == p["id"]

    out = client.post("/api/events/outcome", json={"event_id": eid, "actual_category": "Bottoms"}, headers=u["headers"])
    assert out.status_code == 200, out.text
    o = out.json()
    assert o["prediction_id"] == p["id"] and o["outcome"]["actual_category"] == "Bottoms"
    assert {s["stage"] for s in o["pipeline"]} == {"outcome", "error", "drift_check", "adaptation"}
    assert client.post("/api/events/outcome", json={"event_id": eid, "actual_category": "Tops"},
                       headers=u["headers"]).status_code == 409
    other = make_user()
    assert client.post("/api/events/outcome", json={"event_id": eid, "actual_category": "Tops"},
                       headers=other["headers"]).status_code == 404
    stored = client.get(f"/api/predictions/{p['id']}", headers=u["headers"]).json()
    assert stored["explanation"]["predicted"] == stored["predicted_category"] and stored["event_id"] == eid
    found = client.get(f"/api/predictions?search={eid}", headers=u["headers"]).json()
    assert found["total"] == 1 and found["items"][0]["id"] == p["id"]


def test_event_with_known_outcome_and_validation(client, make_user):
    h = make_user()["headers"]
    r = client.post("/api/events/purchase", json={**EVENT, "event_id": _eid(), "actual_category": "Tops"}, headers=h)
    assert r.status_code == 201 and r.json()["outcome"]["actual_category"] == "Tops"
    assert next(s for s in r.json()["pipeline"] if s["stage"] == "drift_check")["status"] == "done"
    for bad in ({**EVENT, "price": -5}, {**EVENT, "event_id": "bad id!"}, {**EVENT, "unexpected": 1},
                {**EVENT, "customer_preference": "Grunge"}, {**EVENT, "month": 13}):
        assert client.post("/api/events/purchase", json=bad, headers=h).status_code == 422, bad
    assert client.post("/api/events/outcome", json={"actual_category": "Tops"}, headers=h).status_code == 422
    assert client.post("/api/events/outcome", json={"event_id": "x1", "prediction_id": 1, "actual_category": "Tops"},
                       headers=h).status_code == 422
    assert client.post("/api/events/purchase", json=EVENT).status_code == 401


def test_prediction_rate_limit(client, make_user):
    from app.auth.rate_limit import SlidingWindowLimiter
    u = make_user()
    original = client.app.state.prediction_limiter
    client.app.state.prediction_limiter = SlidingWindowLimiter(2, 60)
    try:
        codes = [client.post("/api/predict", json=VALID_INPUT, headers=u["headers"]).status_code for _ in range(3)]
    finally:
        client.app.state.prediction_limiter = original
    assert codes == [201, 201, 429]


def test_predict_returns_explanation(client, make_user):
    r = client.post("/api/predict", json=VALID_INPUT, headers=make_user()["headers"])
    assert r.status_code == 201
    exp = r.json()["explanation"]
    assert exp["predicted"] == r.json()["prediction"]["predicted_category"]
    assert abs(sum(c["share"] for c in exp["contributions"]) - 1) < 0.01


def test_health_endpoints(client):
    for path in ("/health", "/api/health"):
        r = client.get(path)
        assert r.status_code == 200 and r.json()["pipeline"] == "ready" and r.json()["database"] is True
        assert set(r.json()["components"]) == {"database", "ml_pipeline", "websocket", "model_storage"}
    for path in ("/health/db", "/api/health/db"):
        db = client.get(path).json()
        assert db["status"] == "healthy" and db["latency_ms"] is not None
    ml = client.get("/health/ml").json()
    assert ml["status"] in ("healthy", "warning") and ml["pipeline"]["streams"]["live"]["model_version"]
    assert ml["model_storage"]["active_models"]["live"] is True
    ws = client.get("/api/health/websocket").json()
    assert ws["status"] == "healthy" and "clients" in ws


def test_system_monitoring(client, admin, make_user):
    r = client.get("/api/system/monitoring", headers=admin["headers"])
    assert r.status_code == 200, r.text
    m = r.json()
    assert set(m["components"]) == {"api", "database", "websocket", "ml_pipeline", "model_storage"}
    assert m["components"]["database"]["status"] == "healthy"
    for k in ("records_processed", "predictions_made", "outcomes_received", "drift_events", "models_created",
              "adaptations", "failed_jobs", "last_prediction_at", "last_drift_check_at", "last_adaptation_at"):
        assert k in m["pipeline_metrics"], k
    assert m["current_model"]["algorithm"] == "RandomForestClassifier" and m["current_model"]["version"]
    assert m["model_health"]["band"] in ("HEALTHY", "AT_RISK", "DEGRADED")
    assert client.get("/api/system/monitoring", headers=make_user()["headers"]).status_code == 403


def test_data_drift_comparison_and_model_health(client, admin, make_user):
    h = admin["headers"]
    client.post("/api/simulation/reset", json={}, headers=h)
    client.post("/api/simulation/step", json={"count": 120, "stop_on_drift": False}, headers=h)
    d = client.get("/api/drift/data?stream=simulation&window=100", headers=h)
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["status"] in ("STABLE", "WARNING", "DRIFT") and body["triggers_adaptation"] is False
    assert body["reference"]["source"] == "historical" and body["current"]["n"] == 100
    assert {f["feature"] for f in body["features"]} >= {"Price", "Discount", "Customer_Preference"}
    assert client.get("/api/drift/data?stream=simulation&reference=active", headers=h).status_code == 200

    v11 = client.post("/api/models/adapt", json={"stream": "simulation"}, headers=h).json()["version"]
    c = client.get(f"/api/models/compare?stream=simulation&a=v1.0&b={v11}", headers=h)
    assert c.status_code == 200, c.text
    cmp = c.json()
    assert cmp["a"]["version"] == "v1.0" and cmp["b"]["version"] == v11 and cmp["b"]["parent_version"] == "v1.0"
    assert set(cmp["diff"]["validation"]) == {"accuracy", "precision", "recall", "f1", "error_rate"}
    assert client.get("/api/models/compare?stream=simulation&a=v1.0&b=v9.9", headers=h).status_code == 404
    assert client.get("/api/models/compare?stream=simulation&a=v1.0&b=latest", headers=h).status_code == 422

    mh = client.get("/api/models/health?stream=simulation", headers=h).json()
    assert mh["band"] in ("HEALTHY", "AT_RISK", "DEGRADED") and mh["metrics"]["model_version"] == v11
    user = make_user()
    assert client.get("/api/models/health", headers=user["headers"]).status_code == 200
    assert client.get("/api/models/health?stream=simulation", headers=user["headers"]).status_code == 403
    assert client.get("/api/drift/data", headers=user["headers"]).status_code == 403
    assert client.get("/api/models/compare?a=v1.0&b=v1.0", headers=user["headers"]).status_code == 403
    dash = client.get("/api/dashboard?stream=simulation", headers=h).json()
    assert dash["health"]["band"] and len(dash["cycle"]) == 6 and "shadows" in dash["detectors"]
    stats = client.get("/api/drift/statistics?stream=simulation", headers=h).json()
    assert "impact" in stats and stats["definition"].startswith("Concept drift")


def test_audit_log_records_user_and_system_actions(client, admin, make_user):
    h = admin["headers"]
    client.post("/api/simulation/reset", json={}, headers=h)
    client.post("/api/drift/detector", json={"stream": "simulation", "detector": "DDM"}, headers=h)
    client.post("/api/simulation/trend-change", headers=h)
    for _ in range(40):
        if client.post("/api/simulation/step", json={"count": 25}, headers=h).json()["drift_events"]:
            break
    client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong12345"})

    r = client.get("/api/audit-logs?page_size=100", headers=h)
    assert r.status_code == 200
    actions = {i["action"] for i in r.json()["items"]}
    assert {"auth.login", "simulation.reset", "config.detector_changed", "simulation.trend_changed"} <= actions
    reset = client.get("/api/audit-logs?action=simulation.reset", headers=h).json()["items"][0]
    assert reset["user"]["id"] == admin["id"] and reset["actor"] and reset["ip_address"] and reset["severity"] == "warning"
    prefix = client.get("/api/audit-logs?action=auth.*", headers=h).json()["items"]
    assert prefix and all(i["action"].startswith("auth.") for i in prefix)
    failed = client.get("/api/audit-logs?action=auth.login_failed", headers=h).json()["items"]
    assert failed and "Wrong12345" not in str(failed[0]) and failed[0]["severity"] == "warning"

    deadline = time.time() + 10                     # system events are written by the event-bus subscriber
    system = []
    while time.time() < deadline and not system:
        system = client.get("/api/audit-logs?system=true&action=drift.detected", headers=h).json()["items"]
        time.sleep(0.1)
    assert system and system[0]["actor"] == "System" and system[0]["user"] is None
    assert system[0]["severity"] == "critical" and system[0]["stream"] == "simulation"
    facets = client.get("/api/audit-logs/facets", headers=h).json()
    assert "drift.detected" in facets["actions"] and facets["severities"] == ["info", "warning", "critical"]
    assert client.get("/api/audit-logs", headers=make_user("analyst")["headers"]).status_code == 403
    assert client.get("/api/audit-logs?action=DROP TABLE", headers=h).status_code == 422
