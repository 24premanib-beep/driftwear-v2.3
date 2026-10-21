"""HTTP: the full demo on the simulation stream — drift → adaptation → before/during/after comparison →
monitoring → notifications → audit → rollback (authorization, validation, history, predictions)."""


def _drive_to_drift(client, h):
    client.post("/api/simulation/reset", json={}, headers=h)
    normal = client.post("/api/simulation/step", json={"count": 150, "stop_on_drift": True}, headers=h).json()
    assert normal["drift_events"] == []
    assert client.post("/api/simulation/trend-change", headers=h).status_code == 200
    for _ in range(25):
        r = client.post("/api/simulation/step", json={"count": 20, "stop_on_drift": True}, headers=h).json()
        if r["drift_events"]:
            return r
    raise AssertionError("no drift after the trend change")


def test_demo_scenario_over_http(client, admin, make_user):
    h = admin["headers"]
    drift = _drive_to_drift(client, h)
    assert drift["new_versions"] == ["v2.0"]
    recent = {e["event"] for e in client.get("/api/events/recent?stream=simulation&limit=300", headers=h).json()}
    assert {"WARNING_DETECTED", "DRIFT_DETECTED", "ADAPTATION_COMPLETED", "MODEL_VERSION_CREATED"} <= recent
    actions = {i["action"] for i in client.get("/api/audit-logs?stream=simulation&page_size=100",
                                               headers=h).json()["items"]}
    assert {"drift.detected", "model.retraining_completed", "model.created"} <= actions
    client.post("/api/simulation/step", json={"count": 60, "stop_on_drift": True}, headers=h)

    c = client.get("/api/performance/comparison?stream=simulation", headers=h)
    assert c.status_code == 200, c.text
    ev = c.json()["events"][0]
    assert ev["before"]["n"] and ev["during"]["n"] and ev["after"]["n"] >= 10
    assert ev["during"]["error_rate"] > ev["before"]["error_rate"] and ev["after"]["accuracy"] > ev["during"]["accuracy"]
    assert ev["detected_at"] and ev["detector"] and (ev["from_version"], ev["to_version"]) == ("v1.0", "v2.0")
    assert len(ev["story"]) == 6 and ev["predictions"]["after_adaptation"] > 0 and c.json()["series"]
    assert client.get("/api/performance/comparison", headers=make_user()["headers"]).status_code == 403

    m = client.get("/api/system/monitoring?stream=simulation", headers=h).json()
    status = client.get("/api/drift/status?stream=simulation", headers=h).json()
    assert m["ml"]["current_model_version"] == status["model_version"] and m["ml"]["drift_events"] == 1
    assert m["drift"]["confirmed_drifts"] == 1 and m["drift"]["warnings"] >= 1 and m["ml"]["adaptations"] >= 1
    assert m["ml"]["avg_latency_ms"] > 0 and m["ml"]["prediction_success_rate"] == 1.0
    assert m["performance"]["recent"]["n"] == 50 and m["data"]["simulation_events"] == status["records_processed"]
    assert m["system_health"]["api"]["total_requests"] > 0 and "process_cpu_percent" in m["system_health"]["resources"]
    for key in ("components", "pipeline_metrics", "current_model", "model_health", "detector"):
        assert key in m                                                     # earlier fields are unchanged

    active = status["model_version"]
    body = {"stream": "simulation", "to_version": "v1.0", "reason": "Demo rollback"}
    assert client.post("/api/models/rollback", json=body).status_code == 401
    assert client.post("/api/models/rollback", json=body, headers=make_user("analyst")["headers"]).status_code == 403
    assert client.post("/api/models/rollback", json={**body, "to_version": "v9.0"}, headers=h).status_code == 404
    assert client.post("/api/models/rollback", json={**body, "to_version": "latest"}, headers=h).status_code == 422
    # a rollback must say why: missing, blank or too-short reasons are refused before anything changes
    for bad in ({k: v for k, v in body.items() if k != "reason"}, {**body, "reason": "   "}, {**body, "reason": "x"}):
        r = client.post("/api/models/rollback", json=bad, headers=h)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed", r.text
    r = client.post("/api/models/v1.0/activate", json={"stream": "simulation"}, headers=h)    # older = rollback
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "reason", r.text
    assert client.get("/api/drift/status?stream=simulation", headers=h).json()["model_version"] == active
    r = client.post("/api/models/rollback", json=body, headers=h)
    assert r.status_code == 200, r.text
    rb = r.json()
    assert rb["rollback"] is True and (rb["previous_version"], rb["active_version"]) == (active, "v1.0")
    assert rb["activation"]["reason"] == "Demo rollback" and rb["activation"]["user_name"]
    assert client.post("/api/models/rollback", json={**body, "to_version": active}, headers=h).status_code == 409
    hist = client.get("/api/models/activations?stream=simulation", headers=h).json()
    assert hist["items"][0]["action"] == "rollback" and hist["timeline"][0]["action"] == "rollback"
    models = {v["version"]: v["is_active"] for v in client.get("/api/models?stream=simulation", headers=h).json()["items"]}
    assert models["v1.0"] is True and models[active] is False and "v2.0" in models        # nothing deleted
    client.post("/api/simulation/step", json={"count": 5, "stop_on_drift": True}, headers=h)
    latest = client.get("/api/predictions?stream=simulation&page_size=5", headers=h).json()["items"]
    assert all(p["model_version"] == "v1.0" for p in latest)
    entry = client.get("/api/audit-logs?action=model.rollback&page_size=5", headers=h).json()["items"][0]
    assert entry["user_id"] == admin["id"] and entry["details"]["reason"] == "Demo rollback"
    assert entry["details"]["from_version"] == active and entry["details"]["to_version"] == "v1.0"
    assert "MODEL_ACTIVATED" in {e["event"] for e in client.get("/api/events/recent?stream=simulation",
                                                                headers=h).json()}
    fwd = client.post(f"/api/models/{active}/activate", json={"stream": "simulation", "reason": "Back again"}, headers=h)
    assert fwd.status_code == 200 and fwd.json()["rollback"] is False and fwd.json()["reason"] == "Back again"
