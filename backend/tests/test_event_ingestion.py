"""
Real-time event ingestion through the pipeline (no HTTP, no database):

    event → prediction (+ explanation) → outcome → error → drift → adaptation → new model → recovery

plus idempotency, the audit trail of system events and the 'adapting' flag used by model health.
"""
import asyncio

import pytest

from app.errors import ConflictError
from app.services.audit import AuditEventRecorder
from app.services.events import EventBus
from app.services.model_storage import LocalModelStorage
from app.services.pipeline import LIVE, PipelineService, is_rollback
from tests.memory_repository import MemoryRepository

EVENT = {"Customer_ID": "C1023", "Purchase_Date": "2026-06-14 10:00", "Previous_Category": "Tops",
         "Purchase_Frequency": 4, "Recency": 12, "Season": "Summer", "Month": 6, "Price": 1299.0, "Discount": 20.0,
         "Customer_Preference": "Casual"}


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


async def _start(tmp_path):
    bus, col, audit = EventBus(), Collector(), MemoryAudit()
    bus.subscribe(col)
    bus.subscribe(AuditEventRecorder(audit))
    repo = MemoryRepository()
    svc = PipelineService(repo, LocalModelStorage(tmp_path / "models"), bus, tick_seconds=0.01)
    await bus.start()
    await svc.start()
    return svc, bus, repo, col, audit


async def _stop(svc, bus):
    await svc.stop()
    await asyncio.sleep(0.05)
    await bus.stop()


def test_event_is_stored_with_explanation_and_is_idempotent(tmp_path):
    async def go():
        svc, bus, repo, col, _ = await _start(tmp_path)
        res = await svc.predict(user_id=5, record=dict(EVENT), source="event", event_id="evt-1")
        p = res["prediction"]
        assert p["source"] == "event" and p["event_id"] == "evt-1" and p["actual_category"] is None
        exp = res["explanation"]
        assert exp["predicted"] == p["predicted_category"] and len(exp["contributions"]) == 8
        assert repo.get_prediction(p["id"])["explanation"] == exp            # stored with the prediction
        assert svc.status(LIVE)["records_processed"] == 0                    # no outcome → detector untouched
        with pytest.raises(ConflictError):
            await svc.predict(user_id=5, record=dict(EVENT), source="event", event_id="evt-1")
        assert repo.find_prediction_by_event(LIVE, "evt-1")["id"] == p["id"]
        out = await svc.record_outcome(p["id"], "Bottoms")
        assert out["step"] == 0 and repo.get_prediction(p["id"])["actual_category"] == "Bottoms"
        await asyncio.sleep(0.05)
        created = next(e for e in col.events if e["event"] == "PREDICTION_CREATED")
        assert created["data"]["event_id"] == "evt-1" and created["data"]["source"] == "event"
        await _stop(svc, bus)
    asyncio.run(go())


def test_event_stream_drift_adaptation_new_model_and_recovery(tmp_path):
    """Integration: events whose real outcome has changed (everyone now buys Accessories) → the error
    stream rises → WARNING → DRIFT → retrain → v2.0 → new events are predicted correctly again."""
    async def go():
        svc, bus, repo, col, audit = await _start(tmp_path)
        outcomes = []
        for i in range(60):
            r = await svc.predict(user_id=9, record=dict(EVENT, Customer_ID=f"E{i}", Price=600.0 + 37 * i),
                                  source="event", event_id=f"evt-{i}")
            assert svc.status(LIVE)["adapting"] is False
            out = await svc.record_outcome(r["prediction"]["id"], "Accessories")
            outcomes.append(out)
            if out["drift_detected"]:
                break
        last = outcomes[-1]
        assert last["drift_detected"] and last["new_model_version"] == "v2.0"
        assert any(o["status"] == "WARNING" for o in outcomes[:-1])
        assert repo.get_version(LIVE, "v2.0")["is_active"] and repo.get_version(LIVE, "v2.0")["kind"] == "drift"
        assert svc.status(LIVE)["adapting"] is False                         # cleared once saved
        # recovery: the adapted model predicts the new pattern
        correct = 0
        for i in range(10):
            r = await svc.predict(user_id=9, record=dict(EVENT, Customer_ID=f"R{i}", Price=700.0 + 50 * i),
                                  source="event", event_id=f"rec-{i}", actual="Accessories")
            correct += int(r["outcome"]["is_correct"])
            assert r["prediction"]["model_version"] == "v2.0"
        assert correct >= 8
        await asyncio.sleep(0.1)
        names = col.names()
        order = [names.index(n) for n in ("WARNING_DETECTED", "DRIFT_DETECTED", "ADAPTATION_STARTED",
                                          "ADAPTATION_COMPLETED", "MODEL_VERSION_CREATED")]
        assert order == sorted(order)
        drift = next(e for e in col.events if e["event"] == "DRIFT_DETECTED")
        assert drift["severity"] in ("High", "Medium", "Low") and drift["data"]["severity"] == drift["severity"]
        assert repo.drift_events[0]["details"]["severity"] == drift["severity"]
        actions = [r["action"] for r in audit.rows]                          # system events are audited
        assert {"drift.detected", "model.retraining_started", "model.created"} <= set(actions)
        created = next(r for r in audit.rows if r["action"] == "model.created")
        assert created["resource_id"] == "v2.0" and created["user_id"] is None and created["stream"] == LIVE
        await _stop(svc, bus)
    asyncio.run(go())


def test_rollback_event_does_not_broadcast_admin_email(tmp_path):
    async def go():
        svc, bus, repo, col, _ = await _start(tmp_path)
        for i in range(20):
            r = await svc.predict(user_id=1, record=dict(EVENT, Customer_ID=f"M{i}"))
            await svc.record_outcome(r["prediction"]["id"], r["prediction"]["predicted_category"])
        await svc.adapt_now(LIVE, actor="admin@example.com")
        res = await svc.activate_version(LIVE, "v1.0", actor="admin@example.com")
        assert res == {"previous_version": "v1.1", "active_version": "v1.0"}
        await asyncio.sleep(0.05)
        act = next(e for e in col.events if e["event"] == "MODEL_ACTIVATED")
        assert act["data"]["rollback"] is True and "admin@example.com" not in act["message"]
        assert "Rollback completed" in act["message"]
        assert is_rollback("v2.1", "v1.0") and not is_rollback("v1.0", "v2.0")
        await _stop(svc, bus)
    asyncio.run(go())


def test_queue_stats_and_reference_inputs(tmp_path):
    async def go():
        svc, bus, repo, _, _ = await _start(tmp_path)
        await svc.simulate(5)
        with pytest.raises(ConflictError):
            r = await svc.predict(user_id=1, record=dict(EVENT))
            await svc.record_outcome(r["prediction"]["id"], "Tops")
            await svc.record_outcome(r["prediction"]["id"], "Tops")          # already labeled → rejected (4xx)
        stats = svc.queue_stats()
        assert stats["completed"] >= 2 and stats["rejected"] == 1 and stats["failed"] == 0
        ref, info = svc.reference_inputs(LIVE)
        assert len(ref) == 300 and info["source"] == "historical" and set(ref[0]) >= {"Price", "Season"}
        ref2, info2 = svc.reference_inputs(LIVE, "active")
        assert info2["source"] == "historical" and "note" in info2           # v1.0 was trained on history
        await _stop(svc, bus)
    asyncio.run(go())
