"""
Model adaptation: pick the recent data that reflects the NEW pattern and retrain.

Window selection (easy to explain in a viva):
  1. Look at the error sequence since the last adaptation.
  2. Find the split point where "error rate after" minus "error rate before" is the most
     significant (gap weighted by how many records support it)
     -> that is our best estimate of when the fashion trend changed.
  3. Retrain on the records after that point (at least MIN_ADAPTATION_WINDOW,
     at most MAX_ADAPTATION_WINDOW records).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from ml import config
from sklearn.model_selection import KFold, cross_val_predict

from ml.evaluation import classification_metrics
from ml.feature_engineering import build_features
from ml.model import build_pipeline, train_model


@dataclass
class AdaptationResult:
    model: Pipeline
    window_start_step: int
    window_end_step: int
    records_used: int
    change_point_step: int | None
    train_accuracy: float
    rows: pd.DataFrame


def estimate_change_point(errors: np.ndarray,
                          min_before: int = config.MIN_SEGMENT_BEFORE,
                          min_after: int = config.MIN_SEGMENT_AFTER) -> int | None:
    """Return index (into `errors`) where the error rate jumps the most, or None."""
    n = len(errors)
    if n < min_before + min_after:
        return None
    csum = np.concatenate([[0.0], np.cumsum(errors)])
    best_idx, best_score, best_gap = None, 0.0, 0.0
    for k in range(min_before, n - min_after + 1):
        before = csum[k] / k
        after = (csum[n] - csum[k]) / (n - k)
        gap = after - before
        # weight the gap by the amount of evidence on both sides (more records = more certain)
        score = gap * np.sqrt(k * (n - k) / n)
        if score > best_score:
            best_idx, best_score, best_gap = k, score, gap
    return best_idx if best_gap >= 0.15 else None


def select_window(history: pd.DataFrame, since_step: int, current_step: int,
                  calibration: list[int] | None = None) -> tuple[int, int | None]:
    """Choose the first stream step of the retraining window.

    `calibration` (the detector's validation errors) is placed in front of the live
    errors so a change right at the start of monitoring can still be located.
    """
    segment = history[(history["step"] >= since_step) & (history["step"] <= current_step)]
    change_step = None
    if not segment.empty:
        prefix = list(calibration or [])[-100:]
        live = (~segment["correct"].astype(bool)).astype(float).tolist()
        idx = estimate_change_point(np.array(prefix + live, dtype=float))
        if idx is not None:
            idx = max(0, idx - len(prefix))
            change_step = int(segment["step"].iloc[idx])

    start = change_step if change_step is not None else current_step - config.MIN_ADAPTATION_WINDOW + 1
    # enforce min / max window size
    start = min(start, current_step - config.MIN_ADAPTATION_WINDOW + 1)
    start = max(start, current_step - config.MAX_ADAPTATION_WINDOW + 1, 0)
    return start, change_step


def retrain_on_rows(rows: pd.DataFrame, start_step: int, end_step: int,
                    change_step: int | None = None) -> AdaptationResult:
    """Retrain a fresh model on already-selected labeled rows.

    This is the original retraining step with the data source taken out: the
    caller passes the rows (from the CSV in the legacy app, from PostgreSQL in
    the backend). Model, features and the train-accuracy figure are unchanged.
    """
    model = train_model(rows)
    train_acc = float((model.predict(build_features(rows)) == rows["Target_Category"]).mean())
    return AdaptationResult(model, start_step, end_step, len(rows), change_step, train_acc, rows)


def retrain_on_window(dataset: pd.DataFrame, history: pd.DataFrame,
                      start_step: int, end_step: int,
                      change_step: int | None = None) -> AdaptationResult:
    """Retrain a fresh model on the dataset rows seen between two stream steps."""
    window_hist = history[(history["step"] >= start_step) & (history["step"] <= end_step)]
    rows = dataset.loc[window_hist["record_id"].astype(int)]
    return retrain_on_rows(rows, start_step, end_step, change_step)


def bump_version(version: str, major: bool) -> str:
    """'v1.0' -> 'v2.0' (drift adaptation) or 'v1.1' (refresh)."""
    try:
        ma, mi = version.lstrip("v").split(".")
        ma, mi = int(ma), int(mi)
    except ValueError:
        ma, mi = 1, 0
    return f"v{ma + 1}.0" if major else f"v{ma}.{mi + 1}"


def validation_report(rows: pd.DataFrame, max_splits: int = 4) -> tuple[list[int], dict | None]:
    """Out-of-fold errors AND out-of-fold metrics of a model trained on `rows`.

    Same cross-validation as before (it was already computed for detector
    calibration); the predictions are now also summarised as accuracy /
    precision / recall / F1, so the model registry can store validation metrics
    instead of the optimistic training-set accuracy.
    """
    if len(rows) < 10:
        return [], None
    splits = min(max_splits, len(rows) // 5)
    cv = KFold(n_splits=splits, shuffle=True, random_state=config.RANDOM_STATE)
    y = rows["Target_Category"].astype(str)
    pred = cross_val_predict(build_pipeline(), build_features(rows), y, cv=cv)
    errors = [int(v) for v in (pred != y.to_numpy())]
    return errors, classification_metrics(y.tolist(), [str(p) for p in pred])


def validation_errors(rows: pd.DataFrame, max_splits: int = 4) -> list[int]:
    """Out-of-fold errors (1 = wrong) of a model trained on `rows`.

    Used to calibrate the drift detector: it learns the model's *normal* error
    level from data the model did not train on, before any live record arrives.
    """
    return validation_report(rows, max_splits)[0]


# ---------------------------------------------------------------------------
# Additions for the backend (new)
# ---------------------------------------------------------------------------
def _parse_version(version: str) -> tuple[int, int]:
    try:
        ma, mi = version.lstrip("v").split(".")
        return int(ma), int(mi)
    except ValueError:
        return 1, 0


def next_version(current: str, major: bool, existing: set[str] | None = None) -> str:
    """bump_version() that never reuses a version name.

    Identical to bump_version() in the normal flow. It only differs after an
    admin re-activates an older model (rollback): drift then jumps to the next
    unused major version and refreshes to the next unused minor version, so an
    existing model is never overwritten.
    """
    existing = existing or set()
    if major:
        top = max([_parse_version(v)[0] for v in existing] + [_parse_version(current)[0]])
        candidate = bump_version(current, major=True)
        return candidate if candidate not in existing else f"v{top + 1}.0"
    candidate = bump_version(current, major=False)
    while candidate in existing:
        candidate = bump_version(candidate, major=False)
    return candidate


def select_manual_window(history: pd.DataFrame, since_step: int, current_step: int,
                         calibration: list[int] | None = None) -> tuple[int, int | None]:
    """Window for an admin-requested retrain.

    Uses the same change-point estimate as drift adaptation. If the error stream
    shows no change, it retrains on the most recent MAX_ADAPTATION_WINDOW
    records instead of the drift minimum (15), because nothing indicates that
    older data is stale.
    """
    start, change_step = select_window(history, since_step, current_step, calibration)
    if change_step is None:
        first = int(history["step"].min()) if not history.empty else 0
        start = max(first, current_step - config.MAX_ADAPTATION_WINDOW + 1, 0)
    return start, change_step
