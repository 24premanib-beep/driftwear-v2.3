"""In-memory Repository with the same semantics as SqlRepository.

Used to test the pipeline (and run it in notebooks) without PostgreSQL.
Each method validates first and mutates last, mirroring a DB transaction.
"""
from __future__ import annotations

import copy
import itertools
from dataclasses import asdict
from datetime import datetime, timezone

from app.errors import ConflictError
from app.services.repository import (NewPrediction, StreamData, data_record_features, history_item,
                                     open_backfills)


def _now():
    return datetime.now(timezone.utc)


class MemoryRepository:
    def __init__(self):
        self.state: dict[str, dict] = {}
        self.versions: list[dict] = []
        self.predictions: dict[int, dict] = {}
        self.drift_events: list[dict] = []
        self.records: list[dict] = []
        self.activations: list[dict] = []
        self._ids = {k: itertools.count(1) for k in ("version", "prediction", "drift", "record", "activation")}
        self.fail_next_persist = 0

    # ---- stream lifecycle
    def load_stream(self, stream, history_limit):
        if stream not in self.state:
            return None
        vers = [v for v in self.versions if v["stream"] == stream]
        active = next((v for v in vers if v["is_active"]), None)
        baseline = next((v for v in vers if v["kind"] == "initial"), None)
        labeled = sorted((p for p in self.predictions.values() if p["stream"] == stream and p["step"] is not None),
                         key=lambda p: p["step"])[-history_limit:]
        drifts = [d for d in self.drift_events if d["stream"] == stream]
        return StreamData(state=copy.deepcopy(self.state[stream]), active=copy.deepcopy(active),
                          baseline=copy.deepcopy(baseline), versions=[v["version"] for v in vers],
                          history=[history_item(p) for p in labeled], n_drifts=len(drifts),
                          open_backfills=open_backfills(drifts, vers))

    def save_bootstrap(self, stream, version, state):
        self._add_version(stream, version)
        self.state[stream] = copy.deepcopy(state)

    def save_state(self, stream, state):
        self.state[stream] = copy.deepcopy(state)

    def reset_stream(self, stream):
        paths = [v["model_path"] for v in self.versions if v["stream"] == stream]
        self.versions = [v for v in self.versions if v["stream"] != stream]
        self.predictions = {k: p for k, p in self.predictions.items() if p["stream"] != stream}
        self.drift_events = [d for d in self.drift_events if d["stream"] != stream]
        self.state.pop(stream, None)
        self.activations = [a for a in self.activations if a["stream"] != stream]
        return paths

    # ---- predictions
    def _new_prediction_row(self, p: NewPrediction) -> dict:
        row = asdict(p)
        row.update(id=next(self._ids["prediction"]), created_at=_now(), actual_category=None, is_correct=None,
                   step=None, detector_status=None, detector_error=None, scored_version=None,
                   baseline_correct=None, shadow_states=None, rescored=False, outcome_at=None)
        return row

    def create_prediction(self, p):
        if p.event_id and self.find_prediction_by_event(p.stream, p.event_id):
            raise ConflictError(f"Event '{p.event_id}' was already ingested.")   # unique (stream, event_id)
        row = self._new_prediction_row(p)
        self.predictions[row["id"]] = row
        return copy.deepcopy(row)

    def get_prediction(self, prediction_id):
        p = self.predictions.get(prediction_id)
        return copy.deepcopy(p) if p else None

    def find_prediction_by_event(self, stream, event_id):
        p = next((p for p in self.predictions.values() if p["stream"] == stream and p.get("event_id") == event_id), None)
        return copy.deepcopy(p) if p else None

    def persist_outcome(self, *, stream, outcome, prediction_id, new_prediction, drift_event, version, backfills,
                        state, data_record_id=None):
        if self.fail_next_persist:
            self.fail_next_persist -= 1
            raise RuntimeError("simulated database failure")
        if prediction_id is None:
            row = self._new_prediction_row(new_prediction)
        else:
            row = self.predictions[prediction_id]
        row.update(outcome, outcome_at=_now())
        self.predictions[row["id"]] = row
        drift_id = None
        if drift_event:
            drift_id = next(self._ids["drift"])
            self.drift_events.append(dict(drift_event, id=drift_id, detected_at=_now()))
        if version:
            self._add_version(stream, dict(version, drift_event_id=drift_id))
        for b in backfills:
            target = self.drift_events if b["kind"] == "drift_event" else self.versions
            field = "event_key" if b["kind"] == "drift_event" else "version"
            for t in target:
                if t["stream"] == stream and t[field] == b["key"]:
                    t["accuracy_after"] = b["accuracy_after"]
        if data_record_id is not None:
            for r in self.records:
                if r["id"] == data_record_id:
                    r.update(status="processed", prediction_id=row["id"])
        self.state[stream] = copy.deepcopy(state)
        return {"prediction_id": row["id"], "drift_event_id": drift_id}

    # ---- versions
    def _add_version(self, stream, version):
        if any(v["stream"] == stream and v["version"] == version["version"] for v in self.versions):
            raise ValueError(f"duplicate version {version['version']}")
        for v in self.versions:
            if v["stream"] == stream:
                v["is_active"] = False
        self.versions.append(dict(version, id=next(self._ids["version"]), is_active=True, created_at=_now()))

    def persist_version(self, stream, version, state):
        self._add_version(stream, version)
        self.state[stream] = copy.deepcopy(state)

    def activate_version(self, stream, version, state, activation=None):
        if activation:
            self.activations.append(dict(activation, id=next(self._ids["activation"]), created_at=_now().isoformat(),
                                         user_name=None, user_email=None))
        for v in self.versions:
            if v["stream"] == stream:
                v["is_active"] = v["version"] == version
        self.state[stream] = copy.deepcopy(state)

    def list_activations(self, stream, limit=200):
        return copy.deepcopy([a for a in reversed(self.activations) if a["stream"] == stream][:limit])

    def get_version(self, stream, version):
        v = next((v for v in self.versions if v["stream"] == stream and v["version"] == version), None)
        return copy.deepcopy(v) if v else None

    # ---- uploaded records
    def add_records(self, rows: list[dict], user_id=None):
        for r in rows:
            self.records.append(dict(r, id=next(self._ids["record"]), status="pending", user_id=user_id,
                                     prediction_id=None))

    def next_pending_records(self, limit):
        pending = sorted((r for r in self.records if r["status"] == "pending"),
                         key=lambda r: (str(r["purchase_date"]), r["id"]))[:limit]
        return [{"id": r["id"], "features": data_record_features(r), "target_category": r["target_category"],
                 "user_id": r["user_id"]} for r in pending]

    def count_pending_records(self):
        return sum(r["status"] == "pending" for r in self.records)


# ---------------------------------------------------------------------------
# Read-side helpers mirroring app/services/queries.py for the in-memory repository
# ---------------------------------------------------------------------------
def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def outcome_rows(repo: MemoryRepository, stream: str) -> list[dict]:
    rows = sorted((p for p in repo.predictions.values() if p["stream"] == stream and p["step"] is not None),
                  key=lambda p: p["step"])
    return [{"step": p["step"], "ts": _iso(p["outcome_at"]), "predicted": p["predicted_category"],
             "actual": p["actual_category"], "correct": bool(p["is_correct"]),
             "baseline_predicted": p["baseline_prediction"], "baseline_correct": bool(p["baseline_correct"]),
             "model_version": p["model_version"], "status": p["detector_status"], "error": p["detector_error"],
             "shadow": p["shadow_states"] or {}, "period": p["features"].get("Period"),
             "trend": p["features"].get("Trend")} for p in rows]


def drift_rows(repo: MemoryRepository, stream: str) -> list[dict]:
    rows = sorted((dict(d) for d in repo.drift_events if d["stream"] == stream), key=lambda d: d["stream_step"])
    for d in rows:
        d["detected_at"] = _iso(d.get("detected_at"))
    return rows


def version_rows(repo: MemoryRepository, stream: str) -> list[dict]:
    rows = [dict(v) for v in repo.versions if v["stream"] == stream]
    for v in rows:
        v["created_at"] = _iso(v.get("created_at"))
    return rows


def pipeline_metrics(repo: MemoryRepository, stream: str) -> dict:
    preds = [p for p in repo.predictions.values() if p["stream"] == stream]
    events, versions = drift_rows(repo, stream), version_rows(repo, stream)
    return {"predictions_made": len(preds), "outcomes_received": sum(p["actual_category"] is not None for p in preds),
            "drift_events": len(events), "failed_adaptations": sum(e["action"] == "Adaptation failed" for e in events),
            "models_created": len(versions), "adaptations": sum(v["kind"] != "initial" for v in versions),
            "last_drift_at": events[-1]["detected_at"] if events else None}
