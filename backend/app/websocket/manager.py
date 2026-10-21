"""
WebSocket connection registry.

Duck-typed on purpose (anything with `send_json`), so it is independent of the
web framework and easy to test. Each connection remembers the user's id and
role; events are only delivered to connections allowed to see them.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass
from typing import Any

from app.services.events import Event, can_receive

log = logging.getLogger(__name__)
SEND_TIMEOUT_SECONDS = 5.0


@dataclass
class Client:
    id: int
    ws: Any
    user_id: int
    role: str


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[int, Client] = {}
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._clients)

    async def add(self, ws: Any, user_id: int, role: str) -> Client:
        async with self._lock:
            client = Client(next(self._ids), ws, user_id, role)
            self._clients[client.id] = client
        log.info("WebSocket connected: user=%s role=%s (open=%d)", user_id, role, len(self._clients))
        return client

    async def remove(self, client: Client) -> None:
        async with self._lock:
            self._clients.pop(client.id, None)
        log.info("WebSocket disconnected: user=%s (open=%d)", client.user_id, len(self._clients))

    async def update_role(self, user_id: int, role: str) -> None:
        async with self._lock:
            for c in self._clients.values():
                if c.user_id == user_id:
                    c.role = role

    async def close_user(self, user_id: int, reason: str = "") -> None:
        """Close every socket of a user (logout, account disabled)."""
        async with self._lock:
            targets = [c for c in self._clients.values() if c.user_id == user_id]
            for c in targets:
                self._clients.pop(c.id, None)
        for c in targets:
            try:
                await c.ws.close(code=4401, reason=reason[:100])
            except Exception:  # noqa: BLE001 - already closed
                pass

    async def broadcast(self, event: Event) -> None:
        targets = [c for c in list(self._clients.values()) if can_receive(event.audience, c.user_id, c.role)]
        if not targets:
            return
        results = await asyncio.gather(
            *(asyncio.wait_for(c.ws.send_json(event.payload), SEND_TIMEOUT_SECONDS) for c in targets),
            return_exceptions=True)
        for c, res in zip(targets, results):
            if isinstance(res, Exception):
                await self.remove(c)
