"""WebSocket: first-message authentication and real pipeline events."""
import pytest

from tests.conftest import VALID_INPUT


def _receive_until(ws, name, limit=30):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["event"] == name:
            return msg
    raise AssertionError(f"{name} not received")


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": "invalid"})
        assert ws.receive_json()["event"] == "AUTH_FAILED"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_streams_prediction_events(client, make_user):
    u = make_user()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": u["token"]})
        hello = ws.receive_json()
        assert hello["event"] == "CONNECTED" and hello["data"]["role"] == "user"
        assert "simulation" not in hello["data"]["status"]          # users only see the live stream
        ws.send_json({"type": "ping"})
        assert _receive_until(ws, "PONG")["event"] == "PONG"
        p = client.post("/api/predict", json={**VALID_INPUT, "actual_category": "Tops"},
                        headers=u["headers"]).json()["prediction"]
        created = _receive_until(ws, "PREDICTION_CREATED")
        assert created["data"]["prediction_id"] == p["id"] and created["stream"] == "live"
        result = _receive_until(ws, "PREDICTION_RESULT")
        assert result["data"]["actual"] == "Tops" and result["data"]["status"] in ("STABLE", "WARNING", "DRIFT")


def test_staff_receive_drift_events(client, admin):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": admin["token"]})
        assert "simulation" in ws.receive_json()["data"]["status"]
        client.post("/api/simulation/reset", json={}, headers=admin["headers"])
        client.post("/api/simulation/trend-change", headers=admin["headers"])
        for _ in range(40):
            r = client.post("/api/simulation/step", json={"count": 25}, headers=admin["headers"]).json()
            if r["drift_events"]:
                break
        drift = _receive_until(ws, "DRIFT_DETECTED", limit=5000)
        assert drift["detector"] and drift["model_version"] == "v1.0"
        assert _receive_until(ws, "MODEL_VERSION_CREATED", limit=5000)["model_version"] == "v2.0"
