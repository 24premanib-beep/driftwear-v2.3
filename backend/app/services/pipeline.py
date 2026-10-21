"""
PipelineService – runs the concept-drift pipeline inside the API process.

    record → features → prediction → stored in PostgreSQL
           → actual outcome arrives → error 0/1 → DDM / ADWIN / Page-Hinkley
           → STABLE / WARNING / DRIFT
           → on DRIFT: change-point window → retrain → new model version
             → model file to ModelStorageService → metadata to PostgreSQL
           → WebSocket events at every step

Two independent streams, each with its own engine, detector and model lineage:
  * live        real predictions (API), real outcomes, uploaded labeled records
  * simulation  replay of the synthetic dataset; only exists in Simulation Mode

Concurrency model: predictions run directly (read-only on the current model);
everything that changes detector or model state goes through one ordered queue
(workers/queue.py). Each job persists its results in a single transaction and
only then announces them. If persisting fails, the stream's engine is rebuilt
from the database so memory never drifts away from what is stored.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ml import config as ml_config
from ml.drift_detector import DRIFT, STABLE, STATUS_TEXT, WARNING
from ml.feature_engineering import RAW_FEATURES
from ml.model import deserialize_model, serialize_model
from ml.simulation import SimulationFeed
from ml.stream_engine import DriftEngine, EngineError, EngineSnapshot, ModelHandle, OutcomeResult, TrainedVersion

from app.errors import ConflictError, MLError, NotFoundError, ServiceUnavailableError, ValidationFailedError
from app.services import events as ev
from app.services.analytics import drift_severity
from app.services.events import EventBus, make_event, to_plain
from app.services.metrics import latency_summary
from app.services.model_storage import ModelStorage, StorageError
from app.services.repository import NewPrediction, Repository, StreamData
from app.workers.queue import InProcessQueue, TaskQueue

log = logging.getLogger(__name__)

LIVE, SIMULATION = "live", "simulation"
STREAMS = (LIVE, SIMULATION)
PERF_EVENT_EVERY = 10
MAX_BATCH = 500
LATENCY_SAMPLES = 500
MAX_REASON = 500


class PipelineStartupError(RuntimeError):
    pass


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def version_key(version: str) -> tuple[int, int]:
    try:
        major, minor = version.lstrip("v").split(".")
        return int(major), int(minor)
    except ValueError:
        return 0, 0


def is_rollback(previous: str, target: str) -> bool:
    """Activating an OLDER version than the one serving is a rollback."""
    return version_key(target) < version_key(previous)


def compact_explanation(explanation: dict | None) -> dict | None:
    """What is stored with a prediction: method, base value and the per-field contributions."""
    if not explanation:
        return None
    return to_plain({k: explanation[k] for k in ("method", "predicted", "probability", "base_value", "contributions")
                     if k in explanation})


@dataclass
class StreamRuntime:
    engine: DriftEngine
    run_id: str
    feed: SimulationFeed | None = None
    outcomes_since_perf: int = 0


@dataclass
class SimulationControl:
    running: bool = False
    speed: int = 5
    pause_on_drift: bool = True
    task: asyncio.Task | None = None
    last_message: str | None = None


class PipelineService:
    def __init__(self, repo: Repository, storage: ModelStorage, bus: EventBus, *,
                 simulation_enabled: bool = True, default_detector: str = ml_config.DEFAULT_DETECTOR,
                 tick_seconds: float = 1.0, queue: TaskQueue | None = None):
        self.repo = repo
        self.storage = storage
        self.bus = bus
        self.queue: TaskQueue = queue or InProcessQueue()
        self.simulation_enabled = simulation_enabled
        self.default_detector = default_detector
        self.tick_seconds = tick_seconds
        self.runtimes: dict[str, StreamRuntime] = {}
        self._broken: set[str] = set()
        self.sim = SimulationControl()
        self.ready = False
        self._importance_cache: dict[tuple[str, str], list[dict]] = {}
        self._adapting: dict[str, str | None] = {}           # stream -> version being trained right now
        self._reference_cache: dict[int, list[dict]] = {}     # dataset seed -> v1.0 training inputs
        # measured per process for System monitoring: model inference latency and prediction outcomes
        self._stats_lock = threading.Lock()
        self._latency = {s: deque(maxlen=LATENCY_SAMPLES) for s in STREAMS}
        self._pred_counts = {s: {"attempted": 0, "succeeded": 0, "failed": 0} for s in STREAMS}
        self._stats_since = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ================================================================ lifecycle
    async def start(self) -> None:
        await self.queue.start()
        streams = STREAMS if self.simulation_enabled else (LIVE,)
        for stream in streams:
            self.runtimes[stream] = await asyncio.to_thread(self._load_or_bootstrap, stream)
            rt = self.runtimes[stream]
            log.info("Stream '%s' ready: model %s, detector %s, %d outcomes processed",
                     stream, rt.engine.version, rt.engine.detector_name, rt.engine.next_step)
        self.ready = True

    async def stop(self) -> None:
        self.sim.running = False
        if self.sim.task and not self.sim.task.done():
            try:
                await asyncio.wait_for(self.sim.task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
                self.sim.task.cancel()
        await self.queue.stop()
        self.ready = False

    # ================================================================ load / bootstrap
    def _load_or_bootstrap(self, stream: str, seed: int = ml_config.DEFAULT_SEED) -> StreamRuntime:
        data = self.repo.load_stream(stream, ml_config.HISTORY_BUFFER)
        if data is not None and data.active is not None:
            try:
                return self._restore(stream, data)
            except StorageError as exc:
                if stream != SIMULATION:
                    raise PipelineStartupError(
                        f"The live model files could not be loaded ({exc}). Check MODEL_STORAGE_* settings; "
                        "the live model history is never re-created automatically.") from exc
                log.warning("Simulation model files missing (%s); starting a fresh simulation run", exc)
                self._delete_files(self.repo.reset_stream(SIMULATION))
        return self._bootstrap(stream, seed)

    def _bootstrap(self, stream: str, seed: int) -> StreamRuntime:
        feed = SimulationFeed.from_seed(seed)
        engine, tv = DriftEngine.bootstrap(stream, feed.training_rows(), self.default_detector)
        rt = StreamRuntime(engine, _run_id(), feed if stream == SIMULATION else None)
        stored = self._store_model(stream, rt.run_id, tv)
        self.repo.save_bootstrap(stream, self._version_row(stream, rt.run_id, tv, stored), self._state(stream, rt))
        log.info("Stream '%s' bootstrapped: v1.0 trained on %d historical records", stream, tv.records_used)
        return rt

    def _restore(self, stream: str, data: StreamData) -> StreamRuntime:
        st = data.state
        active = self._load_handle(data.active)
        baseline = active if data.baseline is None or data.baseline["version"] == active.version \
            else self._load_handle(data.baseline)
        snap = EngineSnapshot(
            stream=stream, detector=st.get("detector") or self.default_detector, current=active, baseline=baseline,
            history=data.history, next_step=int(st.get("next_step") or 0),
            detector_reset_step=int(st.get("detector_reset_step") or 0),
            refresh_anchor=int(st.get("refresh_anchor") or 0), pending_refresh=list(st.get("pending_refresh") or []),
            n_drifts=data.n_drifts, open_backfills=data.open_backfills, known_versions=set(data.versions),
        )
        engine = DriftEngine.restore(snap)
        feed = None
        if stream == SIMULATION:
            feed = SimulationFeed.from_seed(int(st.get("seed") or ml_config.DEFAULT_SEED),
                                            pointer=st.get("pointer"), trend_changes=st.get("trend_changes") or [])
        return StreamRuntime(engine, st.get("run_id") or _run_id(), feed)

    def _load_handle(self, row: dict) -> ModelHandle:
        data = self.storage.load(row["model_path"], row.get("checksum"))
        return ModelHandle(row["version"], deserialize_model(data), list(row.get("calibration_errors") or []),
                           row.get("kind") or "initial")

    def _safe_reload(self, stream: str) -> None:
        try:
            self.runtimes[stream] = self._load_or_bootstrap(stream)
            self._broken.discard(stream)
        except Exception:  # noqa: BLE001
            log.exception("Could not reload stream '%s' from the database; it is now unavailable", stream)
            self._broken.add(stream)

    def _rt(self, stream: str) -> StreamRuntime:
        if stream == SIMULATION and not self.simulation_enabled:
            raise NotFoundError("Simulation mode is disabled on this server.")
        if stream not in STREAMS:
            raise ValidationFailedError(f"Unknown stream '{stream}'. Use 'live' or 'simulation'.")
        if stream in self._broken or stream not in self.runtimes:
            raise ServiceUnavailableError("The drift pipeline is not available right now. Please try again shortly.")
        return self.runtimes[stream]

    # ================================================================ row builders
    def _store_model(self, stream: str, run_id: str, tv: TrainedVersion):
        key = f"{stream}/{run_id}/model_{tv.version.replace('.', '_')}.joblib"
        return self.storage.save(key, serialize_model(tv.model))

    @staticmethod
    def _version_row(stream: str, run_id: str, tv: TrainedVersion, stored) -> dict:
        m = to_plain(tv.metadata())
        return {
            "stream": stream, "run_id": run_id, "version": m["version"], "parent_version": m["parent_version"],
            "kind": m["kind"], "model_type": "RandomForestClassifier", "trigger": m["trigger"],
            "detector": m["detector"], "accuracy": m["accuracy"], "precision": m["precision"],
            "recall": m["recall"], "f1_score": m["f1_score"], "train_accuracy": m["train_accuracy"],
            "training_records": m["records_used"], "window_start": m["window_start"],
            "window_end": m["window_end"], "change_point_step": m["change_point_step"],
            "created_step": m["step"], "accuracy_before": m["accuracy_before"], "accuracy_after": None,
            "data_period": m["data_period"], "calibration_errors": m["calibration"],
            "model_path": stored.path, "checksum": stored.checksum, "model_size": stored.size, "is_active": True,
        }

    @staticmethod
    def _drift_row(stream: str, e: dict, error: str | None) -> dict:
        e = to_plain(e)
        return {
            "stream": stream, "event_key": e["event_id"], "detector": e["detector"], "status": e["status"],
            "action": e["action"], "error_rate": e["error_rate"], "stream_step": e["step"],
            "change_point_step": e["change_point_step"], "detection_delay": e["detection_delay"],
            "window_size": e["window_size"], "window_start": e["window_start"],
            "accuracy_stable": e["accuracy_stable"], "accuracy_degraded": e["accuracy_degraded"],
            "accuracy_after": None, "previous_model_version": e["from_version"],
            "new_model_version": e["to_version"],
            "details": {"period": e.get("period"), "trend": e.get("trend"), "purchase_date": e.get("purchase_date"),
                        "adaptation_error": error,
                        "severity": drift_severity(e["accuracy_stable"], e["accuracy_degraded"], e["error_rate"])},
        }

    @staticmethod
    def _outcome_row(o: OutcomeResult) -> dict:
        return to_plain({
            "actual_category": o.actual, "is_correct": o.is_correct, "step": o.step, "detector_status": o.status,
            "detector_error": int(not o.correct), "scored_version": o.scored_version,
            "baseline_correct": o.baseline_correct, "shadow_states": o.shadow_states, "rescored": o.rescored,
        })

    @staticmethod
    def _state(stream: str, rt: StreamRuntime) -> dict:
        e, f = rt.engine, rt.feed
        return {
            "stream": stream, "run_id": rt.run_id, "detector": e.detector_name, "next_step": e.next_step,
            "detector_reset_step": e.detector_reset_step, "refresh_anchor": e.refresh_anchor,
            "pending_refresh": list(e.pending_refresh),
            "seed": f.seed if f else None, "pointer": f.pointer if f else None,
            "trend_changes": list(f.trend_changes) if f else [],
        }

    def _delete_files(self, paths: list[str]) -> None:
        for p in paths:
            try:
                self.storage.delete(p)
            except Exception:  # noqa: BLE001
                log.warning("Could not delete model file %s", p)

    # ================================================================ events
    def _emit(self, name: str, stream: str | None, message: str, *, audience: Any = "all",
              data: dict | None = None, **top: Any) -> None:
        self.bus.publish_threadsafe(make_event(name, stream, message, audience=audience, data=data, **top))

    @staticmethod
    def _stream_audience(stream: str) -> Any:
        return "all" if stream == LIVE else "staff"

    def _listener(self, stream: str):
        audience = self._stream_audience(stream)

        def on_engine_event(name: str, payload: dict) -> None:
            if name == "DRIFT_DETECTED":
                payload = {**payload, "severity": drift_severity(payload.get("accuracy_stable"),
                                                                 payload.get("accuracy_degraded"),
                                                                 payload.get("error_rate"))}
                self._emit(ev.DRIFT_DETECTED, stream,
                           f"Concept drift detected by {payload['detector']} ({payload['severity']} severity). "
                           "Model adaptation initiated.",
                           audience=audience, detector=payload["detector"], model_version=payload["from_version"],
                           severity=payload["severity"], data=payload)
            elif name == "ADAPTATION_STARTED":
                self._adapting[stream] = payload.get("to_version")
                label = {"drift": "Retraining on the post-change window",
                         "refresh": "Refreshing with more new-pattern data",
                         "manual": "Manual retrain requested"}.get(payload.get("kind"), "Retraining")
                self._emit(ev.ADAPTATION_STARTED, stream,
                           f"Model adaptation started: {payload['from_version']} → {payload['to_version']}. {label}.",
                           audience=audience, model_version=payload["from_version"],
                           detector=payload.get("detector"), data=payload)
        return on_engine_event

    def _announce_outcome(self, stream: str, rt: StreamRuntime, out: OutcomeResult, saved: dict,
                          owner: int | None, prediction: dict, created: NewPrediction | None) -> None:
        audience = self._stream_audience(stream)
        result_audience = ("owner", owner) if (stream == LIVE and owner is not None) else "staff"
        if created is not None:
            self._emit(ev.PREDICTION_CREATED, stream,
                       f"New prediction: {created.predicted_category} ({created.confidence:.0%}).",
                       audience=result_audience, model_version=created.model_version,
                       data={"prediction_id": saved["prediction_id"], "predicted": created.predicted_category,
                             "confidence": created.confidence, "source": created.source, "step": out.step,
                             "customer_id": created.customer_id, "event_id": created.event_id})
        self._emit(ev.PREDICTION_RESULT, stream,
                   f"{'Correct' if out.is_correct else 'Wrong'}: predicted {out.predicted}, actual {out.actual}.",
                   audience=result_audience, model_version=prediction.get("model_version"),
                   data={"prediction_id": saved["prediction_id"], "step": out.step, "predicted": out.predicted,
                         "actual": out.actual, "is_correct": out.is_correct, "error": int(not out.correct),
                         "scored_version": out.scored_version, "rescored": out.rescored,
                         "baseline_prediction": out.baseline_prediction, "baseline_correct": out.baseline_correct,
                         "status": out.status, "shadow_states": out.shadow_states,
                         "rolling_accuracy": round(out.rolling_accuracy, 4),
                         "confidence": prediction.get("confidence"), "customer_id": prediction.get("customer_id")})
        if out.status != out.previous_status and out.status != DRIFT:
            if out.status == WARNING:
                self._emit(ev.WARNING_DETECTED, stream, f"{rt.engine.detector_name}: possible change detected.",
                           audience=audience, detector=rt.engine.detector_name, model_version=out.scored_version,
                           data={"step": out.step, "status": out.status, "previous_status": out.previous_status})
            else:
                self._emit(ev.STATUS_CHANGED, stream, STATUS_TEXT[out.status], audience=audience,
                           detector=rt.engine.detector_name, model_version=rt.engine.version,
                           data={"step": out.step, "status": out.status, "previous_status": out.previous_status})
        if out.adaptation_error:
            self._emit(ev.ADAPTATION_FAILED, stream, out.adaptation_error + " The previous model stays active.",
                       audience=audience, model_version=rt.engine.version,
                       data={"step": out.step, "drift_event_id": saved.get("drift_event_id")})
        if out.new_version:
            tv = out.new_version
            self._emit(ev.ADAPTATION_COMPLETED, stream,
                       f"Model adaptation completed: {tv.parent_version} → {tv.version} "
                       f"({tv.records_used} records).", audience=audience, model_version=tv.version,
                       detector=tv.detector,
                       data={"kind": tv.kind, "from_version": tv.parent_version, "to_version": tv.version,
                             "records_used": tv.records_used, "window_start": tv.window_start,
                             "window_end": tv.window_end, "accuracy_before": tv.accuracy_before,
                             "drift_event_id": saved.get("drift_event_id")})
            self._emit(ev.MODEL_VERSION_CREATED, stream, f"New model version {tv.version} is now active.",
                       audience=audience, model_version=tv.version, data=self._version_summary(tv))
        rt.outcomes_since_perf += 1
        if out.new_version or out.backfills or rt.outcomes_since_perf >= PERF_EVENT_EVERY:
            rt.outcomes_since_perf = 0
            self._emit(ev.PERFORMANCE_UPDATED, stream, "Performance metrics updated.", audience=audience,
                       model_version=rt.engine.version,
                       data={"rolling_accuracy": round(out.rolling_accuracy, 4),
                             "rolling_error": round(1 - out.rolling_accuracy, 4),
                             "records_processed": rt.engine.next_step, "status": rt.engine.status,
                             "backfills": out.backfills})

    @staticmethod
    def _version_summary(tv: TrainedVersion) -> dict:
        m = tv.metadata()
        return {k: m[k] for k in ("version", "parent_version", "kind", "trigger", "records_used", "accuracy",
                                  "f1_score", "train_accuracy", "accuracy_before", "data_period", "step")}

    # ================================================================ core step (worker thread)
    def _apply_outcome(self, stream: str, rt: StreamRuntime, record: dict, actual: str, *,
                       prediction: dict, prediction_id: int | None, new_prediction: NewPrediction | None,
                       record_id: int | None, owner: int | None, data_record_id: int | None = None) -> dict:
        try:
            return self._apply_outcome_inner(stream, rt, record, actual, prediction=prediction,
                                             prediction_id=prediction_id, new_prediction=new_prediction,
                                             record_id=record_id, owner=owner, data_record_id=data_record_id)
        finally:
            self._adapting.pop(stream, None)

    def _apply_outcome_inner(self, stream: str, rt: StreamRuntime, record: dict, actual: str, *,
                             prediction: dict, prediction_id: int | None, new_prediction: NewPrediction | None,
                             record_id: int | None, owner: int | None, data_record_id: int | None) -> dict:
        try:
            out = rt.engine.record_outcome(record, actual, prediction.get("predicted_category"),
                                           prediction.get("model_version"), prediction.get("baseline_prediction"),
                                           record_id=record_id, listener=self._listener(stream))
        except EngineError as exc:
            self._safe_reload(stream)
            raise MLError(str(exc)) from exc
        except Exception:
            self._safe_reload(stream)
            raise
        try:
            version_row = None
            if out.new_version:
                stored = self._store_model(stream, rt.run_id, out.new_version)
                version_row = self._version_row(stream, rt.run_id, out.new_version, stored)
            drift_row = self._drift_row(stream, out.drift_event, out.adaptation_error) if out.drift_event else None
            saved = self.repo.persist_outcome(
                stream=stream, outcome=self._outcome_row(out), prediction_id=prediction_id,
                new_prediction=new_prediction, drift_event=drift_row, version=version_row,
                backfills=out.backfills, state=self._state(stream, rt), data_record_id=data_record_id)
        except Exception as exc:
            log.exception("Persisting the outcome failed on stream '%s'; reloading from the database", stream)
            self._safe_reload(stream)
            self._emit(ev.PIPELINE_ERROR, stream, "A result could not be saved. The pipeline was reloaded from the "
                       "database; the record was not counted.", audience="staff")
            raise ServiceUnavailableError("The result could not be saved. Please retry.") from exc
        self._announce_outcome(stream, rt, out, saved, owner, prediction, new_prediction)
        return {
            "prediction_id": saved["prediction_id"], "step": out.step, "actual_category": out.actual,
            "predicted_category": out.predicted, "is_correct": out.is_correct, "scored_version": out.scored_version,
            "rescored": out.rescored, "status": out.status, "previous_status": out.previous_status,
            "rolling_accuracy": round(out.rolling_accuracy, 4),
            "drift_detected": out.drift_event is not None,
            "drift_event_id": saved.get("drift_event_id"),
            "new_model_version": out.new_version.version if out.new_version else None,
            "adaptation_error": out.adaptation_error,
        }

    def _predict_and_learn(self, stream: str, rt: StreamRuntime, record: dict, actual: str, *, source: str,
                           user_id: int | None, record_id: int | None, data_record_id: int | None) -> dict:
        self._count(stream, "attempted")
        try:
            pred = self._timed_predict(stream, rt.engine, record)
        except Exception:
            self._count(stream, "failed")
            raise
        newp = NewPrediction(
            stream=stream, source=source, user_id=user_id, customer_id=record.get("Customer_ID"), features=record,
            predicted_category=pred.predicted, confidence=round(pred.confidence, 4),
            probabilities={k: round(v, 4) for k, v in pred.probabilities.items()},
            baseline_prediction=pred.baseline_prediction, model_version=pred.model_version,
            status_at_prediction=pred.status, data_record_id=data_record_id)
        prediction = {"predicted_category": pred.predicted, "model_version": pred.model_version,
                      "baseline_prediction": pred.baseline_prediction, "confidence": newp.confidence,
                      "customer_id": newp.customer_id}
        try:
            res = self._apply_outcome(stream, rt, record, actual, prediction=prediction, prediction_id=None,
                                      new_prediction=newp, record_id=record_id, owner=user_id,
                                      data_record_id=data_record_id)
        except Exception:
            self._count(stream, "failed")
            raise
        self._count(stream, "succeeded")
        return res

    # ================================================================ live predictions
    async def predict(self, *, user_id: int, record: dict, actual: str | None = None, source: str = "api",
                      event_id: str | None = None, explain: bool = True) -> dict:
        """Live prediction: validate → (dedupe event) → features → model → store → announce.

        `source` is "api" (the prediction form) or "event" (real-time ingestion). An `event_id`
        makes ingestion idempotent: the same event is never predicted twice.
        """
        rt = self._rt(LIVE)
        if event_id:
            existing = await asyncio.to_thread(self.repo.find_prediction_by_event, LIVE, event_id)
            if existing is not None:
                raise ConflictError(f"Event '{event_id}' was already ingested (prediction #{existing['id']}).",
                                    details={"prediction_id": existing["id"], "event_id": event_id})
        self._count(LIVE, "attempted")
        try:
            pred = await asyncio.to_thread(self._timed_predict, LIVE, rt.engine, record, explain)
        except EngineError as exc:
            self._count(LIVE, "failed")
            raise MLError(str(exc)) from exc
        except Exception:
            self._count(LIVE, "failed")
            raise
        newp = NewPrediction(
            stream=LIVE, source=source, user_id=user_id, customer_id=record.get("Customer_ID"), features=record,
            predicted_category=pred.predicted, confidence=round(pred.confidence, 4),
            probabilities={k: round(v, 4) for k, v in pred.probabilities.items()},
            baseline_prediction=pred.baseline_prediction, model_version=pred.model_version,
            status_at_prediction=pred.status, event_id=event_id,
            explanation=compact_explanation(pred.explanation))
        try:
            row = await asyncio.to_thread(self.repo.create_prediction, newp)
        except ConflictError:
            raise                       # the same event id raced in twice: a duplicate, not a failure
        except Exception:
            self._count(LIVE, "failed")
            raise
        self._count(LIVE, "succeeded")
        self._emit(ev.PREDICTION_CREATED, LIVE, f"New prediction: {pred.predicted} ({pred.confidence:.0%}).",
                   audience=("owner", user_id), model_version=pred.model_version,
                   data={"prediction_id": row["id"], "predicted": pred.predicted, "confidence": newp.confidence,
                         "source": source, "customer_id": newp.customer_id, "event_id": event_id})
        result = {"prediction": row, "outcome": None, "explanation": newp.explanation}
        if actual is not None:
            result["outcome"] = await self.record_outcome(row["id"], actual)
            result["prediction"] = await asyncio.to_thread(self.repo.get_prediction, row["id"])
        return result

    async def record_outcome(self, prediction_id: int, actual: str) -> dict:
        return await self.queue.submit(lambda: self._outcome_job(prediction_id, actual), name="outcome")

    def _outcome_job(self, prediction_id: int, actual: str) -> dict:
        p = self.repo.get_prediction(prediction_id)
        if p is None:
            raise NotFoundError("Prediction not found.")
        if p["stream"] != LIVE:
            raise ConflictError("Simulation predictions are labeled by the simulator.")
        if p.get("actual_category") is not None:
            raise ConflictError("This prediction already has an actual outcome.")
        rt = self._rt(LIVE)
        return self._apply_outcome(LIVE, rt, dict(p["features"]), actual, prediction=p, prediction_id=prediction_id,
                                   new_prediction=None, record_id=p.get("data_record_id"), owner=p.get("user_id"),
                                   data_record_id=None)

    # ================================================================ uploaded records → live stream
    async def process_uploaded(self, limit: int) -> dict:
        limit = max(1, min(int(limit), MAX_BATCH))
        return await self.queue.submit(lambda: self._uploads_job(limit), name="process-uploads")

    def _uploads_job(self, limit: int) -> dict:
        rt = self._rt(LIVE)
        records = self.repo.next_pending_records(limit)
        drifts, versions, correct = [], [], 0
        for r in records:
            res = self._predict_and_learn(LIVE, rt, dict(r["features"]), r["target_category"], source="upload",
                                          user_id=r.get("user_id"), record_id=r["id"], data_record_id=r["id"])
            correct += int(res["is_correct"])
            if res["drift_detected"]:
                drifts.append(res["drift_event_id"])
            if res["new_model_version"]:
                versions.append(res["new_model_version"])
        remaining = self.repo.count_pending_records()
        summary = {"processed": len(records), "correct": correct, "drift_events": drifts, "new_versions": versions,
                   "remaining": remaining, "model_version": rt.engine.version, "status": rt.engine.status}
        if records:
            self._emit(ev.RECORDS_PROCESSED, LIVE, f"Processed {len(records)} uploaded records "
                       f"({correct} correct); {remaining} still pending.", audience="staff", data=summary)
        return summary

    # ================================================================ model management
    async def adapt_now(self, stream: str, actor: str) -> dict:
        return await self.queue.submit(lambda: self._adapt_job(stream, actor), name="manual-adapt")

    def _adapt_job(self, stream: str, actor: str) -> dict:
        try:
            return self._adapt_job_inner(stream, actor)
        finally:
            self._adapting.pop(stream, None)

    def _adapt_job_inner(self, stream: str, actor: str) -> dict:
        rt = self._rt(stream)
        try:
            tv = rt.engine.adapt_now(trigger=f"Manual retrain by {actor}", listener=self._listener(stream))
        except EngineError as exc:
            raise MLError(str(exc)) from exc
        try:
            stored = self._store_model(stream, rt.run_id, tv)
            self.repo.persist_version(stream, self._version_row(stream, rt.run_id, tv, stored), self._state(stream, rt))
        except Exception as exc:
            log.exception("Saving manual adaptation failed")
            self._safe_reload(stream)
            raise ServiceUnavailableError("The new model could not be saved. The previous model is still active.") from exc
        audience = self._stream_audience(stream)
        self._emit(ev.ADAPTATION_COMPLETED, stream, f"Model adaptation completed: {tv.parent_version} → {tv.version}.",
                   audience=audience, model_version=tv.version, data=self._version_summary(tv))
        self._emit(ev.MODEL_VERSION_CREATED, stream, f"New model version {tv.version} is now active.",
                   audience=audience, model_version=tv.version, data=self._version_summary(tv))
        return self._version_summary(tv)

    async def activate_version(self, stream: str, version: str, actor: str, *, user_id: int | None = None,
                               reason: str | None = None, rollback_only: bool = False) -> dict:
        """Make a stored version active again. Nothing is deleted: every version stays in the registry.

        1. the version must exist on the stream (404) and must not already be active (409)
        2. rollback_only (POST /api/models/rollback): the target must be OLDER than the active model (409)
        3. the model file is loaded and its SHA-256 verified before unpickling (503, nothing changed, on failure)
        4. the engine switches, the detector restarts for that model, scheduled refreshes are cancelled
        5. is_active + the activation record (who, from, to, why) commit in ONE transaction
        6. MODEL_ACTIVATED is broadcast; every later prediction uses the restored model
        """
        return await self.queue.submit(
            lambda: self._activate_job(stream, version, actor, user_id=user_id, reason=reason,
                                       rollback_only=rollback_only), name="activate")

    def _activate_job(self, stream: str, version: str, actor: str, *, user_id: int | None = None,
                      reason: str | None = None, rollback_only: bool = False) -> dict:
        rt = self._rt(stream)
        row = self.repo.get_version(stream, version)
        if row is None:
            raise NotFoundError(f"Model version {version} does not exist on the {stream} stream.")
        if row["version"] == rt.engine.version:
            raise ConflictError(f"{version} is already the active model.")
        previous = rt.engine.version
        rollback = is_rollback(previous, version)
        if rollback_only and not rollback:
            raise ConflictError(f"{version} is newer than the active model {previous}. A rollback restores an older "
                                "version; use activation to move forward.")
        try:
            handle = self._load_handle(row)          # checksum verified before the file is unpickled
        except StorageError as exc:
            raise ServiceUnavailableError(f"The model file for {version} could not be loaded: {exc}") from exc
        cancelled = len(rt.engine.pending_refresh)
        rt.engine.activate(handle)
        activation = {"stream": stream, "from_version": previous, "to_version": version,
                      "action": "rollback" if rollback else "activate",
                      "reason": (reason or "").strip()[:MAX_REASON] or None, "user_id": user_id,
                      "at_step": rt.engine.next_step}
        try:
            self.repo.activate_version(stream, version, self._state(stream, rt), activation=activation)
        except Exception as exc:
            self._safe_reload(stream)
            raise ServiceUnavailableError("The model could not be activated. Nothing was changed.") from exc
        message = (f"Rollback completed: {version} is active again (was {previous}). Monitoring restarted."
                   if rollback else f"{version} activated (was {previous}). Monitoring restarted.")
        if cancelled:
            message += f" {cancelled} scheduled refresh(es) of {previous} were cancelled."
        # the actor and the reason are stored (activation history, audit log), not broadcast to every user
        self._emit(ev.MODEL_ACTIVATED, stream, message, audience=self._stream_audience(stream), model_version=version,
                   data={"from_version": previous, "to_version": version, "rollback": rollback,
                         "action": activation["action"], "cancelled_refreshes": cancelled})
        return {"previous_version": previous, "active_version": version}

    async def set_detector(self, stream: str, name: str) -> dict:
        return await self.queue.submit(lambda: self._detector_job(stream, name), name="set-detector")

    def _detector_job(self, stream: str, name: str) -> dict:
        rt = self._rt(stream)
        previous = rt.engine.detector_name
        try:
            rt.engine.set_detector(name)
        except EngineError as exc:
            raise ValidationFailedError(str(exc)) from exc
        self.repo.save_state(stream, self._state(stream, rt))
        self._emit(ev.DETECTOR_CHANGED, stream, f"Drift detector switched from {previous} to {name}.",
                   audience=self._stream_audience(stream), detector=name, model_version=rt.engine.version,
                   data={"previous": previous, "detector": name, "status": rt.engine.status})
        return rt.engine.status_info()

    async def version_importance(self, stream: str, version: str) -> list[dict]:
        rt = self._rt(stream)
        if version == rt.engine.version:
            df = await asyncio.to_thread(rt.engine.feature_importance, "current")
            return df.to_dict("records")
        key = (stream, version)
        if key not in self._importance_cache:
            row = await asyncio.to_thread(self.repo.get_version, stream, version)
            if row is None:
                raise NotFoundError(f"Model version {version} not found.")
            handle = await asyncio.to_thread(self._load_handle, row)
            from ml.model import feature_importance
            self._importance_cache[key] = feature_importance(handle.model).to_dict("records")
        return self._importance_cache[key]

    # ================================================================ simulation mode
    def simulation_state(self) -> dict:
        rt = self._rt(SIMULATION)
        return {"mode": "simulation", "running": self.sim.running, "speed": self.sim.speed,
                "pause_on_drift": self.sim.pause_on_drift, "last_message": self.sim.last_message,
                "model_version": rt.engine.version, "status": rt.engine.status,
                "detector": rt.engine.detector_name, **rt.feed.info()}

    def _emit_sim_state(self) -> None:
        self._emit(ev.SIMULATION_STATE, SIMULATION, self.sim.last_message or "Simulation state updated.",
                   audience="staff", data=self.simulation_state())

    async def simulate(self, n: int, stop_on_drift: bool = True) -> dict:
        n = max(1, min(int(n), MAX_BATCH))
        res = await self.queue.submit(lambda: self._sim_job(n, stop_on_drift), name="simulate")
        if not self.sim.running:
            self._emit_sim_state()
        return res

    def _sim_job(self, n: int, stop_on_drift: bool) -> dict:
        rt = self._rt(SIMULATION)
        processed, correct, drifts, versions, stopped = 0, 0, [], [], False
        for _ in range(n):
            nxt = rt.feed.next_record()
            if nxt is None:
                break
            record, actual = nxt
            res = self._predict_and_learn(SIMULATION, rt, record, actual, source="simulation", user_id=None,
                                          record_id=record.get("Record_ID"), data_record_id=None)
            processed += 1
            correct += int(res["is_correct"])
            if res["new_model_version"]:
                versions.append(res["new_model_version"])
            if res["drift_detected"]:
                drifts.append(res["drift_event_id"])
                if stop_on_drift:
                    stopped = True
                    break
        return {"processed": processed, "correct": correct, "drift_events": drifts, "new_versions": versions,
                "stopped_on_drift": stopped, "finished": rt.feed.finished, "model_version": rt.engine.version,
                "status": rt.engine.status, "pointer": rt.feed.pointer}

    async def start_simulation(self, speed: int | None = None, pause_on_drift: bool | None = None) -> dict:
        rt = self._rt(SIMULATION)
        if speed is not None:
            self.sim.speed = max(1, min(int(speed), 50))
        if pause_on_drift is not None:
            self.sim.pause_on_drift = bool(pause_on_drift)
        if rt.feed.finished:
            raise ConflictError("The simulated stream has ended. Reset the simulation to start again.")
        if not self.sim.running:
            self.sim.running = True
            self.sim.last_message = "Simulation running."
            self.sim.task = asyncio.create_task(self._sim_loop(), name="simulation-loop")
        self._emit_sim_state()
        return self.simulation_state()

    async def pause_simulation(self, message: str = "Simulation paused.") -> dict:
        self._rt(SIMULATION)
        self.sim.running = False
        self.sim.last_message = message
        self._emit_sim_state()
        return self.simulation_state()

    async def _sim_loop(self) -> None:
        try:
            while self.sim.running:
                res = await self.queue.submit(lambda: self._sim_job(self.sim.speed, self.sim.pause_on_drift),
                                              name="simulate")
                if res["finished"]:
                    self.sim.running = False
                    self.sim.last_message = "All records processed: the simulated stream has finished."
                elif res["drift_events"] and self.sim.pause_on_drift:
                    self.sim.running = False
                    self.sim.last_message = "Paused: concept drift detected and the model was adapted."
                self._emit_sim_state()
                if self.sim.running:
                    await asyncio.sleep(self.tick_seconds)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Simulation loop stopped")
            self.sim.running = False
            self.sim.last_message = f"Simulation stopped: {getattr(exc, 'message', 'internal error')}"
            self._emit_sim_state()

    async def trend_change(self) -> dict:
        return await self.queue.submit(self._trend_job, name="trend-change")

    def _trend_job(self) -> dict:
        rt = self._rt(SIMULATION)
        info = rt.feed.trend_change()
        if not info["ok"]:
            raise ConflictError(info["message"])
        info["step"] = rt.engine.next_step
        self.repo.save_state(SIMULATION, self._state(SIMULATION, rt))
        self._emit(ev.TREND_CHANGED, SIMULATION, info["message"], audience="staff", data=info)
        return info

    async def reset_simulation(self, regenerate: bool = False, seed: int | None = None) -> dict:
        self.sim.running = False
        if self.sim.task and not self.sim.task.done():
            await asyncio.wait_for(self.sim.task, timeout=30)
        return await self.queue.submit(lambda: self._reset_job(regenerate, seed), name="reset-simulation")

    def _reset_job(self, regenerate: bool, seed: int | None) -> dict:
        if not self.simulation_enabled:
            raise NotFoundError("Simulation mode is disabled on this server.")
        if seed is None:
            seed = random.randint(1, 999_999) if regenerate else ml_config.DEFAULT_SEED
        self._delete_files(self.repo.reset_stream(SIMULATION))
        self._importance_cache = {k: v for k, v in self._importance_cache.items() if k[0] != SIMULATION}
        self.runtimes[SIMULATION] = self._bootstrap(SIMULATION, int(seed))
        self._broken.discard(SIMULATION)
        self.sim.last_message = f"Simulation reset (dataset seed {seed}). Model v1.0 retrained on historical data."
        self._emit(ev.SIMULATION_RESET, SIMULATION, self.sim.last_message, audience="staff", data={"seed": seed})
        self._emit_sim_state()
        return self.simulation_state()

    # ================================================================ read-only status
    def status(self, stream: str) -> dict:
        rt = self._rt(stream)
        info = rt.engine.status_info()
        info["queue_pending"] = self.queue.pending
        info["adapting"] = stream in self._adapting
        info["adapting_to"] = self._adapting.get(stream)
        info["mode"] = "simulation" if stream == SIMULATION else "live"
        if rt.feed:
            info["simulation"] = {"running": self.sim.running, **rt.feed.info()}
        return info

    def notify(self, name: str, stream: str | None, message: str, *, audience: Any = "all",
               data: dict | None = None) -> None:
        """For API routes that change data outside the pipeline (e.g. uploads)."""
        self._emit(name, stream, message, audience=audience, data=data)

    # ================================================================ runtime prediction metrics
    def _timed_predict(self, stream: str, engine: DriftEngine, record: dict, explain: bool = False):
        start = time.perf_counter()
        pred = engine.predict(record, explain)
        elapsed = (time.perf_counter() - start) * 1000
        with self._stats_lock:
            self._latency[stream].append(elapsed)
        return pred

    def _count(self, stream: str, key: str) -> None:
        with self._stats_lock:
            self._pred_counts[stream][key] += 1

    def prediction_metrics(self, stream: str) -> dict:
        """Model inference latency (last LATENCY_SAMPLES predictions) and prediction outcomes since start.
        success_rate = succeeded / (succeeded + failed); duplicate event ids are neither."""
        with self._stats_lock:
            counts = dict(self._pred_counts[stream])
            samples = list(self._latency[stream])
        done = counts["succeeded"] + counts["failed"]
        return {"since": self._stats_since, **counts,
                "success_rate": round(counts["succeeded"] / done, 4) if done else None,
                "latency": latency_summary(samples),
                "note": f"Model inference time of the last {LATENCY_SAMPLES} predictions and prediction outcomes "
                        "since this API process started."}

    def activation_history(self, stream: str) -> list[dict]:
        return self.repo.list_activations(stream)

    def queue_stats(self) -> dict:
        stats = getattr(self.queue, "stats", None)
        return dict(stats) if isinstance(stats, dict) else {"pending": self.queue.pending}

    def is_adapting(self, stream: str) -> bool:
        return stream in self._adapting

    # ================================================================ data drift reference
    def _historical_inputs(self, seed: int) -> list[dict]:
        if seed not in self._reference_cache:
            rows = SimulationFeed.from_seed(seed).training_rows()
            self._reference_cache[seed] = [{k: to_plain(r[k]) for k in RAW_FEATURES}
                                           for r in rows.to_dict("records")]
        return self._reference_cache[seed]

    def reference_inputs(self, stream: str, which: str = "baseline") -> tuple[list[dict], dict]:
        """Reference window for DATA drift.

        baseline: the historical records model v1.0 was trained on (fixed; the default).
        active:   the records the ACTIVE model was trained on, when they are still in memory and
                  there are at least 50 of them; otherwise falls back to baseline (and says so).
        """
        rt = self._rt(stream)
        seed = rt.feed.seed if rt.feed else ml_config.DEFAULT_SEED
        note = None
        if which == "active":
            row = self.repo.get_version(stream, rt.engine.version)
            if row and row.get("window_start") is not None:
                lo, hi = int(row["window_start"]), int(row["window_end"])
                recs = [{k: h["record"].get(k) for k in RAW_FEATURES}
                        for h in rt.engine.history if lo <= h["step"] <= hi]
                if len(recs) >= 50:
                    return recs, {"source": "active_training_window", "version": rt.engine.version,
                                  "label": f"Training window of {rt.engine.version} (records {lo}–{hi})"}
                note = (f"{rt.engine.version} was trained on only {len(recs)} records; "
                        "using the historical baseline instead.")
            else:
                note = f"{rt.engine.version} was trained on the historical data."
        info = {"source": "historical", "version": "v1.0",
                "label": "Historical data used to train v1.0"}
        if note:
            info["note"] = note
        return self._historical_inputs(seed), info
