"""Performance metrics for the prediction stream."""
from __future__ import annotations

import pandas as pd
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from src import config


def classification_metrics(y_true, y_pred) -> dict[str, float]:
    """Accuracy + macro precision/recall/F1 (macro = every category counts equally)."""
    if len(y_true) == 0:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0, "error": 0.0, "n": 0}
    labels = sorted(set(y_true) | set(y_pred))
    p, r, f, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    acc = accuracy_score(y_true, y_pred)
    return {"accuracy": float(acc), "precision": float(p), "recall": float(r),
            "f1": float(f), "error": float(1 - acc), "n": int(len(y_true))}


def add_rolling_columns(history: pd.DataFrame, window: int = config.ROLLING_WINDOW) -> pd.DataFrame:
    """Rolling accuracy / error for the adaptive model and the static baseline."""
    if history.empty:
        return history
    h = history.copy()
    h["rolling_accuracy"] = h["correct"].astype(float).rolling(window, min_periods=1).mean()
    h["rolling_error"] = 1 - h["rolling_accuracy"]
    h["baseline_rolling_accuracy"] = (
        h["baseline_correct"].astype(float).rolling(window, min_periods=1).mean()
    )
    h["cumulative_accuracy"] = h["correct"].astype(float).expanding().mean()
    return h


def accuracy_between(history: pd.DataFrame, start: int, end: int) -> float | None:
    """Accuracy of records with stream step in [start, end)."""
    part = history[(history["step"] >= start) & (history["step"] < end)]
    if part.empty:
        return None
    return float(part["correct"].mean())


def metrics_by_version(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["model_version", "accuracy", "precision", "recall", "f1", "n"])
    rows = []
    for ver, part in history.groupby("model_version", sort=False):
        m = classification_metrics(part["actual"].tolist(), part["predicted"].tolist())
        rows.append({"model_version": ver, **m})
    return pd.DataFrame(rows)
