"""
StreamEngine – the Learn → Predict → Monitor → Detect Drift → Adapt loop.

For every incoming purchase record:
    1. the current model predicts the category
    2. the actual category is revealed
    3. correct / wrong is computed
    4. the error (0/1) is fed to the River drift detector
    5. WARNING -> remember where the possible change started
       DRIFT   -> select recent window, retrain, save, bump version (v1.0 -> v2.0)
    6. after a drift the model refreshes itself as more new-pattern data arrives
       (v2.0 -> v2.1 -> v2.2)

A frozen copy of model v1.0 ("static model") also predicts every record, so the
benefit of adaptation can be shown side by side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from src import config
from src.adaptation import bump_version, retrain_on_window, select_window, validation_errors
from src.data_generator import generate_dataset, save_dataset
from src.drift_detector import DRIFT, STABLE, WARNING, DriftMonitor
from src.feature_engineering import build_features, record_to_frame
from src.evaluation import accuracy_between, classification_metrics
from src.model import predict_record, train_model
from src.preprocessing import DatasetError, load_dataset
from src.storage import LocalStorage


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class StepResult:
    record: dict
    predicted: str
    actual: str
    confidence: float
    correct: bool
    status: str
    drift_event: dict | None = None
    adaptation: dict | None = None


@dataclass
class BatchResult:
    steps: list[StepResult] = field(default_factory=list)
    stopped_on_drift: bool = False
    finished: bool = False

    @property
    def drift_events(self) -> list[dict]:
        return [s.drift_event for s in self.steps if s.drift_event]

    @property
    def adaptations(self) -> list[dict]:
        return [s.adaptation for s in self.steps if s.adaptation]


class StreamEngine:
    def __init__(self, detector_name: str = config.DEFAULT_DETECTOR, storage: LocalStorage | None = None):
        self.storage = storage or LocalStorage()
        self.detector_name = detector_name
        self.dataset: pd.DataFrame = pd.DataFrame()
        self.dataset_seed = config.DEFAULT_SEED
        self.monitor = DriftMonitor(detector_name)
        self._clear_state()

    # ------------------------------------------------------------------ setup
    def _clear_state(self) -> None:
        self.model = None
        self.baseline_model = None
        self.version = "v1.0"
        self.pointer = config.INITIAL_TRAIN_SIZE
        self.train_size = config.INITIAL_TRAIN_SIZE
        self.history: list[dict] = []
        self.drift_events: list[dict] = []
        self.adaptations: list[dict] = []
        self.trend_changes: list[dict] = []
        self.warning_start: int | None = None
        self.detector_reset_step = 0
        self.detector_prime: list[int] = []
        self.pending_refresh: list[int] = []
        self.refresh_anchor = 0
        self.initial_train_accuracy = None
        self.created_at = _now()
        self._hist_cache: pd.DataFrame | None = None
        self.monitor = DriftMonitor(self.detector_name)

    @classmethod
    def load_or_create(cls, detector_name: str = config.DEFAULT_DETECTOR) -> "StreamEngine":
        engine = cls(detector_name)
        if not engine._try_restore():
            engine.new_simulation(regenerate=not config.DATASET_PATH.exists())
        return engine

    def _ensure_dataset(self, regenerate: bool, seed: int | None = None) -> None:
        if regenerate:
            self.dataset_seed = int(seed if seed is not None else config.DEFAULT_SEED)
            save_dataset(generate_dataset(seed=self.dataset_seed))
        try:
            self.dataset = load_dataset()
        except DatasetError:
            self.dataset_seed = config.DEFAULT_SEED
            save_dataset(generate_dataset(seed=self.dataset_seed))
            self.dataset = load_dataset()
        if len(self.dataset) < 60:
            raise DatasetError("Dataset needs at least 60 records for a meaningful stream")

    def new_simulation(self, regenerate: bool = False, seed: int | None = None) -> None:
        """Reset everything and train model v1.0 on the historical part of the data."""
        self._ensure_dataset(regenerate, seed)
        self.storage.clear_run()
        self._clear_state()
        self.train_size = min(config.INITIAL_TRAIN_SIZE, len(self.dataset) // 3)
        self.pointer = self.train_size
        train = self.dataset.iloc[: self.train_size]
        self.model = train_model(train)
        self.baseline_model = self.model
        self.initial_train_accuracy = float(
            (self.model.predict(build_features(train)) == train["Target_Category"]).mean())
        self.adaptations.append({
            "adaptation_id": 0, "type": "Initial training", "trigger": "Historical data", "step": -1,
            "from_version": "—", "to_version": "v1.0", "records_used": int(self.train_size),
            "window_start": None, "window_end": None,
            "train_accuracy": round(self.initial_train_accuracy, 4),
            "accuracy_before": None, "accuracy_after": None,
            "data_period": self._period_summary(train), "timestamp": _now(),
            "purchase_date": str(train["Purchase_Date"].iloc[-1]),
        })
        self._restart_detector(validation_errors(train), reset_step=0)
        self.storage.save_current_model(self.model, self.version)
        self.storage.save_baseline_model(self.baseline_model)
        self.save()

    def reset(self) -> None:
        self.new_simulation(regenerate=False)

    def generate_new_dataset(self) -> None:
        self.new_simulation(regenerate=True, seed=int(np.random.randint(1, 1_000_000)))

    def set_detector(self, name: str) -> None:
        """Switch detector and rebuild its state from the error history."""
        self.detector_name = name
        self.monitor = DriftMonitor(name)
        self._replay_detector()
        self.save()

    # ------------------------------------------------------------ persistence
    def save(self) -> None:
        self.storage.save_predictions(self.history_df)
        self.storage.save_drift_events(pd.DataFrame(self.drift_events))
        self.storage.save_metadata(self.metadata)

    @property
    def metadata(self) -> dict:
        return {
            "model_version": self.version,
            "detector": self.detector_name,
            "pointer": self.pointer,
            "n_processed": len(self.history),
            "train_size": self.train_size,
            "dataset_seed": self.dataset_seed,
            "dataset_rows": len(self.dataset),
            "initial_train_accuracy": self.initial_train_accuracy,
            "detector_reset_step": self.detector_reset_step,
            "detector_prime": self.detector_prime,
            "pending_refresh": self.pending_refresh,
            "refresh_anchor": self.refresh_anchor,
            "adaptations": self.adaptations,
            "trend_changes": self.trend_changes,
            "created_at": self.created_at,
            "updated_at": _now(),
        }

    def _try_restore(self) -> bool:
        meta = self.storage.load_metadata()
        if not meta:
            return False
        try:
            self.dataset = load_dataset()
            model = self.storage.load_current_model()
            baseline = self.storage.load_baseline_model()
            hist = self.storage.load_predictions()
            if model is None or baseline is None:
                return False
            if len(hist) != meta["n_processed"] or meta["pointer"] > len(self.dataset):
                return False
            if meta.get("dataset_rows") != len(self.dataset):
                return False
            self._clear_state()
            self.detector_name = meta.get("detector", self.detector_name)
            self.monitor = DriftMonitor(self.detector_name)
            self.model, self.baseline_model = model, baseline
            self.version = meta["model_version"]
            self.pointer = int(meta["pointer"])
            self.train_size = int(meta["train_size"])
            self.dataset_seed = meta.get("dataset_seed", config.DEFAULT_SEED)
            self.initial_train_accuracy = meta.get("initial_train_accuracy")
            self.detector_reset_step = int(meta.get("detector_reset_step", 0))
            self.detector_prime = [int(v) for v in meta.get("detector_prime", [])]
            self.pending_refresh = list(meta.get("pending_refresh", []))
            self.refresh_anchor = int(meta.get("refresh_anchor", 0))
            self.adaptations = meta.get("adaptations", [])
            self.trend_changes = meta.get("trend_changes", [])
            self.created_at = meta.get("created_at", _now())
            if not hist.empty:
                hist["correct"] = hist["correct"].astype(bool)
                hist["baseline_correct"] = hist["baseline_correct"].astype(bool)
            self.history = hist.to_dict("records")
            ev = self.storage.load_drift_events()
            self.drift_events = [] if ev.empty else ev.replace({np.nan: None}).to_dict("records")
            self._replay_detector()
            return True
        except Exception:  # noqa: BLE001 - anything odd -> start fresh
            return False

    def _restart_detector(self, prime: list[int], reset_step: int) -> None:
        """Reset the detector and calibrate it with the new model's validation errors."""
        self.detector_prime = list(prime)[-config.CALIBRATION_SIZE:]
        self.detector_reset_step = reset_step
        self.monitor.reset()
        for x in self.detector_prime:
            self.monitor.update(bool(x))
        self.monitor.status = STABLE
        self.warning_start = None

    def _replay_detector(self) -> None:
        """Rebuild detector state: calibration errors, then stored live errors."""
        self._restart_detector(self.detector_prime, self.detector_reset_step)
        for h in self.history[self.detector_reset_step:]:
            status = self.monitor.update(not bool(h["correct"]))
            self._track_warning(status, int(h["step"]))

    # ------------------------------------------------------------ helpers
    @property
    def history_df(self) -> pd.DataFrame:
        if self._hist_cache is None:
            self._hist_cache = pd.DataFrame(self.history, columns=[
                "step", "record_id", "purchase_date", "customer_id", "period", "trend",
                "actual", "predicted", "confidence", "correct", "baseline_pred",
                "baseline_correct", "model_version", "detector_status",
            ])
        return self._hist_cache

    def _period_summary(self, rows: pd.DataFrame) -> str:
        if rows.empty:
            return "—"
        top = rows["Trend"].value_counts().index[0]
        return f"Period {int(rows['Period'].mode().iloc[0])} ({top})"

    def _track_warning(self, status: str, step: int) -> None:
        if status == WARNING and self.warning_start is None:
            self.warning_start = step
        elif status == STABLE:
            self.warning_start = None

    @property
    def status(self) -> str:
        return self.monitor.status

    @property
    def finished(self) -> bool:
        return self.pointer >= len(self.dataset)

    @property
    def remaining(self) -> int:
        return max(0, len(self.dataset) - self.pointer)

    @property
    def current_period(self) -> int:
        idx = min(self.pointer, len(self.dataset) - 1)
        return int(self.dataset["Period"].iloc[idx])

    @property
    def current_trend(self) -> str:
        idx = min(self.pointer, len(self.dataset) - 1)
        return str(self.dataset["Trend"].iloc[idx])

    @property
    def n_drifts(self) -> int:
        return len(self.drift_events)

    @property
    def last_prediction(self) -> dict | None:
        return self.history[-1] if self.history else None

    def upcoming(self, n: int = 8) -> pd.DataFrame:
        return self.dataset.iloc[self.pointer: self.pointer + n]

    # ------------------------------------------------------------ the loop
    def process_next(self) -> StepResult | None:
        if self.finished:
            return None
        row = self.dataset.iloc[self.pointer]
        record = row.to_dict()
        step = len(self.history)

        X = record_to_frame(record)
        predicted, confidence, _ = predict_record(self.model, X)               # 1. predict
        actual = str(row["Target_Category"])                                     # 2. actual
        correct = predicted == actual                                            # 3. compare
        base_pred, _, _ = predict_record(self.baseline_model, X)
        status = self.monitor.update(not correct)                                # 4. monitor
        self._track_warning(status, step)                                        # 5. warning zone

        self.history.append({
            "step": step, "record_id": int(row["Record_ID"]),
            "purchase_date": str(row["Purchase_Date"]), "customer_id": row["Customer_ID"],
            "period": int(row["Period"]), "trend": row["Trend"],
            "actual": actual, "predicted": predicted, "confidence": round(confidence, 4),
            "correct": bool(correct), "baseline_pred": base_pred,
            "baseline_correct": bool(base_pred == actual),
            "model_version": self.version, "detector_status": status,
        })
        self._hist_cache = None
        self.pointer += 1

        result = StepResult(record, predicted, actual, confidence, correct, status)
        if status == DRIFT:                                                      # 6. drift -> adapt
            result.drift_event, result.adaptation = self._adapt_on_drift(step, row)
        elif self.pending_refresh and step >= self.pending_refresh[0]:
            result.adaptation = self._scheduled_refresh(step, row)
        self._fill_after_metrics()
        return result

    def process_batch(self, n: int, stop_on_drift: bool = False) -> BatchResult:
        batch = BatchResult()
        for _ in range(max(0, int(n))):
            res = self.process_next()
            if res is None:
                batch.finished = True
                break
            batch.steps.append(res)
            if res.drift_event and stop_on_drift:
                batch.stopped_on_drift = True
                break
        batch.finished = batch.finished or self.finished
        self.save()
        return batch

    # ------------------------------------------------------------ adaptation
    def _adapt_on_drift(self, step: int, row: pd.Series) -> tuple[dict, dict]:
        hist = self.history_df
        start, change_step = select_window(hist, self.detector_reset_step, step, self.detector_prime)
        res = retrain_on_window(self.dataset, hist, start, step, change_step)

        old_version, new_version = self.version, bump_version(self.version, major=True)
        cp = change_step if change_step is not None else start
        acc_stable = accuracy_between(hist, max(self.detector_reset_step, cp - config.PERF_EVAL_WINDOW), cp)
        acc_degraded = accuracy_between(hist, cp, step + 1)
        err_rate = None if acc_degraded is None else 1 - acc_degraded

        self.model = res.model
        self.version = new_version
        self.storage.save_current_model(self.model, self.version)

        event = {
            "event_id": f"Drift {len(self.drift_events) + 1}",
            "step": step, "record_id": int(row["Record_ID"]),
            "purchase_date": str(row["Purchase_Date"]), "period": int(row["Period"]),
            "trend": row["Trend"], "detector": self.detector_name,
            "change_point_step": cp, "detection_delay": step - cp,
            "error_rate": round(err_rate, 4) if err_rate is not None else None,
            "accuracy_stable": round(acc_stable, 4) if acc_stable is not None else None,
            "accuracy_degraded": round(acc_degraded, 4) if acc_degraded is not None else None,
            "accuracy_after": None,
            "status": "Detected", "action": "Model Updated",
            "from_version": old_version, "to_version": new_version,
            "window_size": res.records_used, "timestamp": _now(),
        }
        adaptation = {
            "adaptation_id": len(self.adaptations), "type": "Drift adaptation",
            "trigger": event["event_id"], "step": step,
            "from_version": old_version, "to_version": new_version,
            "records_used": res.records_used, "window_start": start, "window_end": step,
            "train_accuracy": round(res.train_accuracy, 4),
            "accuracy_before": event["accuracy_degraded"], "accuracy_after": None,
            "data_period": self._period_summary(self.dataset.loc[
                hist[(hist.step >= start) & (hist.step <= step)]["record_id"]]),
            "timestamp": _now(), "purchase_date": str(row["Purchase_Date"]),
        }
        self.drift_events.append(event)
        self.adaptations.append(adaptation)

        # restart monitoring for the new model, calibrated on its own validation errors
        self._restart_detector(validation_errors(res.rows), reset_step=step + 1)
        self.refresh_anchor = start
        self.pending_refresh = [step + s for s in config.CONSOLIDATION_STEPS]
        return event, adaptation

    def _scheduled_refresh(self, step: int, row: pd.Series) -> dict:
        self.pending_refresh.pop(0)
        hist = self.history_df
        start = max(self.refresh_anchor, step - config.MAX_ADAPTATION_WINDOW + 1)
        acc_before = accuracy_between(hist, max(start, step - config.PERF_EVAL_WINDOW + 1), step + 1)
        res = retrain_on_window(self.dataset, hist, start, step)
        old_version, new_version = self.version, bump_version(self.version, major=False)
        self.model, self.version = res.model, new_version
        self.storage.save_current_model(self.model, self.version)
        self._restart_detector(validation_errors(res.rows), reset_step=step + 1)
        adaptation = {
            "adaptation_id": len(self.adaptations), "type": "Scheduled refresh",
            "trigger": "More new-pattern data", "step": step,
            "from_version": old_version, "to_version": new_version,
            "records_used": res.records_used, "window_start": start, "window_end": step,
            "train_accuracy": round(res.train_accuracy, 4),
            "accuracy_before": round(acc_before, 4) if acc_before is not None else None,
            "accuracy_after": None,
            "data_period": self._period_summary(self.dataset.loc[
                hist[(hist.step >= start) & (hist.step <= step)]["record_id"]]),
            "timestamp": _now(), "purchase_date": str(row["Purchase_Date"]),
        }
        self.adaptations.append(adaptation)
        return adaptation

    def _fill_after_metrics(self) -> None:
        """Once enough records followed an adaptation, record its 'after' accuracy."""
        n = len(self.history)
        w = config.PERF_EVAL_WINDOW
        hist = None
        for items in (self.drift_events, self.adaptations):
            for a in items:
                if a.get("accuracy_after") is None and a.get("step", -1) >= 0 and n >= a["step"] + 1 + w:
                    hist = self.history_df if hist is None else hist
                    acc = accuracy_between(hist, a["step"] + 1, a["step"] + 1 + w)
                    a["accuracy_after"] = round(acc, 4) if acc is not None else None

    # ------------------------------------------------------------ demo mode
    def simulate_trend_change(self) -> dict:
        """Jump the stream to the next fashion-trend period (controlled distribution change)."""
        if self.finished:
            return {"ok": False, "message": "The stream has ended. Reset the simulation to start again."}
        cur = self.current_period
        later = self.dataset.index[(self.dataset.index >= self.pointer) & (self.dataset["Period"] > cur)]
        if len(later) == 0:
            return {"ok": False, "message": "Already in the last trend period. Reset or generate a new dataset."}
        target = int(later[0])
        info = {
            "ok": True, "step": len(self.history),
            "from_period": cur, "from_trend": self.current_trend,
            "to_period": int(self.dataset["Period"].iloc[target]),
            "to_trend": str(self.dataset["Trend"].iloc[target]),
            "skipped_records": target - self.pointer, "timestamp": _now(),
        }
        self.pointer = target
        self.trend_changes.append(info)
        self.save()
        info["message"] = f"Trend changed: {info['from_trend']} → {info['to_trend']}"
        return info

    # ------------------------------------------------------------ metrics
    def overall_metrics(self) -> dict:
        h = self.history_df
        return classification_metrics(h["actual"].tolist(), h["predicted"].tolist())

    def baseline_metrics(self) -> dict:
        h = self.history_df
        return classification_metrics(h["actual"].tolist(), h["baseline_pred"].tolist())

    def recent_metrics(self, window: int = config.ROLLING_WINDOW) -> dict:
        h = self.history_df.tail(window)
        return classification_metrics(h["actual"].tolist(), h["predicted"].tolist())

    def feature_row(self, record_id: int) -> dict:
        return self.dataset.loc[int(record_id)].to_dict()
