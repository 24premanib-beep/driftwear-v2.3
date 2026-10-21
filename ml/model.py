"""Random Forest pipeline: train, predict, explain, save, load."""
from __future__ import annotations

import io
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline

from ml import config
from ml.feature_engineering import (
    FEATURE_LABELS, build_features, build_preprocessor, original_feature_of, record_to_frame,
)


def build_pipeline() -> Pipeline:
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        random_state=config.RANDOM_STATE,
        n_jobs=1,  # single-record predictions are faster without thread overhead
    )
    return Pipeline([("prep", build_preprocessor()), ("clf", clf)])


def train_model(df: pd.DataFrame) -> Pipeline:
    if len(df) < 5:
        raise ValueError("At least 5 records are needed to train a model")
    model = build_pipeline()
    model.fit(build_features(df), df["Target_Category"].astype(str))
    return model


def predict_record(model: Pipeline, record: dict | pd.DataFrame) -> tuple[str, float, dict[str, float]]:
    """Return (predicted category, confidence, probability per category).

    Confidence is the Random Forest's real class probability (averaged tree votes).
    `record` may be a dict or an already-built one-row feature frame.
    """
    X = record if isinstance(record, pd.DataFrame) else record_to_frame(record)
    proba = model.predict_proba(X)[0]
    classes = list(model.classes_)
    probs = {c: 0.0 for c in config.CATEGORIES}
    probs.update({c: float(p) for c, p in zip(classes, proba)})
    best = classes[int(np.argmax(proba))]
    return best, float(np.max(proba)), probs


def predict_batch(model: Pipeline, df: pd.DataFrame) -> np.ndarray:
    return model.predict(build_features(df))


def feature_importance(model: Pipeline) -> pd.DataFrame:
    """Aggregate one-hot importances back to the original input fields."""
    names = model.named_steps["prep"].get_feature_names_out()
    imps = model.named_steps["clf"].feature_importances_
    agg: dict[str, float] = {}
    for n, v in zip(names, imps):
        raw = original_feature_of(n)
        agg[raw] = agg.get(raw, 0.0) + float(v)
    out = pd.DataFrame({"feature": list(agg), "importance": list(agg.values())})
    out["label"] = out["feature"].map(FEATURE_LABELS).fillna(out["feature"])
    return out.sort_values("importance", ascending=False).reset_index(drop=True)


def save_model(model: Pipeline, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def load_model(path: Path) -> Pipeline | None:
    if not path.exists():
        return None
    try:
        return joblib.load(path)
    except Exception:  # noqa: BLE001 - a corrupt/incompatible file means "retrain"
        return None


# --- byte-level persistence used by the backend's ModelStorageService --------
# joblib/pickle files execute code when loaded: only ever load bytes that came
# from the application's own private model storage (checksums are verified by
# the storage service before this is called).
def serialize_model(model: Pipeline) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf, compress=3)
    return buf.getvalue()


def deserialize_model(data: bytes) -> Pipeline:
    return joblib.load(io.BytesIO(data))
