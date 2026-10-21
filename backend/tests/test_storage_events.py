"""Model storage, event bus, WebSocket fan-out and the ordered task queue."""
import asyncio
import time

import pytest

from app.services.events import EventBus, can_receive, make_event
from app.services.model_storage import IntegrityError, LocalModelStorage, StorageError
from app.websocket.manager import ConnectionManager
from app.workers.queue import InProcessQueue


def test_local_storage_is_write_once_and_verified(tmp_path):
    st = LocalModelStorage(tmp_path)
    ref = st.save("live/run1/model_v1_0.joblib", b"model-bytes")
    assert st.load(ref.path, ref.checksum) == b"model-bytes" and ref.size == 11
    with pytest.raises(StorageError):
        st.save(ref.path, b"other")                       # never overwrite a model
    (tmp_path / ref.path).write_bytes(b"tampered")
    with pytest.raises(IntegrityError):
        st.load(ref.path, ref.checksum)                   # never unpickle unverified bytes
    for bad in ("../escape.joblib", "/etc/passwd", "a/../../b"):
        with pytest.raises(StorageError):
            st.save(bad, b"x")


def test_event_audiences():
    assert can_receive("all", 1, "user")
    assert not can_receive("staff", 1, "user") and can_receive("staff", 1, "analyst")
    assert can_receive(("owner", 1), 1, "user") and not can_receive(("owner", 2), 1, "user")
    assert can_receive(("owner", 2), 1, "admin")


class _WS:
    def __init__(self, fail=False):
        self.got, self.fail = [], fail

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("closed")
        self.got.append(payload["event"])

    async def close(self, code=1000, reason=""):
        self.closed = code


def test_bus_delivers_in_order_to_allowed_clients_and_drops_dead_ones():
    async def go():
        bus, mgr = EventBus(), ConnectionManager()
        bus.subscribe(mgr.broadcast)
        await bus.start()
        user, analyst, dead = _WS(), _WS(), _WS(fail=True)
        await mgr.add(user, 1, "user")
        await mgr.add(analyst, 2, "analyst")
        await mgr.add(dead, 3, "admin")
        bus.publish(make_event("DRIFT_DETECTED", "live", "drift"))
        bus.publish(make_event("PREDICTION_CREATED", "live", "mine", audience=("owner", 1)))
        bus.publish(make_event("PREDICTION_CREATED", "live", "theirs", audience=("owner", 9)))
        await asyncio.to_thread(bus.publish_threadsafe, make_event("ADAPTATION_STARTED", "live", "from a thread"))
        bus.publish(make_event("SIMULATION_STATE", "simulation", "sim", audience="staff"))
        await asyncio.sleep(0.05)
        await bus.stop()
        assert user.got == ["DRIFT_DETECTED", "PREDICTION_CREATED", "ADAPTATION_STARTED"]
        assert analyst.got == ["DRIFT_DETECTED", "PREDICTION_CREATED", "PREDICTION_CREATED", "ADAPTATION_STARTED",
                               "SIMULATION_STATE"]
        assert mgr.count == 2
        assert [e["event"] for e in bus.recent_for(1, "user")][0] == "ADAPTATION_STARTED"
        await mgr.close_user(1)
        assert mgr.count == 1 and user.closed == 4401
    asyncio.run(go())


def test_queue_runs_jobs_one_at_a_time_in_order():
    async def go():
        q = InProcessQueue()
        await q.start()
        running, order = [], []

        def job(i):
            def f():
                running.append(i)
                assert len(running) == 1          # never two jobs at once
                time.sleep(0.005)
                order.append(i)
                running.remove(i)
                return i
            return f
        results = await asyncio.gather(*(q.submit(job(i)) for i in range(10)))
        assert results == order == list(range(10))
        with pytest.raises(ZeroDivisionError):
            await q.submit(lambda: 1 / 0)
        assert await q.submit(lambda: "still running") == "still running"
        await q.stop()
    asyncio.run(go())
