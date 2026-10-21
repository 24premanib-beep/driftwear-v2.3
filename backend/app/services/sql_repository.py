"""
PostgreSQL implementation of the pipeline Repository (see services/repository.py).

Each public method runs in exactly one transaction, so an outcome, its drift
event, the new active model version and the engine state are committed
together or not at all.
"""
from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.database import Database
from app.database.models import (DataRecord, DriftEvent, ModelActivation, ModelVersion, Prediction, StreamState, User,
                                 utcnow)
from app.errors import ConflictError, NotFoundError
from app.services.repository import (NewPrediction, StreamData, data_record_features, history_item,
                                     open_backfills)

STATE_FIELDS = ("run_id", "detector", "next_step", "detector_reset_step", "refresh_anchor", "pending_refresh",
                "seed", "pointer", "trend_changes")


def row_dict(obj) -> dict | None:
    """ORM object → plain dict of its column values."""
    if obj is None:
        return None
    return {attr.key: getattr(obj, attr.key) for attr in inspect(obj).mapper.column_attrs}


def activation_rows(s: Session, stream: str, limit: int = 200) -> list[dict]:
    """model_activations rows (newest first) with the acting user's name; shared with the read-side queries."""
    rows = s.execute(select(ModelActivation, User.name, User.email)
                     .outerjoin(User, User.id == ModelActivation.user_id)
                     .where(ModelActivation.stream == stream)
                     .order_by(ModelActivation.id.desc()).limit(limit)).all()
    out = []
    for act, name, email in rows:
        d = row_dict(act)
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        d.update(user_name=name, user_email=email)
        out.append(d)
    return out


class SqlRepository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _apply_state(s: Session, stream: str, state: dict) -> None:
        obj = s.get(StreamState, stream)
        if obj is None:
            obj = StreamState(stream=stream)
            s.add(obj)
        for key in STATE_FIELDS:
            if key in state:
                setattr(obj, key, state[key])
        obj.updated_at = utcnow()

    @staticmethod
    def _deactivate(s: Session, stream: str) -> None:
        s.execute(update(ModelVersion).where(ModelVersion.stream == stream, ModelVersion.is_active.is_(True))
                  .values(is_active=False))

    # ------------------------------------------------------------------ stream lifecycle
    def load_stream(self, stream: str, history_limit: int) -> StreamData | None:
        with self.db.session() as s:
            st = s.get(StreamState, stream)
            if st is None:
                return None
            versions = s.scalars(select(ModelVersion).where(ModelVersion.stream == stream)
                                 .order_by(ModelVersion.id)).all()
            labeled = s.scalars(select(Prediction)
                                .where(Prediction.stream == stream, Prediction.step.is_not(None))
                                .order_by(Prediction.step.desc()).limit(history_limit)).all()
            drifts = s.scalars(select(DriftEvent).where(DriftEvent.stream == stream)).all()
            vrows = [row_dict(v) for v in versions]
            return StreamData(
                state=row_dict(st),
                active=next((v for v in vrows if v["is_active"]), None),
                baseline=next((v for v in vrows if v["kind"] == "initial"), None),
                versions=[v["version"] for v in vrows],
                history=[history_item(row_dict(p)) for p in reversed(labeled)],
                n_drifts=len(drifts),
                open_backfills=open_backfills([row_dict(d) for d in drifts], vrows),
            )

    def save_bootstrap(self, stream: str, version: dict, state: dict) -> None:
        with self.db.transaction() as s:
            self._deactivate(s, stream)
            s.add(ModelVersion(**version))
            self._apply_state(s, stream, state)

    def save_state(self, stream: str, state: dict) -> None:
        with self.db.transaction() as s:
            self._apply_state(s, stream, state)

    def reset_stream(self, stream: str) -> list[str]:
        with self.db.transaction() as s:
            paths = list(s.scalars(select(ModelVersion.model_path).where(ModelVersion.stream == stream)))
            s.execute(delete(ModelVersion).where(ModelVersion.stream == stream))
            s.execute(delete(DriftEvent).where(DriftEvent.stream == stream))
            s.execute(delete(Prediction).where(Prediction.stream == stream))
            s.execute(delete(StreamState).where(StreamState.stream == stream))
            s.execute(delete(ModelActivation).where(ModelActivation.stream == stream))
        return paths

    # ------------------------------------------------------------------ predictions
    def create_prediction(self, p: NewPrediction) -> dict:
        try:
            with self.db.transaction() as s:
                obj = Prediction(**asdict(p))
                s.add(obj)
                s.flush()
                return row_dict(obj)
        except IntegrityError as exc:
            if p.event_id:          # uq_predictions_stream_event: two requests raced with the same event id
                raise ConflictError(f"Event '{p.event_id}' was already ingested.") from exc
            raise

    def get_prediction(self, prediction_id: int) -> dict | None:
        with self.db.session() as s:
            return row_dict(s.get(Prediction, prediction_id))

    def find_prediction_by_event(self, stream: str, event_id: str) -> dict | None:
        with self.db.session() as s:
            return row_dict(s.scalar(select(Prediction).where(Prediction.stream == stream,
                                                              Prediction.event_id == event_id)))

    def persist_outcome(self, *, stream: str, outcome: dict, prediction_id: int | None,
                        new_prediction: NewPrediction | None, drift_event: dict | None, version: dict | None,
                        backfills: list[dict], state: dict, data_record_id: int | None = None) -> dict:
        with self.db.transaction() as s:
            if prediction_id is None:
                p = Prediction(**asdict(new_prediction))
                s.add(p)
            else:
                p = s.get(Prediction, prediction_id, with_for_update=True)
                if p is None:
                    raise NotFoundError("Prediction not found.")
                if p.actual_category is not None:
                    raise ConflictError("This prediction already has an actual outcome.")
            for key, value in outcome.items():
                setattr(p, key, value)
            p.outcome_at = utcnow()
            s.flush()

            drift_id = None
            if drift_event:
                d = DriftEvent(**drift_event)
                s.add(d)
                s.flush()
                drift_id = d.id
            if version:
                self._deactivate(s, stream)
                s.add(ModelVersion(**version, drift_event_id=drift_id))
            for b in backfills:
                if b["kind"] == "drift_event":
                    s.execute(update(DriftEvent).where(DriftEvent.stream == stream, DriftEvent.event_key == b["key"])
                              .values(accuracy_after=b["accuracy_after"]))
                else:
                    s.execute(update(ModelVersion)
                              .where(ModelVersion.stream == stream, ModelVersion.version == b["key"])
                              .values(accuracy_after=b["accuracy_after"]))
            if data_record_id is not None:
                s.execute(update(DataRecord).where(DataRecord.id == data_record_id)
                          .values(status="processed", prediction_id=p.id, processed_at=utcnow()))
            self._apply_state(s, stream, state)
            return {"prediction_id": p.id, "drift_event_id": drift_id}

    # ------------------------------------------------------------------ model versions
    def persist_version(self, stream: str, version: dict, state: dict) -> None:
        with self.db.transaction() as s:
            self._deactivate(s, stream)
            s.add(ModelVersion(**version))
            self._apply_state(s, stream, state)

    def activate_version(self, stream: str, version: str, state: dict, activation: dict | None = None) -> None:
        with self.db.transaction() as s:
            target = s.scalar(select(ModelVersion).where(ModelVersion.stream == stream,
                                                         ModelVersion.version == version))
            if target is None:
                raise NotFoundError(f"Model version {version} not found.")
            self._deactivate(s, stream)
            s.flush()
            target.is_active = True
            if activation:
                s.add(ModelActivation(**activation))
            self._apply_state(s, stream, state)

    def list_activations(self, stream: str, limit: int = 200) -> list[dict]:
        with self.db.session() as s:
            return activation_rows(s, stream, limit)

    def get_version(self, stream: str, version: str) -> dict | None:
        with self.db.session() as s:
            return row_dict(s.scalar(select(ModelVersion).where(ModelVersion.stream == stream,
                                                                ModelVersion.version == version)))

    # ------------------------------------------------------------------ uploaded records
    def next_pending_records(self, limit: int) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(DataRecord).where(DataRecord.status == "pending")
                             .order_by(DataRecord.purchase_date, DataRecord.id).limit(limit)).all()
            return [{"id": r.id, "features": data_record_features(row_dict(r)),
                     "target_category": r.target_category, "user_id": r.user_id} for r in rows]

    def count_pending_records(self) -> int:
        with self.db.session() as s:
            return int(s.scalar(select(func.count()).select_from(DataRecord)
                                .where(DataRecord.status == "pending")) or 0)
