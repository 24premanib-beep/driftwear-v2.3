"""Component health checks (app/services/health.py) against real objects and fakes."""
import asyncio
from types import SimpleNamespace

from app.services import health as H
from app.services.events import EventBus
from app.services.model_storage import LocalModelStorage
from app.services.pipeline import PipelineService
from tests.memory_repository import MemoryRepository


class FakeDb:
    dialect = "postgresql"

    def __init__(self, ok=True, revision=H.EXPECTED_DB_REVISION):
        self.ok, self.revision = ok, revision

    def ping(self):
        if not self.ok:
            raise ConnectionError("down")
        return True

    def migration_revision(self):
        return self.revision


def test_database_check():
    assert H.check_database(FakeDb())["status"] == H.HEALTHY
    assert H.check_database(FakeDb(revision="0001_initial"))["status"] == H.WARNING
    down = H.check_database(FakeDb(ok=False))
    assert down["status"] == H.ERROR and "down" not in down["message"]          # no exception text leaks
    assert H.overall(H.HEALTHY, H.WARNING) == H.WARNING and H.overall(H.WARNING, H.ERROR) == H.ERROR


def test_pipeline_storage_and_websocket_checks(tmp_path):
    async def go():
        bus = EventBus()
        repo = MemoryRepository()
        storage = LocalModelStorage(tmp_path / "m")
        pipe = PipelineService(repo, storage, bus)
        state = SimpleNamespace(pipeline_state="starting", pipeline=pipe, bus=bus, storage=storage,
                                ws_manager=SimpleNamespace(count=2))
        assert H.check_pipeline(state)["status"] == H.WARNING
        assert H.check_websocket(state)["status"] == H.ERROR                     # bus not started yet
        await bus.start()
        await pipe.start()
        state.pipeline_state = "ready"
        p = H.check_pipeline(state)
        assert p["status"] == H.HEALTHY and p["streams"]["live"]["model_version"] == "v1.0"
        ws = H.check_websocket(state)
        assert ws["status"] == H.HEALTHY and ws["clients"] == 2
        assert H.check_storage(state)["status"] == H.HEALTHY
        storage.delete(repo.get_version("live", "v1.0")["model_path"])       # active model file disappears
        assert H.check_storage(state)["status"] == H.ERROR
        pipe._broken.add("simulation")
        assert H.check_pipeline(state)["status"] == H.ERROR
        await pipe.stop()
        await bus.stop()
    asyncio.run(go())
