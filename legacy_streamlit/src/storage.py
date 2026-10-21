"""
Local file storage (CSV / JSON / joblib).

All disk access goes through `LocalStorage`, so a database backend can later be
added by writing another class with the same methods – the rest of the app
does not need to change.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from src import config
from src.model import load_model, save_model


class LocalStorage:
    def __init__(self):
        for d in (config.DATA_DIR, config.MODELS_DIR, config.ARCHIVE_DIR):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- tables ----------
    @staticmethod
    def _save_csv(df: pd.DataFrame, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        df.to_csv(tmp, index=False)
        tmp.replace(path)  # atomic-ish write so a crash never leaves half a file

    @staticmethod
    def _load_csv(path: Path) -> pd.DataFrame:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def save_predictions(self, df: pd.DataFrame) -> None:
        self._save_csv(df, config.PREDICTIONS_PATH)

    def load_predictions(self) -> pd.DataFrame:
        return self._load_csv(config.PREDICTIONS_PATH)

    def save_drift_events(self, df: pd.DataFrame) -> None:
        self._save_csv(df, config.DRIFT_EVENTS_PATH)

    def load_drift_events(self) -> pd.DataFrame:
        return self._load_csv(config.DRIFT_EVENTS_PATH)

    # ---------- metadata ----------
    def save_metadata(self, meta: dict) -> None:
        tmp = config.METADATA_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2, default=str))
        tmp.replace(config.METADATA_PATH)

    def load_metadata(self) -> dict | None:
        try:
            return json.loads(config.METADATA_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    # ---------- models ----------
    def save_current_model(self, model, version: str) -> None:
        save_model(model, config.MODEL_PATH)
        save_model(model, config.ARCHIVE_DIR / f"model_{version.replace('.', '_')}.pkl")

    def load_current_model(self):
        return load_model(config.MODEL_PATH)

    def save_baseline_model(self, model) -> None:
        save_model(model, config.BASELINE_MODEL_PATH)

    def load_baseline_model(self):
        return load_model(config.BASELINE_MODEL_PATH)

    # ---------- housekeeping ----------
    def clear_run(self) -> None:
        """Delete logs and model files of the current simulation run."""
        for p in (config.PREDICTIONS_PATH, config.DRIFT_EVENTS_PATH, config.METADATA_PATH,
                  config.MODEL_PATH, config.BASELINE_MODEL_PATH):
            p.unlink(missing_ok=True)
        shutil.rmtree(config.ARCHIVE_DIR, ignore_errors=True)
        config.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
