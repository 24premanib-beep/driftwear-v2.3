"""Drift detection → adaptation → model registry, through the HTTP API (simulation stream)."""
import time


def _until_drift(client, headers, max_batches=40):
    for _ in range(max_batches):
        r = client.post("/api/simulation/step", json={"count": 25, "stop_on_drift": True}, headers=headers)
        assert r.status_code == 200, r.text
        if r.json()["drift_events"]:
            return r.json()
    raise AssertionError("no drift detected")


def test_drift_adaptation_and_registry_end_to_end(client, admin, make_user):
    analyst = make_user("analyst")
    h = analyst["headers"]
    r = client.post("/api/simulation/reset", json={"regenerate": False}, headers=admin["headers"])
    assert r.status_code == 200 and r.json()["model_version"] == "v1.0" and r.json()["processed"] == 0
    assert client.post("/api/simulation/trend-change", headers=h).status_code == 200
    res = _until_drift(client, h)
    assert res["model_version"] == "v2.0" and res["stopped_on_drift"]

    events = client.get("/api/drift/events?stream=simulation", headers=h).json()
    e = events[0]
    assert e["detector"] and e["previous_model_version"] == "v1.0" and e["new_model_version"] == "v2.0"
    assert e["window_size"] >= 10 and e["detection_delay"] >= 0 and e["action"] == "Model Updated"

    models = client.get("/api/models?stream=simulation", headers=h).json()["items"]
    v2 = next(m for m in models if m["version"] == "v2.0")
    assert v2["is_active"] and v2["kind"] == "drift" and v2["drift_event_id"] == e["id"]
    assert "model_path" not in v2 and v2["training_records"] == e["window_size"]
    detail = client.get("/api/models/v2.0?stream=simulation", headers=h).json()
    assert detail["drift_event"]["id"] == e["id"] and len(detail["feature_importance"]) > 0
    assert client.get("/api/models/current?stream=simulation", headers=h).json()["version"] == "v2.0"
    assert client.get("/api/models/v9.9?stream=simulation", headers=h).status_code == 404
    assert client.get("/api/models/not-a-version", headers=h).status_code == 422

    dash = client.get("/api/dashboard?stream=simulation", headers=h).json()
    assert dash["kpis"]["model_version"] == "v2.0" and dash["kpis"]["drift_events"] == 1
    assert dash["series"] and dash["markers"]["drifts"][0]["to_version"] == "v2.0"
    stats = client.get("/api/drift/statistics?stream=simulation", headers=h).json()
    assert stats["summary"]["drift_events"] == 1 and stats["status_counts"]["DRIFT"] == 1
    perf = client.get("/api/performance?stream=simulation", headers=h).json()
    assert len(perf["confusion_matrix"]["matrix"]) == 6 and perf["by_version"]
    sim_history = client.get("/api/predictions?stream=simulation&page_size=5", headers=h).json()
    processed = client.get("/api/drift/status?stream=simulation", headers=h).json()["records_processed"]
    assert sim_history["total"] == processed and sim_history["items"][0]["source"] == "simulation"


def test_admin_adapt_and_rollback(client, admin, make_user):
    h = admin["headers"]
    client.post("/api/simulation/reset", json={}, headers=h)
    client.post("/api/simulation/step", json={"count": 40, "stop_on_drift": False}, headers=h)
    r = client.post("/api/models/adapt", json={"stream": "simulation"}, headers=h)
    assert r.status_code == 200 and r.json()["version"] == "v1.1" and r.json()["kind"] == "manual"
    # going back to an older version is a rollback, so it needs a reason (422 without one, nothing changes)
    r = client.post("/api/models/v1.0/activate", json={"stream": "simulation"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "reason"
    r = client.post("/api/models/v1.0/activate", json={"stream": "simulation", "reason": "test rollback"}, headers=h)
    assert r.status_code == 200 and r.json()["active_version"] == "v1.0"
    assert client.post("/api/models/v1.0/activate", json={"stream": "simulation"}, headers=h).status_code == 409
    r = client.post("/api/models/adapt", json={"stream": "simulation"}, headers=h)
    assert r.json()["version"] == "v1.2"                         # v1.1 is never overwritten
    user = make_user()
    assert client.post("/api/models/adapt", json={"stream": "simulation"},
                       headers=user["headers"]).status_code == 403


def test_detector_switch(client, admin):
    h = admin["headers"]
    available = client.get("/api/drift/status?stream=simulation", headers=h).json()["available_detectors"]
    r = client.post("/api/drift/detector", json={"stream": "simulation", "detector": "ADWIN"}, headers=h)
    if "ADWIN" in available:
        assert r.status_code == 200 and r.json()["detector"] == "ADWIN"
        client.post("/api/drift/detector", json={"stream": "simulation", "detector": "DDM"}, headers=h)
    else:
        assert r.status_code == 422                              # River not installed
    assert client.post("/api/drift/detector", json={"stream": "simulation", "detector": "XYZ"},
                       headers=h).status_code == 422


def test_background_simulation_runner_pauses_on_drift(client, admin):
    h = admin["headers"]
    client.post("/api/simulation/reset", json={}, headers=h)
    client.post("/api/simulation/trend-change", headers=h)
    r = client.post("/api/simulation/start", json={"speed": 10, "pause_on_drift": True}, headers=h)
    assert r.status_code == 200 and r.json()["running"] is True
    deadline = time.time() + 60
    state = r.json()
    while time.time() < deadline and state["running"]:
        time.sleep(0.2)
        state = client.get("/api/simulation/state", headers=h).json()
    assert not state["running"] and "drift" in (state["last_message"] or "").lower()
    assert client.post("/api/simulation/pause", headers=h).json()["running"] is False


def test_users_cannot_see_simulation(client, make_user):
    u = make_user()
    assert client.get("/api/dashboard?stream=simulation", headers=u["headers"]).status_code == 403
    assert client.post("/api/simulation/step", json={"count": 1}, headers=u["headers"]).status_code == 403
    assert client.get("/api/drift/status?stream=simulation", headers=u["headers"]).json()["mode"] == "live"
