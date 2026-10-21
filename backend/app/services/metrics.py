"""
Runtime metrics measured inside this API process (no database, no web framework).

* RequestMetrics: every /api request's status and latency, recorded by the request middleware.
* ResourceSampler: process CPU, process / system memory and load average, read from the operating system.
* latency_summary: avg / p50 / p95 / max of a list of durations.

These numbers are real but per process and since it started; the System monitoring page says so. Anything the
platform cannot measure (e.g. memory on an OS without /proc and without psutil) is returned as None, which the
UI shows as "N/A". Nothing here is estimated.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone

_ID_SEGMENT = re.compile(r"^(\d+|v\d+\.\d+)$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def latency_summary(values) -> dict:
    vals = sorted(float(v) for v in values)
    n = len(vals)
    if not n:
        return {"n": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}

    def q(p: float) -> float:
        return vals[min(n - 1, int(round(p * (n - 1))))]
    return {"n": n, "avg_ms": round(sum(vals) / n, 2), "p50_ms": round(q(0.50), 2), "p95_ms": round(q(0.95), 2),
            "max_ms": round(vals[-1], 2)}


def route_group(path: str) -> str:
    """/api/predictions/42 → /api/predictions/{id}; /api/models/v2.0/activate → /api/models/{id}/activate."""
    return "/".join("{id}" if _ID_SEGMENT.match(p) else p for p in path.split("/"))[:80]


class RequestMetrics:
    """API request counters (since start) and a rolling window of recent requests for latency."""

    def __init__(self, window: int = 2000, clock=time.time):
        self._lock = threading.Lock()
        self._recent: deque[tuple[float, str, int, float]] = deque(maxlen=window)
        self._totals: Counter = Counter()
        self._clock = clock
        self.started_at = _now_iso()

    def record(self, method: str, path: str, status: int, duration_ms: float) -> None:
        # health probes run every few seconds from load balancers and would drown the real traffic
        if not path.startswith("/api") or path.startswith("/api/health"):
            return
        with self._lock:
            self._totals["total"] += 1
            self._totals[f"{int(status) // 100}xx"] += 1
            self._recent.append((self._clock(), f"{method} {route_group(path)}", int(status), float(duration_ms)))

    def snapshot(self, top: int = 8) -> dict:
        with self._lock:
            recent = list(self._recent)
            totals = dict(self._totals)
        now = self._clock()
        total = totals.get("total", 0)
        groups: dict[str, list[tuple[int, float]]] = {}
        for _, group, status, ms in recent:
            groups.setdefault(group, []).append((status, ms))
        endpoints = sorted(({"endpoint": g, "requests": len(v), "server_errors": sum(1 for s, _ in v if s >= 500),
                             **latency_summary([ms for _, ms in v])} for g, v in groups.items()),
                           key=lambda e: -e["requests"])[:top]
        by_status = {k: totals.get(k, 0) for k in ("2xx", "3xx", "4xx", "5xx")}
        return {
            "since": self.started_at, "total_requests": total, "by_status": by_status,
            "server_error_rate": round(by_status["5xx"] / total, 4) if total else None,
            "client_error_rate": round(by_status["4xx"] / total, 4) if total else None,
            "requests_last_minute": sum(1 for r in recent if now - r[0] <= 60),
            "latency": latency_summary([r[3] for r in recent]), "window": len(recent), "endpoints": endpoints,
            "note": "API requests under /api (health probes excluded) since this process started; "
                    "latency over the most recent requests.",
        }


def _read_meminfo() -> tuple[float | None, float | None]:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = float(rest.split()[0]) / 1024          # kB → MB
        return info.get("MemTotal"), info.get("MemAvailable")
    except (OSError, ValueError, IndexError):
        return None, None


def _read_rss_mb() -> float | None:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 20
    except (OSError, ValueError, IndexError, AttributeError):
        return None


class ResourceSampler:
    """Process CPU % (of one core, averaged between samples), memory and load, from psutil if installed,
    otherwise from os.times() and /proc. Unavailable values are None."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._prev = (clock(), self._cpu_seconds())
        self._last: tuple[float, float] | None = None

    @staticmethod
    def _cpu_seconds() -> float:
        t = os.times()
        return t.user + t.system

    def _cpu(self) -> tuple[float | None, float | None]:
        now, cpu = self._clock(), self._cpu_seconds()
        with self._lock:
            prev_wall, prev_cpu = self._prev
            span = now - prev_wall
            if span >= 1.0:                         # shorter windows are too noisy to be meaningful
                self._last = (round(max(0.0, (cpu - prev_cpu) / span * 100), 1), round(span, 1))
                self._prev = (now, cpu)
            return self._last if self._last else (None, None)

    @staticmethod
    def _memory() -> dict:
        try:
            import psutil
            vm = psutil.virtual_memory()
            return {"process_memory_mb": round(psutil.Process().memory_info().rss / 2 ** 20, 1),
                    "system_memory_total_mb": round(vm.total / 2 ** 20), "system_memory_used_percent": round(vm.percent, 1),
                    "source": "psutil"}
        except ImportError:
            pass
        except Exception:  # noqa: BLE001 - a sandbox may forbid reading process info
            return {"process_memory_mb": None, "system_memory_total_mb": None, "system_memory_used_percent": None,
                    "source": None}
        rss = _read_rss_mb()
        total, available = _read_meminfo()
        used = round((1 - available / total) * 100, 1) if total and available is not None else None
        return {"process_memory_mb": None if rss is None else round(rss, 1),
                "system_memory_total_mb": None if total is None else round(total), "system_memory_used_percent": used,
                "source": "procfs" if rss is not None or total is not None else None}

    def sample(self) -> dict:
        cpu, basis = self._cpu()
        try:
            load = round(os.getloadavg()[0], 2)
        except (AttributeError, OSError):
            load = None
        mem = self._memory()
        return {
            "process_cpu_percent": cpu, "cpu_window_seconds": basis, "cpu_count": os.cpu_count(),
            "load_average_1m": load, **mem,
            "note": "CPU is this API process as a % of one core, averaged since the previous sample. Memory and load "
                    "are what the operating system reports (inside a container this is the host's view).",
        }
