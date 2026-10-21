"""
Real-time events.

Every event is produced by an actual pipeline step (a stored prediction, a
detector state change, a retrain call, a committed model version). Nothing here
generates activity on its own.

Wire format (what WebSocket clients receive):
    {
      "event": "DRIFT_DETECTED",
      "stream": "live",                     # or "simulation"
      "timestamp": "2026-10-01T12:00:00+00:00",
      "message": "Concept drift detected by DDM. Model adaptation initiated.",
      "detector": "DDM", "model_version": "v1.0",   # when relevant
      "data": {...}
    }

Audience (server-side only, never sent): who may receive the event.
    "all"          every signed-in user
    "staff"        analysts and admins
    ("owner", id)  that user plus analysts and admins
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Union

log = logging.getLogger(__name__)

Audience = Union[str, tuple[str, int]]

PREDICTION_CREATED = "PREDICTION_CREATED"
PREDICTION_RESULT = "PREDICTION_RESULT"
WARNING_DETECTED = "WARNING_DETECTED"
STATUS_CHANGED = "STATUS_CHANGED"
DRIFT_DETECTED = "DRIFT_DETECTED"
ADAPTATION_STARTED = "ADAPTATION_STARTED"
ADAPTATION_COMPLETED = "ADAPTATION_COMPLETED"
ADAPTATION_FAILED = "ADAPTATION_FAILED"
MODEL_VERSION_CREATED = "MODEL_VERSION_CREATED"
MODEL_ACTIVATED = "MODEL_ACTIVATED"
PERFORMANCE_UPDATED = "PERFORMANCE_UPDATED"
DETECTOR_CHANGED = "DETECTOR_CHANGED"
DATA_UPLOADED = "DATA_UPLOADED"
RECORDS_PROCESSED = "RECORDS_PROCESSED"
SIMULATION_STATE = "SIMULATION_STATE"
TREND_CHANGED = "TREND_CHANGED"
SIMULATION_RESET = "SIMULATION_RESET"
PIPELINE_ERROR = "PIPELINE_ERROR"


@dataclass
class Event:
    payload: dict
    audience: Audience = "all"

    @property
    def name(self) -> str:
        return self.payload.get("event", "")


def to_plain(obj: Any) -> Any:
    """NumPy scalars → Python scalars (JSON and database drivers reject numpy types)."""
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    item = getattr(obj, "item", None)
    if item is not None and type(obj).__module__ == "numpy":
        return item()
    return obj


def make_event(name: str, stream: str | None, message: str, *, audience: Audience = "all",
               data: dict | None = None, **top: Any) -> Event:
    payload = {"event": name, "stream": stream,
               "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               "message": message}
    payload.update({k: to_plain(v) for k, v in top.items() if v is not None})
    payload["data"] = to_plain(data or {})
    return Event(payload, audience)


def can_receive(audience: Audience, user_id: int, role: str) -> bool:
    if audience == "all":
        return True
    staff = role in ("admin", "analyst")
    if audience == "staff":
        return staff
    if isinstance(audience, tuple) and audience[0] == "owner":
        return staff or audience[1] == user_id
    return False


Subscriber = Callable[[Event], Awaitable[None]]


class EventBus:
    """In-process pub/sub. publish() from the event loop; publish_threadsafe() from worker threads."""

    def __init__(self, history: int = 300):
        self.recent: deque[Event] = deque(maxlen=history)
        self._subscribers: list[Subscriber] = []
        self._queue: asyncio.Queue[Event] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self.published = 0
        self.last_event_at: str | None = None

    @property
    def running(self) -> bool:
        """True while the dispatcher task is alive (used by /health/websocket)."""
        return self._task is not None and not self._task.done()

    @property
    def backlog(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._dispatch(), name="event-bus")

    async def stop(self) -> None:
        if self._queue is not None:
            await self._queue.join()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def publish(self, event: Event) -> None:
        self.recent.append(event)
        self.published += 1
        self.last_event_at = event.payload.get("timestamp")
        if self._queue is not None:
            self._queue.put_nowait(event)

    def publish_threadsafe(self, event: Event) -> None:
        if self._loop is None:
            self.recent.append(event)
            return
        self._loop.call_soon_threadsafe(self.publish, event)

    def recent_for(self, user_id: int, role: str, limit: int = 50, stream: str | None = None) -> list[dict]:
        items = [e.payload for e in self.recent
                 if can_receive(e.audience, user_id, role) and (stream is None or e.payload.get("stream") == stream)]
        return items[-limit:][::-1]

    async def _dispatch(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                for fn in list(self._subscribers):
                    try:
                        await fn(event)
                    except Exception:  # noqa: BLE001 - one bad subscriber must not stop the bus
                        log.exception("Event subscriber failed for %s", event.name)
            finally:
                self._queue.task_done()
