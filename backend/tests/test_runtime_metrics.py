"""Runtime metrics for System monitoring (app/services/metrics.py): measured, or None — never invented."""
import builtins

import app.services.metrics as M
from app.services.metrics import RequestMetrics, ResourceSampler, latency_summary, route_group


def test_latency_summary_and_route_groups():
    assert latency_summary([10, 20, 30, 40, 100]) == {"n": 5, "avg_ms": 40.0, "p50_ms": 30.0, "p95_ms": 100.0,
                                                      "max_ms": 100.0}
    assert latency_summary([]) == {"n": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    assert route_group("/api/predictions/42") == "/api/predictions/{id}"
    assert route_group("/api/models/v2.0/activate") == "/api/models/{id}/activate"


def test_request_metrics_count_real_api_requests_only():
    t = [1000.0]
    m = RequestMetrics(clock=lambda: t[0])
    m.record("GET", "/api/dashboard", 200, 12.0)
    m.record("POST", "/api/events/purchase", 201, 30.0)
    m.record("POST", "/api/events/purchase", 422, 5.0)
    m.record("GET", "/api/models/v1.0", 500, 50.0)
    m.record("GET", "/health", 200, 1.0)              # load-balancer probes are not API traffic
    m.record("GET", "/api/health/db", 200, 1.0)
    t[0] += 120
    m.record("GET", "/api/dashboard", 200, 8.0)
    snap = m.snapshot()
    assert snap["total_requests"] == 5 and snap["by_status"] == {"2xx": 3, "3xx": 0, "4xx": 1, "5xx": 1}
    assert snap["server_error_rate"] == 0.2 and snap["requests_last_minute"] == 1 and snap["latency"]["n"] == 5
    top = {e["endpoint"]: e for e in snap["endpoints"]}
    assert top["POST /api/events/purchase"]["requests"] == 2 and top["GET /api/models/{id}"]["server_errors"] == 1
    assert RequestMetrics().snapshot()["server_error_rate"] is None             # no traffic: N/A, not 0 %


def test_resource_sampler_measures_or_reports_none(monkeypatch):
    t = [0.0]
    s = ResourceSampler(clock=lambda: t[0])
    assert s.sample()["process_cpu_percent"] is None                           # < 1 s window: not measured yet
    t[0] = 5.0
    snap = s.sample()
    assert snap["process_cpu_percent"] >= 0 and snap["cpu_window_seconds"] == 5.0 and snap["cpu_count"]
    assert snap["source"] in ("psutil", "procfs", None)
    real_import = builtins.__import__

    def without_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_psutil)
    procfs = ResourceSampler._memory()
    assert procfs["source"] in ("procfs", None)
    monkeypatch.setattr(M, "_read_rss_mb", lambda: None)
    monkeypatch.setattr(M, "_read_meminfo", lambda: (None, None))
    assert ResourceSampler._memory() == {"process_memory_mb": None, "system_memory_total_mb": None,
                                         "system_memory_used_percent": None, "source": None}
