"""Model rollback through the real pipeline: verification, restore, history, cancelled refreshes, restart."""
import asyncio

import pytest

from app.errors import ConflictError, NotFoundError, ServiceUnavailableError
from app.services.events import EventBus
from app.services.model_storage import LocalModelStorage
from app.services.pipeline import LIVE, PipelineService
from tests.memory_repository import MemoryRepository

RECORD = {"Customer_ID": "C1001", "Purchase_Date": "2026-04-10 12:00", "Previous_Category": "Tops",
          "Purchase_Frequency": 6, "Recency": 21, "Season": "Summer", "Month": 4, "Price": 1499.0,
          "Discount": 10.0, "Customer_Preference": "Casual"}


class Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event.payload)


async def _start(tmp_path, repo=None):
    bus, col = EventBus(), Collector()
    bus.subscribe(col)
    repo = repo or MemoryRepository()
    svc = PipelineService(repo, LocalModelStorage(tmp_path / "models"), bus, tick_seconds=0.01)
    await bus.start()
    await svc.start()
    return svc, bus, repo, col


async def _stop(svc, bus):
    await svc.stop()
    await asyncio.sleep(0.02)
    await bus.stop()


async def _drift_to_v2(svc):
    """Customers suddenly buy Accessories: real concept drift on the live stream → v2.0."""
    for i in range(80):
        r = await svc.predict(user_id=2, record=dict(RECORD, Customer_ID=f"D{i}"), actual="Accessories")
        if r["outcome"]["drift_detected"]:
            break
    assert svc.status(LIVE)["model_version"] == "v2.0"


def test_rollback_restores_the_previous_model_and_keeps_history(tmp_path):
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        await _drift_to_v2(svc)
        engine = svc.runtimes[LIVE].engine
        assert len(engine.pending_refresh) == 3                      # +25 / +75 / +150 refreshes of v2.0
        with pytest.raises(NotFoundError):
            await svc.activate_version(LIVE, "v9.0", "admin", rollback_only=True)
        with pytest.raises(ConflictError):
            await svc.activate_version(LIVE, "v2.0", "admin", rollback_only=True)      # already active
        res = await svc.activate_version(LIVE, "v1.0", "admin@example.com", user_id=1,
                                         reason="  v2.0 overfits the sale  ", rollback_only=True)
        assert res == {"previous_version": "v2.0", "active_version": "v1.0"}
        assert engine.pending_refresh == [] and repo.state[LIVE]["pending_refresh"] == []
        (act,) = repo.list_activations(LIVE)
        assert (act["from_version"], act["to_version"], act["action"], act["user_id"], act["reason"]) == (
            "v2.0", "v1.0", "rollback", 1, "v2.0 overfits the sale")
        assert {v["version"]: v["is_active"] for v in repo.versions if v["stream"] == LIVE} == {"v1.0": True,
                                                                                                "v2.0": False}
        for v in repo.versions:
            assert (tmp_path / "models" / v["model_path"]).exists()         # history and files are never deleted
        with pytest.raises(ConflictError):
            await svc.activate_version(LIVE, "v2.0", "admin", rollback_only=True)      # newer: not a rollback
        # every later prediction uses the restored model, and no scheduled refresh replaces it
        for i in range(40):
            r = await svc.predict(user_id=2, record=dict(RECORD, Customer_ID=f"R{i}"))
            assert r["prediction"]["model_version"] == "v1.0"
            await svc.record_outcome(r["prediction"]["id"], r["prediction"]["predicted_category"])
        assert svc.status(LIVE)["model_version"] == "v1.0"
        assert sorted(v["version"] for v in repo.versions if v["stream"] == LIVE) == ["v1.0", "v2.0"]
        await asyncio.sleep(0.05)
        event = [e for e in col.events if e["event"] == "MODEL_ACTIVATED"][-1]
        assert event["data"]["rollback"] is True and event["data"]["action"] == "rollback"
        assert event["data"]["cancelled_refreshes"] == 3 and "overfits" not in event["message"]
        await _stop(svc, bus)

        svc2, bus2, _, _ = await _start(tmp_path, repo=repo)                 # restart: the rollback persists
        assert svc2.status(LIVE)["model_version"] == "v1.0"
        assert svc2.runtimes[LIVE].engine.pending_refresh == []
        await svc2.activate_version(LIVE, "v2.0", "admin", user_id=1)        # moving forward is an activation
        assert [a["action"] for a in repo.list_activations(LIVE)] == ["activate", "rollback"]
        await _stop(svc2, bus2)
    asyncio.run(go())


def test_rollback_refuses_a_tampered_model_file(tmp_path):
    async def go():
        svc, bus, repo, _ = await _start(tmp_path)
        await _drift_to_v2(svc)
        v1 = repo.get_version(LIVE, "v1.0")
        (tmp_path / "models" / v1["model_path"]).write_bytes(b"tampered")
        with pytest.raises(ServiceUnavailableError):
            await svc.activate_version(LIVE, "v1.0", "admin", rollback_only=True)
        assert svc.status(LIVE)["model_version"] == "v2.0" and repo.get_version(LIVE, "v2.0")["is_active"]
        assert repo.list_activations(LIVE) == []                             # nothing recorded, nothing changed
        await _stop(svc, bus)
    asyncio.run(go())
