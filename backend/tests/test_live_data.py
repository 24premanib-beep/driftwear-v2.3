"""Live data pathway without HTTP: validation → rejection store → prediction → outcome (single and batch)."""
import asyncio

import pytest

from ml.validation import event_to_record, validate_event, validate_outcome

from app.errors import ValidationFailedError
from app.services.events import EventBus
from app.services.ingestion import EventRejected, IngestionService
from app.services.model_storage import LocalModelStorage
from app.services.pipeline import LIVE, PipelineService
from tests.memory_repository import MemoryRepository

EVENT = {"event_id": "evt-1", "customer_id": "C1023", "previous_category": "Tops", "purchase_frequency": 4,
         "recency": 12, "season": "Monsoon", "month": 6, "price": 1299, "discount": 20,
         "customer_preference": "Casual"}


class MemoryRejections:
    def __init__(self):
        self.rows = []

    def record(self, rows):
        self.rows.extend(rows)


async def _start(tmp_path, max_batch=10):
    bus, repo = EventBus(), MemoryRepository()
    svc = PipelineService(repo, LocalModelStorage(tmp_path / "models"), bus, tick_seconds=0.01)
    await bus.start()
    await svc.start()
    rej = MemoryRejections()
    return svc, bus, repo, rej, IngestionService(svc, rej, max_batch=max_batch)


async def _stop(svc, bus):
    await svc.stop()
    await asyncio.sleep(0.02)
    await bus.stop()


@pytest.mark.parametrize("change,field,fragment", [
    ({"price": -500}, "price", "greater than 0"),
    ({"price": 0}, "price", "greater than 0"),
    ({"discount": 95}, "discount", "between 0 and 90"),
    ({"discount": -5}, "discount", "between 0 and 90"),
    ({"recency": -1}, "recency", "between 0 and 730"),
    ({"purchase_frequency": 2.5}, "purchase_frequency", "whole number"),
    ({"purchase_frequency": "many"}, "purchase_frequency", "number"),
    ({"purchase_frequency": True}, "purchase_frequency", "number"),
    ({"season": "XYZ"}, "season", "Must be one of"),
    ({"previous_category": "Shoes"}, "previous_category", "Must be one of"),
    ({"customer_preference": "Grunge"}, "customer_preference", "Must be one of"),
    ({"actual_category": "Hats"}, "actual_category", "Must be one of"),
    ({"month": 13}, "month", "between 1 and 12"),
    ({"purchase_date": "2026-13-40"}, "purchase_date", "Not a valid date"),
    ({"purchase_date": "2099-01-01T00:00:00"}, "purchase_date", "future"),
    ({"purchase_date": "1999-12-31T00:00:00"}, "purchase_date", "before 2000"),
    ({"customer_id": "bad id!"}, "customer_id", "letters"),
    ({"event_id": "bad id!"}, "event_id", "Use letters"),
    ({"unexpected": 1}, "unexpected", "Unexpected field"),
    ({"price": None}, "price", "missing"),
])
def test_event_validation_rejects_bad_values(change, field, fragment):
    chk = validate_event({**EVENT, **change})
    assert not chk.ok and chk.values == {}
    hits = [e for e in chk.details() if e["field"] == field]
    assert hits and fragment.lower() in hits[0]["message"].lower(), chk.details()


def test_event_validation_reports_every_problem():
    fields = {e["field"] for e in validate_event({"price": -500, "season": "XYZ"}).details()}
    assert {"price", "season", "previous_category", "purchase_frequency", "recency", "discount",
            "customer_preference"} <= fields
    assert not validate_event(["not", "an", "object"]).ok and not validate_event(None).ok


def test_valid_event_is_normalised_and_warned_not_rejected():
    chk = validate_event({**EVENT, "previous_category": "tops", "customer_preference": " casual", "season": "winter",
                          "price": "1,299", "purchase_date": "2026-06-14T10:00:00Z"})
    assert chk.ok and chk.values["previous_category"] == "Tops" and chk.values["price"] == 1299.0
    assert [w["field"] for w in chk.warning_details()] == ["season"]         # unusual, reported, kept
    rec, actual, eid = event_to_record(chk.values)
    assert (rec["Season"], rec["Month"], rec["Purchase_Date"], eid, actual) == ("Winter", 6, "2026-06-14 10:00",
                                                                                "evt-1", None)
    derived = {k: v for k, v in EVENT.items() if k not in ("season", "month")} | {"purchase_date": "2025-11-02T09:00:00"}
    rec2, _, _ = event_to_record(validate_event(derived).values)
    assert rec2["Month"] == 11 and rec2["Season"] == "Festive"                 # same derivation as the form


def test_outcome_validation():
    assert validate_outcome({"event_id": "evt-1", "actual_category": "dresses"}).values == {
        "event_id": "evt-1", "actual_category": "Dresses"}
    assert validate_outcome({"prediction_id": 3, "actual_category": "Tops"}).ok
    for bad in ({"actual_category": "Tops"}, {"event_id": "e", "prediction_id": 1, "actual_category": "Tops"},
                {"prediction_id": 0, "actual_category": "Tops"}, {"event_id": "e1", "actual_category": "Hats"},
                {"event_id": "e1", "actual_category": "Tops", "x": 1}, "nope"):
        assert not validate_outcome(bad).ok, bad


def test_single_event_ingestion_and_stored_rejection(tmp_path):
    async def go():
        svc, bus, repo, rej, ing = await _start(tmp_path)
        res = await ing.ingest(dict(EVENT), user_id=7)
        p = res["prediction"]
        assert p["source"] == "event" and p["event_id"] == "evt-1" and p["model_version"] == "v1.0"
        assert p["created_at"] is not None and res["outcome"] is None
        assert res["validation"] == {"passed": True, "warnings": []}
        assert repo.get_prediction(p["id"])["features"]["Season"] == "Monsoon"
        with pytest.raises(EventRejected) as exc:
            await ing.ingest({**EVENT, "event_id": "evt-2", "price": -500, "season": "XYZ"}, user_id=7)
        assert exc.value.status_code == 422 and exc.value.message.startswith("Event rejected: price")
        assert {d["field"] for d in exc.value.details} == {"price", "season"}
        (row,) = rej.rows
        assert (row["event_id"], row["error_count"], row["user_id"], row["source"]) == ("evt-2", 2, 7, "single")
        assert repo.find_prediction_by_event(LIVE, "evt-2") is None             # never reached the model
        m = svc.prediction_metrics(LIVE)
        assert m["succeeded"] == 1 and m["failed"] == 0 and m["success_rate"] == 1.0 and m["latency"]["n"] == 1
        await _stop(svc, bus)
    asyncio.run(go())


def test_batch_with_valid_invalid_and_duplicate_items(tmp_path):
    async def go():
        svc, bus, repo, rej, ing = await _start(tmp_path, max_batch=5)
        await ing.ingest({**EVENT, "event_id": "old-1"}, user_id=1)
        items = [{**EVENT, "event_id": "b-1", "actual_category": "Tops"}, {**EVENT, "event_id": "b-2", "discount": 120},
                 {**EVENT, "event_id": "b-1"}, {**EVENT, "event_id": "old-1"}, "not an object"]
        res = await ing.ingest_batch(items, user_id=1)
        assert (res["received"], res["accepted"], res["rejected"], res["duplicates"]) == (5, 1, 3, 1)
        assert [r["status"] for r in res["results"]] == ["accepted", "rejected", "rejected", "duplicate", "rejected"]
        first = res["results"][0]
        assert first["outcome"]["actual_category"] == "Tops" and first["model_version"] == "v1.0"
        assert "Duplicate of item 0" in res["results"][2]["errors"][0]["message"]
        assert [r["batch_index"] for r in rej.rows] == [1, 2, 4] and all(r["source"] == "batch" for r in rej.rows)
        with pytest.raises(ValidationFailedError):
            await ing.ingest_batch([EVENT] * 6, user_id=1)                       # over the batch limit
        with pytest.raises(ValidationFailedError):
            await ing.ingest_batch([], user_id=1)
        await _stop(svc, bus)
    asyncio.run(go())


def test_batch_outcomes_link_to_events_and_respect_ownership(tmp_path):
    async def go():
        svc, bus, repo, rej, ing = await _start(tmp_path)
        a = await ing.ingest({**EVENT, "event_id": "o-1"}, user_id=1)
        await ing.ingest({**EVENT, "event_id": "o-2"}, user_id=2)
        res = await ing.record_outcomes([
            {"event_id": "o-1", "actual_category": "Bottoms"}, {"event_id": "o-2", "actual_category": "Tops"},
            {"prediction_id": a["prediction"]["id"], "actual_category": "Tops"},
            {"event_id": "missing", "actual_category": "Tops"}, {"actual_category": "Tops"}], user_id=1, is_admin=False)
        assert [r["status"] for r in res["results"]] == ["recorded", "not_found", "conflict", "not_found", "rejected"]
        stored = repo.get_prediction(a["prediction"]["id"])
        assert stored["actual_category"] == "Bottoms" and stored["step"] == 0
        assert stored["outcome_at"] >= stored["created_at"]                     # outcome arrived after the prediction
        first = res["results"][0]
        assert first["model_version"] == "v1.0" and first["is_correct"] is not None
        assert first["detector_status"] in ("STABLE", "WARNING", "DRIFT")
        admin = await ing.record_outcomes([{"event_id": "o-2", "actual_category": "Tops"}], user_id=99, is_admin=True)
        assert admin["recorded"] == 1
        await _stop(svc, bus)
    asyncio.run(go())
