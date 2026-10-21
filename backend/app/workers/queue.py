"""
Task queue for everything that changes drift-engine state.

Why a single ordered queue: the drift detector must see prediction errors one at
a time, in order, from exactly one writer. Running two outcomes concurrently
would let both observe the same detector state (double drift detection, two
"v2.0" models). The queue guarantees that, while the CPU-bound work (retraining,
~1 s) runs in a worker thread so the API stays responsive.

`TaskQueue` is the seam for a distributed queue later (Celery/RQ/Arq). Moving to
one requires persisting River detector state between tasks, which is why it is
not used yet: retraining is fast enough that the in-process queue is simpler
and has fewer failure modes. See README "Scaling".
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)


class TaskQueue(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def submit(self, fn: Callable[[], Any], *, name: str = "task", timeout: float | None = None) -> Any: ...
    @property
    def pending(self) -> int: ...
    @property
    def stats(self) -> dict: ...


@dataclass
class _Job:
    fn: Callable[[], Any]
    name: str
    future: asyncio.Future = field(repr=False)


class InProcessQueue:
    """FIFO, one job at a time; each job's sync function runs in a thread."""

    def __init__(self, maxsize: int = 1000):
        self._queue: asyncio.Queue[_Job | None] | None = None
        self._task: asyncio.Task | None = None
        self._maxsize = maxsize
        # completed: finished normally · rejected: expected business errors (4xx, e.g. "already labeled")
        # failed: unexpected errors or 5xx (e.g. a database write failed) — shown on System monitoring
        self._stats = {"completed": 0, "rejected": 0, "failed": 0, "running": None,
                       "last_failure": None, "last_failure_at": None, "last_completed_at": None}

    @property
    def stats(self) -> dict:
        return {**self._stats, "pending": self.pending}

    @property
    def pending(self) -> int:
        return self._queue.qsize() if self._queue else 0

    async def start(self) -> None:
        self._queue = asyncio.Queue(self._maxsize)
        self._task = asyncio.create_task(self._worker(), name="pipeline-worker")

    async def stop(self) -> None:
        if self._queue is None or self._task is None:
            return
        await self._queue.put(None)
        try:
            await asyncio.wait_for(self._task, timeout=30)
        except asyncio.TimeoutError:  # pragma: no cover
            self._task.cancel()

    async def submit(self, fn: Callable[[], Any], *, name: str = "task", timeout: float | None = None) -> Any:
        if self._queue is None:
            raise RuntimeError("Task queue is not running")
        fut = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait(_Job(fn, name, fut))
        except asyncio.QueueFull as exc:
            raise RuntimeError("The pipeline is busy; try again shortly") from exc
        # shield: if the HTTP request times out, the job still finishes and stays consistent
        return await asyncio.wait_for(asyncio.shield(fut), timeout) if timeout else await fut

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            if job is None:
                break
            self._stats["running"] = job.name
            try:
                result = await asyncio.to_thread(job.fn)
                self._stats["completed"] += 1
                self._stats["last_completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if not job.future.done():
                    job.future.set_result(result)
            except BaseException as exc:  # noqa: BLE001 - surfaced to the caller
                status = getattr(exc, "status_code", None)
                if status is None:                      # expected AppErrors are not logged as crashes
                    log.exception("Pipeline task '%s' failed", job.name)
                if status is None or status >= 500:
                    self._stats["failed"] += 1
                    self._stats["last_failure"] = job.name
                    self._stats["last_failure_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                else:
                    self._stats["rejected"] += 1
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                self._stats["running"] = None
