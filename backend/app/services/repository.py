"""
Persistence contract used by the pipeline.

`PipelineService` only talks to this protocol, never to SQLAlchemy directly.
The production implementation is `SqlRepository` (services/sql_repository.py,
PostgreSQL). Keeping the contract free of ORM types means the whole
predict → outcome → drift → adapt → version flow can be tested without a
database (tests/memory_repository.py implements the same protocol).

All methods are synchronous and transactional: each call either fully commits
or changes nothing. They are called from the pipeline worker thread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class NewPrediction:
    stream: str
    source: str                         # api | simulation | upload
    user_id: int | None
    customer_id: str | None
    features: dict
    predicted_category: str
    confidence: float
    probabilities: dict
    baseline_prediction: str
    model_version: str
    status_at_prediction: str
    data_record_id: int | None = None
    event_id: str | None = None          # producer's id for real-time events (unique per stream)
    explanation: dict | None = None      # per-prediction feature contributions (ml/explain.py)


@dataclass
class StreamData:
    """What the pipeline needs to rebuild a stream's engine after a restart."""
    state: dict                               # stream_state row
    active: dict | None                       # active model_versions row
    baseline: dict | None                     # the stream's v1.0 row
    versions: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)   # recent labeled outcomes, engine format
    n_drifts: int = 0
    open_backfills: list[dict] = field(default_factory=list)


class Repository(Protocol):
    # ---- stream lifecycle --------------------------------------------------
    def load_stream(self, stream: str, history_limit: int) -> StreamData | None: ...
    def save_bootstrap(self, stream: str, version: dict, state: dict) -> None: ...
    def save_state(self, stream: str, state: dict) -> None: ...
    def reset_stream(self, stream: str) -> list[str]:
        """Delete a stream's rows; returns model paths so files can be removed."""
        ...

    # ---- predictions & outcomes -------------------------------------------
    def create_prediction(self, p: NewPrediction) -> dict:
        """Raises ConflictError if p.event_id was already ingested on that stream."""
        ...
    def get_prediction(self, prediction_id: int) -> dict | None: ...
    def find_prediction_by_event(self, stream: str, event_id: str) -> dict | None: ...
    def persist_outcome(self, *, stream: str, outcome: dict, prediction_id: int | None,
                        new_prediction: NewPrediction | None, drift_event: dict | None,
                        version: dict | None, backfills: list[dict], state: dict,
                        data_record_id: int | None = None) -> dict:
        """One transaction: (insert prediction) + outcome + drift event + new active
        version + metric back-fills + stream state. Returns {"prediction_id", "drift_event_id"}."""
        ...

    # ---- model versions ----------------------------------------------------
    def persist_version(self, stream: str, version: dict, state: dict) -> None: ...
    def activate_version(self, stream: str, version: str, state: dict, activation: dict | None = None) -> None:
        """Switch the active version; `activation` (who / from / to / why) is stored in the same transaction."""
        ...
    def list_activations(self, stream: str, limit: int = 200) -> list[dict]:
        """Activation / rollback history, newest first."""
        ...
    def get_version(self, stream: str, version: str) -> dict | None: ...

    # ---- uploaded records waiting for the live stream ----------------------
    def next_pending_records(self, limit: int) -> list[dict]: ...
    def count_pending_records(self) -> int: ...


# ---------------------------------------------------------------------------
# Shared mapping helpers (used by every Repository implementation)
# ---------------------------------------------------------------------------
def history_item(row: dict) -> dict:
    """A labeled prediction row → the engine's history format."""
    features = dict(row["features"])
    record = dict(features, Target_Category=row["actual_category"])
    return {
        "step": int(row["step"]),
        "record_id": row.get("data_record_id") or features.get("Record_ID"),
        "actual": row["actual_category"],
        "predicted": row["predicted_category"],
        "correct": not bool(row["detector_error"]),
        "baseline_pred": row["baseline_prediction"],
        "baseline_correct": bool(row["baseline_correct"]),
        "model_version": row.get("scored_version") or row["model_version"],
        "detector_status": row.get("detector_status"),
        "record": record,
    }


def open_backfills(drift_rows: list[dict], version_rows: list[dict]) -> list[dict]:
    """Drift events / versions whose 'accuracy after' has not been measured yet."""
    out = [{"kind": "drift_event", "key": d["event_key"], "step": int(d["stream_step"])}
           for d in drift_rows if d.get("accuracy_after") is None and d.get("new_model_version")]
    out += [{"kind": "model_version", "key": v["version"], "step": int(v["created_step"])}
            for v in version_rows if v.get("accuracy_after") is None and (v.get("created_step") or -1) >= 0]
    return out


DATA_RECORD_FEATURES = {
    "customer_id": "Customer_ID", "purchase_date": "Purchase_Date", "previous_category": "Previous_Category",
    "purchase_frequency": "Purchase_Frequency", "recency": "Recency", "season": "Season", "month": "Month",
    "price": "Price", "discount": "Discount", "customer_preference": "Customer_Preference",
    "period": "Period", "trend": "Trend",
}


def data_record_features(row: dict) -> dict:
    """A data_records row → the engine's feature record (same keys as the CSV)."""
    rec = {}
    for col, key in DATA_RECORD_FEATURES.items():
        v = row.get(col)
        if v is None:
            continue
        if col == "purchase_date" and hasattr(v, "strftime"):
            v = v.strftime("%Y-%m-%d %H:%M")
        rec[key] = v
    return rec
