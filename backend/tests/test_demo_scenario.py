"""
The final demo, end to end through the real pipeline (no HTTP, no database; the HTTP version of the same
scenario is tests/test_api_demo_scenario.py):

  1 initial model → 2 normal simulation (stable) → 3 trend change (errors rise) → 4 WARNING → DRIFT
  → 5 adaptation (new version) → 6 before / during / after comparison → 7 monitoring counters
  → 8 notifications → 9 audit trail → 10 rollback (previous version active, recorded, used for predictions)

Every number asserted here is computed from the outcomes the pipeline actually produced.
"""
import asyncio

from app.services import analytics, monitoring
from app.services.audit import AuditEventRecorder
from app.services.events import EventBus
from app.services.model_storage import LocalModelStorage
from app.services.pipeline import SIMULATION, PipelineService
from tests.memory_repository import MemoryRepository, drift_rows, outcome_rows, pipeline_metrics, version_rows

HEALTHY = {"api": {"status": "healthy", "uptime_seconds": 5}, "database": {"status": "healthy", "latency_ms": 1.0},
           "websocket": {"status": "healthy", "clients": 0, "events_published": 0}}


class Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event.payload)

    def names(self):
        return [e["event"] for e in self.events]


class MemoryAudit:
    def __init__(self):
        self.rows = []

    def record(self, action, **kw):
        self.rows.append({"action": action, **kw})


def test_full_demo_scenario(tmp_path):
    async def go():
        bus, col, audit = EventBus(), Collector(), MemoryAudit()
        bus.subscribe(col)
        bus.subscribe(AuditEventRecorder(audit))
        repo = MemoryRepository()
        svc = PipelineService(repo, LocalModelStorage(tmp_path / "models"), bus, tick_seconds=0.01)
        await bus.start()
        await svc.start()

        # 1. initial model
        st = svc.status(SIMULATION)
        assert (st["model_version"], st["status"], st["records_processed"]) == ("v1.0", "STABLE", 0)

        # 2. normal fashion period: stable, reasonable accuracy
        normal = await svc.simulate(150, stop_on_drift=True)
        assert normal["processed"] == 150 and normal["drift_events"] == []
        normal_accuracy = normal["correct"] / normal["processed"]
        assert normal_accuracy >= 0.5, normal_accuracy

        # 3 + 4. the trend changes: errors rise, the detector warns, then confirms drift
        await svc.trend_change()
        processed = correct = 0
        drift = None
        while drift is None and processed < 400:
            r = await svc.simulate(20, stop_on_drift=True)
            processed += r["processed"]
            correct += r["correct"]
            drift = r if r["drift_events"] else None
        assert drift is not None, "no drift after the trend change"
        assert correct / processed < normal_accuracy                       # prediction errors increased

        # 5. adaptation created a new version
        assert drift["new_versions"] == ["v2.0"] and svc.status(SIMULATION)["model_version"] == "v2.0"
        assert repo.get_version(SIMULATION, "v2.0")["kind"] == "drift"

        # 6. outcomes after the adaptation → before / during / after comparison
        await svc.simulate(60, stop_on_drift=True)
        rows, events, versions = (outcome_rows(repo, SIMULATION), drift_rows(repo, SIMULATION),
                                  version_rows(repo, SIMULATION))
        ev = analytics.drift_comparison(rows, events, versions)["events"][0]
        assert ev["before"]["n"] > 0 and ev["during"]["n"] > 0 and ev["after"]["n"] >= 10
        assert ev["during"]["error_rate"] > ev["before"]["error_rate"]
        assert ev["after"]["accuracy"] > ev["during"]["accuracy"] and ev["recovered"] is True
        assert (ev["from_version"], ev["to_version"]) == ("v1.0", "v2.0") and ev["detector"] == "DDM"
        assert ev["warning"] is not None and ev["warning"]["step"] <= ev["step"]       # WARNING came before DRIFT
        assert ev["trend_change"] is not None                                         # the data's own label
        assert ev["predictions"]["before_adaptation"] > 0 and ev["predictions"]["after_adaptation"] > 0

        # 7. monitoring reflects what happened
        status = svc.status(SIMULATION)
        sections = monitoring.compose_sections(
            status=status, rows=rows, events=events, versions=versions, metrics=pipeline_metrics(repo, SIMULATION),
            components=HEALTHY, predictions=svc.prediction_metrics(SIMULATION), data={}, api=None, resources=None)
        ml, drift_view = sections["ml"], sections["drift"]
        assert ml["total_predictions"] == status["records_processed"] == len(rows)
        assert ml["current_model_version"] == status["model_version"] and ml["drift_events"] == 1
        assert ml["adaptations"] >= 1 and ml["prediction_success_rate"] == 1.0 and ml["avg_latency_ms"] > 0
        assert 0 < ml["prediction_error_rate"] < 1
        assert drift_view["confirmed_drifts"] == 1 and drift_view["warnings"] >= 1
        assert sections["performance"]["recent"]["n"] == 50

        # 8. notifications were pushed for every step
        await asyncio.sleep(0.05)
        names = col.names()
        assert names.index("DRIFT_DETECTED") < names.index("ADAPTATION_COMPLETED") < names.index("MODEL_VERSION_CREATED")
        assert "WARNING_DETECTED" in names

        # 9. audit trail of the system's own actions
        actions = [r["action"] for r in audit.rows]
        assert {"drift.detected", "model.retraining_completed", "model.created"} <= set(actions)
        assert "v2.0" in [r["resource_id"] for r in audit.rows if r["action"] == "model.created"]

        # 10. rollback from the newest version to the previous one
        active = svc.status(SIMULATION)["model_version"]
        previous = repo.get_version(SIMULATION, active)["parent_version"]
        res = await svc.activate_version(SIMULATION, previous, "admin@example.com", user_id=1,
                                         reason="Demo: restore the previous model", rollback_only=True)
        assert res == {"previous_version": active, "active_version": previous}
        act = repo.list_activations(SIMULATION)[0]
        assert (act["action"], act["from_version"], act["to_version"]) == ("rollback", active, previous)
        before = len(outcome_rows(repo, SIMULATION))
        await svc.simulate(5, stop_on_drift=True)
        assert all(r["model_version"] == previous for r in outcome_rows(repo, SIMULATION)[before:])
        assert active in [v["version"] for v in version_rows(repo, SIMULATION)]      # nothing was deleted
        await asyncio.sleep(0.05)
        assert col.names()[-1] in ("MODEL_ACTIVATED", "PREDICTION_RESULT", "PERFORMANCE_UPDATED", "SIMULATION_STATE")
        assert "MODEL_ACTIVATED" in col.names()

        await svc.stop()
        await asyncio.sleep(0.02)
        await bus.stop()
    asyncio.run(go())
