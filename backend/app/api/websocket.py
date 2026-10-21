"""
WebSocket endpoint: /ws

Protocol
  1. client connects
  2. client sends {"type": "auth", "token": "<JWT>"} within 10 s
     (the token is not put in the URL, so it never lands in access logs)
  3. server replies {"event": "CONNECTED", ...} with a status snapshot
  4. server pushes pipeline events; client may send {"type": "ping"} → {"event": "PONG"}
Close codes: 4401 authentication failed / session ended.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.dependencies import user_from_token
from app.errors import AppError

router = APIRouter()
log = logging.getLogger(__name__)
AUTH_TIMEOUT_SECONDS = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    app = websocket.app
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        msg = json.loads(raw)
        if not isinstance(msg, dict) or msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
            raise ValueError("expected auth message")

        def authenticate():
            with app.state.db.session() as s:
                u = user_from_token(msg["token"], s, app.state.settings)
                return u.id, u.role, u.name
        user_id, role, name = await asyncio.to_thread(authenticate)
    except (asyncio.TimeoutError, ValueError, AppError, json.JSONDecodeError) as exc:
        reason = exc.message if isinstance(exc, AppError) else "Authentication required"
        try:
            await websocket.send_json({"event": "AUTH_FAILED", "timestamp": _now(), "message": reason, "data": {}})
            await websocket.close(code=4401)
        except Exception:  # noqa: BLE001
            pass
        return
    except WebSocketDisconnect:
        return

    manager = app.state.ws_manager
    client = await manager.add(websocket, user_id, role)
    try:
        pipeline = app.state.pipeline
        snapshot = {"live": pipeline.status("live")}
        if role in ("analyst", "admin") and pipeline.simulation_enabled:
            snapshot["simulation"] = pipeline.status("simulation")
        await websocket.send_json({"event": "CONNECTED", "stream": None, "timestamp": _now(),
                                   "message": f"Connected as {name} ({role}).",
                                   "data": {"user_id": user_id, "role": role, "status": snapshot}})
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"event": "PONG", "timestamp": _now(), "message": "", "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("WebSocket error")
    finally:
        await manager.remove(client)
