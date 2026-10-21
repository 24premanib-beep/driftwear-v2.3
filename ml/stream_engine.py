"""
DriftEngine – the Learn → Predict → Monitor → Detect Drift → Adapt loop.

Refactored from the original `StreamEngine` (legacy_streamlit/src/stream_engine.py)
for a real-time backend. The drift maths is unchanged:

  * River DDM / ADWIN / Page-Hinkley through `DriftMonitor`
  * detector reset + calibration with out-of-fold errors after every (re)training
  * change-point estimate → sliding retraining window (15–300 records)
  * drift → major version (v1.0 → v2.0); scheduled refreshes at +25/+75/+150
    new-pattern records → minor versions (v2.1, v2.2, v2.3)
  * a frozen v1.0 "static" baseline predicts every record for comparison
  * "accuracy after" is filled in once PERF_EVAL_WINDOW more records arrive

What changed, and why:

  1. Prediction and ground truth are separate calls. `predict()` never touches
     the detector; `record_outcome()` receives the real category whenever it
     becomes available, computes the 0/1 error and feeds the detector. The
     simulator calls both back to back, which reproduces the original stream.
  2. Retraining uses the labeled outcomes the engine has seen (held in a
     bounded in-memory buffer that the backend restores from PostgreSQL), not
     rows looked up in the CSV.
  3. The engine performs no I/O. Every call returns a result object (new model
     version, drift event, metric back-fills) and the caller persists it. That
     keeps this module testable without a database and lets the backend choose
     where models and events are stored.
  4. Additive: the detectors that are not driving adaptation run as "shadow"
     monitors on the same error stream, so DDM, ADWIN and Page-Hinkley can be
     compared on real data. Only the primary detector triggers adaptation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from ml import config
from ml.adaptation import (next_version, retrain_on_rows, select_manual_window, select_window,
                           validation_report)
from ml.drift_detector import DRIFT, STABLE, STATUS_TEXT, WARNING, DriftMonitor, available_detectors
from ml.evaluation import accuracy_between
from ml.explain import explain_prediction
from ml.feature_engineering import RAW_FEATURES, build_features, record_to_frame
from ml.model import feature_importance, predict_record, train_model

Listener = Callable[[str, dict], None]

HISTORY_COLUMNS = ["step", "record_id", "actual", "predicted", "correct", "baseline_pred",
                   "baseline_correct", "model_version", "detector_status"]


class EngineError(RuntimeError):
    """A request the engine cannot fulfil (e.g. not enough labeled data)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _round(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(float(x), digits)


# ----------------------------------------------------------------------------- data classes
@dataclass
class ModelHandle:
    """A trained model plus what the detector needs to monitor it."""
    version: str
    model: Any
    calibration: list[int] = field(default_factory=list)
    kind: str = "initial"


@dataclass
class TrainedVersion:
    """A newly created model version, ready to be stored by the caller."""
    version: str
    parent_version: str | None
    kind: str                      # initial | drift | refresh | manual
    trigger: str
    model: Any
    step: int                      # stream step at which it was created (-1 = before the stream)
    records_used: int
    window_start: int | None
    window_end: int | None
    change_point_step: int | None
    train_accuracy: float
    validation: dict | None        # out-of-fold accuracy / precision / recall / f1
    calibration: list[int]
    accuracy_before: float | None
    data_period: str
    detector: str
    created_at: str = field(default_factory=_now)

    @property
    def handle(self) -> ModelHandle:
        return ModelHandle(self.version, self.model, list(self.calibration), self.kind)

    def metadata(self) -> dict:
        v = self.validation or {}
        return {
            "version": self.version, "parent_version": self.parent_version, "kind": self.kind,
            "trigger": self.trigger, "step": self.step, "records_used": self.records_used,
            "window_start": self.window_start, "window_end": self.window_end,
            "change_point_step": self.change_point_step,
            "train_accuracy": _round(self.train_accuracy),
            "accuracy": _round(v.get("accuracy")), "precision": _round(v.get("precision")),
            "recall": _round(v.get("recall")), "f1_score": _round(v.get("f1")),
            "accuracy_before": self.accuracy_before, "data_period": self.data_period,
            "detector": self.detector, "calibration": list(self.calibration),
            "created_at": self.created_at,
        }


@dataclass
class PredictionResult:
    predicted: str
    confidence: float
    probabilities: dict[str, float]
    baseline_prediction: str
    model_version: str
    status: str
    explanation: dict | None = None    # per-prediction feature contributions (ml/explain.py), on request


@dataclass
class OutcomeResult:
    step: int
    actual: str
    predicted: str                 # what the stored prediction said
    is_correct: bool               # ... and whether that was right
    scored_version: str            # model whose error was fed to the detector
    correct: bool                  # detector input (False = error 1)
    rescored: bool                 # True if the prediction came from an older model
    baseline_prediction: str
    baseline_correct: bool
    previous_status: str
    status: str
    shadow_states: dict[str, str]
    rolling_accuracy: float
    drift_event: dict | None = None
    new_version: TrainedVersion | None = None
    adaptation_error: str | None = None
    backfills: list[dict] = field(default_factory=list)


@dataclass
class EngineSnapshot:
    """Everything needed to rebuild an engine after a restart (loaded from the DB)."""
    stream: str
    detector: str
    current: ModelHandle
    baseline: ModelHandle
    history: list[dict]
    next_step: int
    detector_reset_step: int
    refresh_anchor: int
    pending_refresh: list[int]
    n_drifts: int
    open_backfills: list[dict]
    known_versions: set[str]


# ----------------------------------------------------------------------------- engine
class DriftEngine:
    def __init__(self, stream: str, detector_name: str = config.DEFAULT_DETECTOR):
        self.stream = stream
        self.detector_name = detector_name if detector_name in available_detectors() else "DDM"
        self.monitor = DriftMonitor(self.detector_name)
        self.shadows: dict[str, DriftMonitor] = {}
        self.current: ModelHandle | None = None
        self.baseline: ModelHandle | None = None
        self.history: list[dict] = []
        self._hist_cache: pd.DataFrame | None = None
        self._recent: deque[int] = deque(maxlen=config.LIVE_ROLLING_WINDOW)
        self.next_step = 0
        self.detector_reset_step = 0
        self.detector_prime: list[int] = []
        self.warning_start: int | None = None
        self.refresh_anchor = 0
        self.pending_refresh: list[int] = []
        self.n_drifts = 0
        self.open_backfills: list[dict] = []
        self.known_versions: set[str] = set()
        self._build_shadows()

    # ------------------------------------------------------------------ construction
    @classmethod
    def bootstrap(cls, stream: str, train_rows: pd.DataFrame,
                  detector_name: str = config.DEFAULT_DETECTOR) -> tuple["DriftEngine", TrainedVersion]:
        """Train model v1.0 on historical data (original `new_simulation`)."""
        if len(train_rows) < 10:
            raise EngineError("At least 10 historical records are needed to train model v1.0")
        eng = cls(stream, detector_name)
        model = train_model(train_rows)
        train_acc = float((model.predict(build_features(train_rows)) == train_rows["Target_Category"]).mean())
        calibration, metrics = validation_report(train_rows)
        tv = TrainedVersion(
            version="v1.0", parent_version=None, kind="initial", trigger="Historical data",
            model=model, step=-1, records_used=int(len(train_rows)), window_start=None, window_end=None,
            change_point_step=None, train_accuracy=train_acc, validation=metrics,
            calibration=list(calibration)[-config.CALIBRATION_SIZE:], accuracy_before=None,
            data_period=eng._period_summary(train_rows), detector=eng.detector_name,
        )
        eng.current = tv.handle
        eng.baseline = tv.handle
        eng.known_versions = {"v1.0"}
        eng._restart_detector(calibration, reset_step=0)
        return eng, tv

    @classmethod
    def restore(cls, snap: EngineSnapshot) -> "DriftEngine":
        """Rebuild state from persisted data and replay the detector (original `_try_restore`)."""
        eng = cls(snap.stream, snap.detector)
        eng.current, eng.baseline = snap.current, snap.baseline
        eng.history = sorted(snap.history, key=lambda h: h["step"])[-config.HISTORY_BUFFER:]
        eng.next_step = int(snap.next_step)
        eng.detector_reset_step = int(snap.detector_reset_step)
        eng.detector_prime = list(snap.current.calibration)[-config.CALIBRATION_SIZE:]
        eng.refresh_anchor = int(snap.refresh_anchor)
        eng.pending_refresh = [int(s) for s in snap.pending_refresh]
        eng.n_drifts = int(snap.n_drifts)
        eng.open_backfills = list(snap.open_backfills)
        eng.known_versions = set(snap.known_versions) | {snap.current.version, snap.baseline.version}
        for h in eng.history[-config.LIVE_ROLLING_WINDOW:]:
            eng._recent.append(int(bool(h["correct"])))
        eng._replay_detector()
        return eng

    # ------------------------------------------------------------------ detector helpers
    def _build_shadows(self) -> None:
        self.shadows = {n: DriftMonitor(n) for n in available_detectors() if n != self.detector_name}

    def _restart_detector(self, prime: list[int], reset_step: int) -> None:
        """Reset the detector and calibrate it with the new model's validation errors."""
        self.detector_prime = list(prime)[-config.CALIBRATION_SIZE:]
        self.detector_reset_step = reset_step
        for mon in [self.monitor, *self.shadows.values()]:
            mon.reset()
            for x in self.detector_prime:
                mon.update(bool(x))
            mon.status = STABLE
        self.warning_start = None

    def _replay_detector(self) -> None:
        """Calibration errors first, then the stored live errors since the last reset."""
        self._restart_detector(self.detector_prime, self.detector_reset_step)
        for h in self.history:
            if h["step"] < self.detector_reset_step:
                continue
            err = not bool(h["correct"])
            status = self.monitor.update(err)
            for mon in self.shadows.values():
                mon.update(err)
            self._track_warning(status, int(h["step"]))

    def _track_warning(self, status: str, step: int) -> None:
        if status == WARNING and self.warning_start is None:
            self.warning_start = step
        elif status == STABLE:
            self.warning_start = None

    def set_detector(self, name: str) -> None:
        """Switch the primary detector and rebuild its state from the error history."""
        if name not in available_detectors():
            raise EngineError(f"Detector '{name}' is not available. Options: {', '.join(available_detectors())}")
        self.detector_name = name
        self.monitor = DriftMonitor(name)
        self._build_shadows()
        self._replay_detector()

    # ------------------------------------------------------------------ properties
    @property
    def status(self) -> str:
        return self.monitor.status

    @property
    def version(self) -> str:
        return self.current.version if self.current else "—"

    def history_df(self) -> pd.DataFrame:
        if self._hist_cache is None:
            self._hist_cache = pd.DataFrame([{k: h.get(k) for k in HISTORY_COLUMNS} for h in self.history],
                                            columns=HISTORY_COLUMNS)
        return self._hist_cache

    def rolling_accuracy(self) -> float | None:
        return (sum(self._recent) / len(self._recent)) if self._recent else None

    def status_info(self) -> dict:
        return {
            "stream": self.stream,
            "detector": self.detector_name,
            "detector_backend": self.monitor.backend,
            "detector_description": self.monitor.description,
            "available_detectors": available_detectors(),
            "status": self.status,
            "status_text": STATUS_TEXT[self.status],
            "model_version": self.version,
            "baseline_version": self.baseline.version if self.baseline else None,
            "records_processed": self.next_step,
            "detector_reset_step": self.detector_reset_step,
            "values_since_reset": max(0, self.next_step - self.detector_reset_step),
            "calibration_size": len(self.detector_prime),
            "warning_start": self.warning_start,
            "pending_refresh": list(self.pending_refresh),
            "shadow_detectors": {n: m.status for n, m in self.shadows.items()},
            "rolling_accuracy": _round(self.rolling_accuracy()),
            "drift_events": self.n_drifts,
        }

    def feature_importance(self, which: str = "current") -> pd.DataFrame:
        handle = self.current if which == "current" else self.baseline
        if handle is None:
            raise EngineError("No model is loaded")
        return feature_importance(handle.model)

    def _period_summary(self, rows: pd.DataFrame) -> str:
        if rows.empty:
            return "—"
        if "Trend" in rows and rows["Trend"].notna().any():
            top = rows["Trend"].value_counts().index[0]
            period = rows["Period"].mode().iloc[0] if "Period" in rows and rows["Period"].notna().any() else 1
            return f"Period {int(period)} ({top})"
        if "Purchase_Date" in rows:
            d = pd.to_datetime(rows["Purchase_Date"], errors="coerce").dropna()
            if not d.empty:
                return f"Purchases {d.min():%Y-%m-%d} – {d.max():%Y-%m-%d}"
        return f"{len(rows)} labeled records"

    def _rows_between(self, start: int, end: int) -> pd.DataFrame:
        recs = [h["record"] for h in self.history if start <= h["step"] <= end]
        return pd.DataFrame(recs)

    @staticmethod
    def _emit(listener: Listener | None, name: str, payload: dict) -> None:
        if listener is None:
            return
        try:
            listener(name, payload)
        except Exception:  # noqa: BLE001 - notifications must never break the ML loop
            pass

    # ------------------------------------------------------------------ 1. predict
    def predict(self, record: dict, explain: bool = False) -> PredictionResult:
        """Predict the next category. Does NOT update the drift detector.

        explain=True also returns why: the contribution of each input field, computed on the
        SAME model handle that made the prediction (so it stays consistent during an adaptation).
        """
        current, baseline = self.current, self.baseline     # read once: adaptation may swap them
        if current is None or baseline is None:
            raise EngineError("The model is not ready yet")
        X = record_to_frame(record)
        predicted, confidence, probs = predict_record(current.model, X)
        base_pred, _, _ = predict_record(baseline.model, X)
        explanation = explain_prediction(current.model, X) if explain else None
        return PredictionResult(predicted, float(confidence), probs, base_pred, current.version, self.status,
                                explanation)

    # ------------------------------------------------------------------ 2. outcome → monitor → adapt
    def record_outcome(self, record: dict, actual: str, predicted: str | None = None,
                       model_version: str | None = None, baseline_prediction: str | None = None,
                       record_id: int | None = None, listener: Listener | None = None) -> OutcomeResult:
        """The real category is known: score, monitor, and adapt if drift is confirmed."""
        if self.current is None:
            raise EngineError("The model is not ready yet")
        step = self.next_step
        X = record_to_frame(record)

        # Score with the model being monitored. If the prediction came from an
        # older version (the label arrived after an adaptation), re-score this
        # record with the current model so its detector only sees its own errors.
        rescored = predicted is None or model_version != self.current.version
        scored = predict_record(self.current.model, X)[0] if rescored else predicted
        correct = scored == actual
        if baseline_prediction is None:
            baseline_prediction = predict_record(self.baseline.model, X)[0]
        stored_pred = predicted if predicted is not None else scored

        previous = self.status
        status = self.monitor.update(not correct)
        shadow_states = {n: m.update(not correct) for n, m in self.shadows.items()}
        self._track_warning(status, step)

        rec = dict(record)
        rec["Target_Category"] = actual
        self.history.append({
            "step": step, "record_id": record_id, "actual": actual, "predicted": scored,
            "correct": bool(correct), "baseline_pred": baseline_prediction,
            "baseline_correct": bool(baseline_prediction == actual),
            "model_version": self.current.version, "detector_status": status, "record": rec,
        })
        if len(self.history) > config.HISTORY_BUFFER + 500:
            del self.history[: len(self.history) - config.HISTORY_BUFFER]
        self._hist_cache = None
        self._recent.append(int(correct))
        self.next_step += 1

        result = OutcomeResult(
            step=step, actual=actual, predicted=stored_pred, is_correct=bool(stored_pred == actual),
            scored_version=self.current.version, correct=bool(correct), rescored=bool(rescored and predicted is not None),
            baseline_prediction=baseline_prediction, baseline_correct=bool(baseline_prediction == actual),
            previous_status=previous, status=status, shadow_states=shadow_states,
            rolling_accuracy=float(self.rolling_accuracy() or 0.0),
        )
        if status == DRIFT:
            result.drift_event, result.new_version, result.adaptation_error = \
                self._adapt_on_drift(step, rec, listener)
        elif self.pending_refresh and step >= self.pending_refresh[0]:
            result.new_version, result.adaptation_error = self._scheduled_refresh(step, listener)
        result.backfills = self._fill_after_metrics()
        return result

    # ------------------------------------------------------------------ adaptation
    def _adapt_on_drift(self, step: int, rec: dict, listener: Listener | None
                        ) -> tuple[dict, TrainedVersion | None, str | None]:
        hist = self.history_df()
        start, change_step = select_window(hist, self.detector_reset_step, step, self.detector_prime)
        cp = change_step if change_step is not None else start
        acc_stable = accuracy_between(hist, max(self.detector_reset_step, cp - config.PERF_EVAL_WINDOW), cp)
        acc_degraded = accuracy_between(hist, cp, step + 1)
        err_rate = None if acc_degraded is None else 1 - acc_degraded
        old_version = self.current.version
        new_version = next_version(old_version, major=True, existing=self.known_versions)
        self.n_drifts += 1

        event = {
            "event_id": f"Drift {self.n_drifts}", "stream": self.stream,
            "step": step, "purchase_date": str(rec.get("Purchase_Date", "")),
            "period": rec.get("Period"), "trend": rec.get("Trend"),
            "detector": self.detector_name, "change_point_step": int(cp), "detection_delay": int(step - cp),
            "error_rate": _round(err_rate), "accuracy_stable": _round(acc_stable),
            "accuracy_degraded": _round(acc_degraded), "accuracy_after": None,
            "status": "Detected", "action": "Model Updated",
            "from_version": old_version, "to_version": new_version,
            "window_size": None, "window_start": int(start), "timestamp": _now(),
        }
        self._emit(listener, "DRIFT_DETECTED", dict(event))
        self._emit(listener, "ADAPTATION_STARTED", {
            "stream": self.stream, "kind": "drift", "trigger": event["event_id"], "detector": self.detector_name,
            "from_version": old_version, "to_version": new_version, "step": step,
            "window_start": int(start), "window_end": step,
        })
        try:
            rows = self._rows_between(start, step)
            res = retrain_on_rows(rows, start, step, change_step)
            calibration, metrics = validation_report(res.rows)
        except Exception as exc:  # noqa: BLE001 - keep serving with the old model
            event.update(action="Adaptation failed", to_version=None, window_size=0)
            self.known_versions.discard(new_version)
            self._restart_detector(self.detector_prime, reset_step=step + 1)
            return event, None, f"Retraining failed: {exc}"

        event["window_size"] = res.records_used
        tv = TrainedVersion(
            version=new_version, parent_version=old_version, kind="drift",
            trigger=f"{event['event_id']} ({self.detector_name})", model=res.model, step=step,
            records_used=res.records_used, window_start=start, window_end=step, change_point_step=change_step,
            train_accuracy=res.train_accuracy, validation=metrics,
            calibration=list(calibration)[-config.CALIBRATION_SIZE:],
            accuracy_before=event["accuracy_degraded"], data_period=self._period_summary(rows),
            detector=self.detector_name,
        )
        self.current = tv.handle
        self.known_versions.add(new_version)
        # restart monitoring for the new model, calibrated on its own validation errors
        self._restart_detector(calibration, reset_step=step + 1)
        self.refresh_anchor = start
        self.pending_refresh = [step + s for s in config.CONSOLIDATION_STEPS]
        self.open_backfills += [{"kind": "drift_event", "key": event["event_id"], "step": step},
                                {"kind": "model_version", "key": new_version, "step": step}]
        return event, tv, None

    def _scheduled_refresh(self, step: int, listener: Listener | None) -> tuple[TrainedVersion | None, str | None]:
        self.pending_refresh.pop(0)
        hist = self.history_df()
        start = max(self.refresh_anchor, step - config.MAX_ADAPTATION_WINDOW + 1)
        acc_before = accuracy_between(hist, max(start, step - config.PERF_EVAL_WINDOW + 1), step + 1)
        old_version = self.current.version
        new_version = next_version(old_version, major=False, existing=self.known_versions)
        self._emit(listener, "ADAPTATION_STARTED", {
            "stream": self.stream, "kind": "refresh", "trigger": "More new-pattern data",
            "from_version": old_version, "to_version": new_version, "step": step,
            "window_start": int(start), "window_end": step,
        })
        try:
            rows = self._rows_between(start, step)
            res = retrain_on_rows(rows, start, step)
            calibration, metrics = validation_report(res.rows)
        except Exception as exc:  # noqa: BLE001
            return None, f"Scheduled refresh failed: {exc}"
        tv = TrainedVersion(
            version=new_version, parent_version=old_version, kind="refresh", trigger="More new-pattern data",
            model=res.model, step=step, records_used=res.records_used, window_start=start, window_end=step,
            change_point_step=None, train_accuracy=res.train_accuracy, validation=metrics,
            calibration=list(calibration)[-config.CALIBRATION_SIZE:], accuracy_before=_round(acc_before),
            data_period=self._period_summary(rows), detector=self.detector_name,
        )
        self.current = tv.handle
        self.known_versions.add(new_version)
        self._restart_detector(calibration, reset_step=step + 1)
        self.open_backfills.append({"kind": "model_version", "key": new_version, "step": step})
        return tv, None

    def adapt_now(self, trigger: str = "Manual retrain", listener: Listener | None = None) -> TrainedVersion:
        """Admin-requested retrain on recent labeled data (minor version bump)."""
        if self.current is None:
            raise EngineError("The model is not ready yet")
        if len(self.history) < config.MIN_ADAPTATION_WINDOW:
            raise EngineError(f"At least {config.MIN_ADAPTATION_WINDOW} labeled outcomes are needed to retrain; "
                              f"{len(self.history)} available")
        last = self.next_step - 1
        hist = self.history_df()
        start, change_step = select_manual_window(hist, self.detector_reset_step, last, self.detector_prime)
        acc_before = accuracy_between(hist, max(start, last - config.PERF_EVAL_WINDOW + 1), last + 1)
        old_version = self.current.version
        new_version = next_version(old_version, major=False, existing=self.known_versions)
        self._emit(listener, "ADAPTATION_STARTED", {
            "stream": self.stream, "kind": "manual", "trigger": trigger, "from_version": old_version,
            "to_version": new_version, "step": last, "window_start": int(start), "window_end": last,
        })
        rows = self._rows_between(start, last)
        if len(rows) < config.MIN_ADAPTATION_WINDOW:
            raise EngineError("Not enough recent labeled records in memory to retrain")
        res = retrain_on_rows(rows, start, last, change_step)
        calibration, metrics = validation_report(res.rows)
        tv = TrainedVersion(
            version=new_version, parent_version=old_version, kind="manual", trigger=trigger, model=res.model,
            step=last, records_used=res.records_used, window_start=start, window_end=last,
            change_point_step=change_step, train_accuracy=res.train_accuracy, validation=metrics,
            calibration=list(calibration)[-config.CALIBRATION_SIZE:], accuracy_before=_round(acc_before),
            data_period=self._period_summary(rows), detector=self.detector_name,
        )
        self.current = tv.handle
        self.known_versions.add(new_version)
        self._restart_detector(calibration, reset_step=self.next_step)
        self.open_backfills.append({"kind": "model_version", "key": new_version, "step": last})
        return tv

    def activate(self, handle: ModelHandle) -> None:
        """Make a stored version current again (rollback / activation). The detector restarts for it.

        Scheduled refreshes (+25 / +75 / +150 records after a drift) belonged to the model being replaced:
        they are cancelled, otherwise an admin's rollback would be retrained away a few records later.
        A new confirmed drift starts a new adaptation cycle as usual.
        """
        self.current = handle
        self.known_versions.add(handle.version)
        self.pending_refresh = []
        self._restart_detector(handle.calibration, reset_step=self.next_step)

    def _fill_after_metrics(self) -> list[dict]:
        """Once enough records followed an adaptation, compute its 'after' accuracy."""
        w = config.PERF_EVAL_WINDOW
        due = [b for b in self.open_backfills if self.next_step >= b["step"] + 1 + w]
        if not due:
            return []
        hist = self.history_df()
        out = []
        for b in due:
            acc = accuracy_between(hist, b["step"] + 1, b["step"] + 1 + w)
            out.append({**b, "accuracy_after": _round(acc)})
            self.open_backfills.remove(b)
        return out


# ----------------------------------------------------------------------------- helpers
def feature_record(source: dict) -> dict:
    """Keep only what the model and the history need from an incoming record."""
    keep = RAW_FEATURES + ["Customer_ID", "Purchase_Date", "Period", "Trend"]
    return {k: source[k] for k in keep if k in source}
