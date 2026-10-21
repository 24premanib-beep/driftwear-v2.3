"""
End-to-end tests of the drift pipeline without a database or web server:
PipelineService + MemoryRepository + LocalModelStorage + EventBus.

These exercise the same code paths the API uses (the API layer only adds
HTTP, auth and SQL persistence on top).
"""
import asyncio

import pytest

from app.errors import ConflictError, ServiceUnavailableError
from app.services.events import EventBus
from app.services.model_storage import LocalModelStorage
from app.services.pipeline import LIVE, SIMULATION, PipelineService
from tests.memory_repository import MemoryRepository
from tests.reference import new_engine_run

RECORD = {"Customer_ID": "C1001", "Purchase_Date": "2026-04-10 12:00", "Previous_Category": "Tops",
          "Purchase_Frequency": 6, "Recency": 21, "Season": "Summer", "Month": 4, "Price": 1499.0,
          "Discount": 10.0, "Customer_Preference": "Casual"}


class Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append({**event.payload, "_audience": event.audience})

    def names(self, stream=None):
        return [e["event"] for e in self.events if stream is None or e["stream"] == stream]


async def _start(tmp_path, repo=None):
    bus = EventBus()
    col = Collector()
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


def test_bootstrap_creates_v1_for_both_streams(tmp_path):
    async def go():
        svc, bus, repo, _ = await _start(tmp_path)
        assert {v["stream"]: v["version"] for v in repo.versions} == {LIVE: "v1.0", SIMULATION: "v1.0"}
        v1 = repo.get_version(LIVE, "v1.0")
        assert v1["kind"] == "initial" and v1["training_records"] == 300 and v1["is_active"]
        assert 0 < v1["accuracy"] < 1 and len(v1["calibration_errors"]) == 40 and len(v1["checksum"]) == 64
        assert (tmp_path / "models" / v1["model_path"]).exists()
        assert svc.status(LIVE)["status"] == "STABLE"
        await _stop(svc, bus)
    asyncio.run(go())


def test_live_prediction_then_outcome(tmp_path):
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        res = await svc.predict(user_id=7, record=dict(RECORD))
        p = res["prediction"]
        assert p["model_version"] == "v1.0" and p["actual_category"] is None and res["outcome"] is None
        assert 0 < p["confidence"] <= 1 and abs(sum(p["probabilities"].values()) - 1) < 0.01
        assert svc.status(LIVE)["records_processed"] == 0          # no label yet → detector untouched

        out = await svc.record_outcome(p["id"], "Bottoms")
        assert out["step"] == 0 and out["actual_category"] == "Bottoms"
        stored = repo.get_prediction(p["id"])
        assert stored["actual_category"] == "Bottoms" and stored["step"] == 0
        assert stored["is_correct"] == (p["predicted_category"] == "Bottoms")
        with pytest.raises(ConflictError):
            await svc.record_outcome(p["id"], "Tops")
        await asyncio.sleep(0.05)
        created = [e for e in col.events if e["event"] == "PREDICTION_CREATED"][0]
        assert created["_audience"] == ("owner", 7)
        assert "PREDICTION_RESULT" in col.names(LIVE)
        await _stop(svc, bus)
    asyncio.run(go())


def test_simulation_drift_triggers_adaptation_and_new_version(tmp_path):
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        await svc.trend_change()                       # jump to the next fashion trend
        res = {"drift_events": []}
        for _ in range(20):
            res = await svc.simulate(10, stop_on_drift=True)
            if res["drift_events"]:
                break
        assert res["drift_events"], "drift should be detected after the trend change"
        assert res["stopped_on_drift"] and res["model_version"] == "v2.0"
        drift = repo.drift_events[0]
        assert drift["detector"] == "DDM" and drift["previous_model_version"] == "v1.0"
        assert drift["new_model_version"] == "v2.0"
        # window = change point .. detection step (clamped to the records that exist after the jump)
        assert drift["window_size"] == drift["stream_step"] - drift["window_start"] + 1 >= 10
        v2 = repo.get_version(SIMULATION, "v2.0")
        assert v2["is_active"] and v2["kind"] == "drift" and v2["drift_event_id"] == drift["id"]
        assert not repo.get_version(SIMULATION, "v1.0")["is_active"]
        await asyncio.sleep(0.05)
        names = col.names(SIMULATION)
        order = [names.index(n) for n in ("DRIFT_DETECTED", "ADAPTATION_STARTED", "ADAPTATION_COMPLETED",
                                          "MODEL_VERSION_CREATED")]
        assert order == sorted(order)
        assert "TREND_CHANGED" in names
        assert all(e["_audience"] == "staff" for e in col.events if e["stream"] == SIMULATION)
        assert not repo.versions or all(v["stream"] != LIVE or v["version"] == "v1.0" for v in repo.versions)
        await _stop(svc, bus)
    asyncio.run(go())


@pytest.mark.slow
def test_restart_mid_stream_restores_and_matches_uninterrupted_run(tmp_path):
    """Process past the first drift, restart from storage, finish: identical to an uninterrupted run."""
    async def go():
        repo = MemoryRepository()
        svc, bus, _, _ = await _start(tmp_path, repo)
        await svc.simulate(500, stop_on_drift=False)
        await svc.simulate(150, stop_on_drift=False)       # step 649: after drift (616), refresh pending
        before = svc.status(SIMULATION)
        assert before["model_version"] == "v2.1" and before["pending_refresh"]
        await _stop(svc, bus)

        svc2, bus2, _, _ = await _start(tmp_path, repo)    # "server restart"
        after = svc2.status(SIMULATION)
        for key in ("model_version", "records_processed", "detector_reset_step", "pending_refresh", "status",
                    "warning_start", "calibration_size"):
            assert after[key] == before[key], key
        while not (await svc2.simulate(500, stop_on_drift=False))["finished"]:
            pass
        sim = sorted((p for p in repo.predictions.values() if p["stream"] == SIMULATION), key=lambda p: p["step"])
        ref = new_engine_run()                              # same engine, uninterrupted, no database
        assert len(sim) == ref["n"] == 1800
        assert [d["stream_step"] for d in repo.drift_events] == ref["drift_steps"]
        assert [v["version"] for v in repo.versions if v["stream"] == SIMULATION] == ref["versions"]
        got = [(p["predicted_category"], round(p["confidence"], 4), not p["detector_error"], p["baseline_correct"],
                p["model_version"], p["detector_status"]) for p in sim]
        assert got == ref["per_step"]
        assert all(d["accuracy_after"] is not None for d in repo.drift_events)
        await _stop(svc2, bus2)
    asyncio.run(go())


def test_persistence_failure_reloads_engine_from_database(tmp_path):
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        await svc.simulate(5)
        step_before = svc.status(SIMULATION)["records_processed"]
        repo.fail_next_persist = 1
        with pytest.raises(ServiceUnavailableError):
            await svc.simulate(1)
        status = svc.status(SIMULATION)
        assert status["records_processed"] == step_before        # nothing half-applied
        assert svc.simulation_state()["pointer"] == repo.state[SIMULATION]["pointer"]
        await svc.simulate(1)                                      # and it keeps working
        assert svc.status(SIMULATION)["records_processed"] == step_before + 1
        await asyncio.sleep(0.05)
        assert "PIPELINE_ERROR" in col.names(SIMULATION)
        await _stop(svc, bus)
    asyncio.run(go())


def test_manual_adapt_rollback_and_late_label_is_rescored(tmp_path):
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        for i in range(20):  # 20 labeled live outcomes that agree with the model → no drift
            r = await svc.predict(user_id=1, record=dict(RECORD, Customer_ID=f"C{i}", Price=500.0 + 150 * i,
                                                         Previous_Category=["Tops", "Footwear", "Dresses"][i % 3]))
            await svc.record_outcome(r["prediction"]["id"], r["prediction"]["predicted_category"])
        assert svc.status(LIVE)["model_version"] == "v1.0"
        pending = await svc.predict(user_id=1, record=dict(RECORD))      # made by v1.0, label arrives later
        assert pending["prediction"]["model_version"] == "v1.0"

        manual = await svc.adapt_now(LIVE, actor="admin@example.com")
        assert manual["version"] == "v1.1" and manual["kind"] == "manual"
        late = await svc.record_outcome(pending["prediction"]["id"], "Footwear")
        assert late["rescored"] and late["scored_version"] == "v1.1"

        rb = await svc.activate_version(LIVE, "v1.0", actor="admin@example.com")
        assert rb == {"previous_version": "v1.1", "active_version": "v1.0"}
        assert repo.get_version(LIVE, "v1.0")["is_active"] and not repo.get_version(LIVE, "v1.1")["is_active"]
        again = await svc.adapt_now(LIVE, actor="admin@example.com")
        assert again["version"] == "v1.2"                              # never reuses v1.1
        with pytest.raises(ConflictError):
            await svc.activate_version(LIVE, "v1.2", actor="x")
        await asyncio.sleep(0.05)
        assert "MODEL_ACTIVATED" in col.names(LIVE)
        await _stop(svc, bus)
    asyncio.run(go())


def test_wrong_live_labels_trigger_real_drift(tmp_path):
    """Consistently wrong outcomes on the live stream are real drift: the model adapts to them."""
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        results = []
        for i in range(40):
            r = await svc.predict(user_id=2, record=dict(RECORD, Customer_ID=f"D{i}"), actual="Accessories")
            results.append(r["outcome"])
            if r["outcome"]["drift_detected"]:
                break
        assert results[-1]["drift_detected"] and results[-1]["new_model_version"] == "v2.0"
        assert any(o["status"] == "WARNING" for o in results)          # warning zone came first
        after = await svc.predict(user_id=2, record=dict(RECORD, Customer_ID="D99"))
        assert after["prediction"]["model_version"] == "v2.0"
        assert after["prediction"]["predicted_category"] == "Accessories"
        await asyncio.sleep(0.05)
        live = col.names(LIVE)
        assert live.index("WARNING_DETECTED") < live.index("DRIFT_DETECTED") < live.index("MODEL_VERSION_CREATED")
        await _stop(svc, bus)
    asyncio.run(go())


def test_uploaded_records_flow_through_live_stream(tmp_path):
    async def go():
        svc, bus, repo, _ = await _start(tmp_path)
        rows = [{"customer_id": f"U{i}", "purchase_date": f"2026-0{1 + i % 9}-1{i % 9} 10:00",
                 "previous_category": "Tops", "purchase_frequency": 3, "recency": 10, "season": "Winter",
                 "month": 1 + i % 9, "price": 900.0 + i, "discount": 5.0, "customer_preference": "Sporty",
                 "target_category": "Footwear", "period": None, "trend": None} for i in range(12)]
        repo.add_records(rows, user_id=3)
        res = await svc.process_uploaded(5)
        assert res["processed"] == 5 and res["remaining"] == 7
        res = await svc.process_uploaded(100)
        assert res["processed"] == 7 and res["remaining"] == 0
        live = [p for p in repo.predictions.values() if p["stream"] == LIVE]
        assert len(live) == 12 and all(p["source"] == "upload" and p["step"] is not None for p in live)
        assert all(r["status"] == "processed" and r["prediction_id"] for r in repo.records)
        dates = [repo.predictions[r["prediction_id"]]["features"]["Purchase_Date"] for r in
                 sorted(repo.records, key=lambda r: repo.predictions[r["prediction_id"]]["step"])]
        assert dates == sorted(dates)                                   # processed in time order
        await _stop(svc, bus)
    asyncio.run(go())


def test_simulation_runner_pauses_on_drift(tmp_path):
    async def go():
        svc, bus, repo, col = await _start(tmp_path)
        await svc.trend_change()
        state = await svc.start_simulation(speed=10, pause_on_drift=True)
        assert state["running"]
        for _ in range(500):
            await asyncio.sleep(0.02)
            if not svc.sim.running:
                break
        assert not svc.sim.running and repo.drift_events
        assert "concept drift" in svc.simulation_state()["last_message"].lower()
        reset = await svc.reset_simulation(regenerate=True, seed=7)
        assert reset["seed"] == 7 and reset["processed"] == 0 and reset["model_version"] == "v1.0"
        assert not repo.drift_events and [v["version"] for v in repo.versions if v["stream"] == SIMULATION] == ["v1.0"]
        assert repo.get_version(LIVE, "v1.0")["is_active"]             # live untouched by simulation reset
        await _stop(svc, bus)
    asyncio.run(go())
