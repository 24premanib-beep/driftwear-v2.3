"""
Simulation feed: replays the time-ordered synthetic dataset as a stream.

This is the original prototype's data stream (dataset pointer, "simulate
fashion trend change") separated from the engine. In the backend it only
drives the `simulation` stream; real records never pass through it.

Datasets are reproducible from their seed (seed 42 = data/fashion_purchases.csv),
so a run can be restored after a restart without writing extra files.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ml import config
from ml.data_generator import generate_dataset
from ml.preprocessing import DatasetError, clean_dataset, load_dataset
from ml.stream_engine import feature_record


def load_simulation_dataset(seed: int = config.DEFAULT_SEED) -> pd.DataFrame:
    """Default seed reads the shipped CSV; any other seed regenerates in memory."""
    if seed == config.DEFAULT_SEED and config.DATASET_PATH.exists():
        try:
            return load_dataset(config.DATASET_PATH)
        except DatasetError:
            pass
    return clean_dataset(generate_dataset(seed=seed))


def initial_train_size(dataset: pd.DataFrame) -> int:
    return min(config.INITIAL_TRAIN_SIZE, len(dataset) // 3)


def _plain(v):
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, np.generic):
        return v.item()
    return v


class SimulationFeed:
    def __init__(self, dataset: pd.DataFrame, seed: int = config.DEFAULT_SEED,
                 pointer: int | None = None, trend_changes: list[dict] | None = None):
        if len(dataset) < 60:
            raise DatasetError("Dataset needs at least 60 records for a meaningful stream")
        self.dataset = dataset
        self.seed = int(seed)
        self.train_size = initial_train_size(dataset)
        self.pointer = self.train_size if pointer is None else int(pointer)
        self.trend_changes = list(trend_changes or [])

    @classmethod
    def from_seed(cls, seed: int = config.DEFAULT_SEED, **kw) -> "SimulationFeed":
        return cls(load_simulation_dataset(seed), seed=seed, **kw)

    # ------------------------------------------------------------------ state
    @property
    def total(self) -> int:
        return len(self.dataset)

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

    def training_rows(self) -> pd.DataFrame:
        return self.dataset.iloc[: self.train_size]

    def info(self) -> dict:
        return {
            "seed": self.seed, "dataset_rows": self.total, "train_size": self.train_size,
            "pointer": self.pointer, "processed": self.pointer - self.train_size,
            "stream_size": self.total - self.train_size, "remaining": self.remaining,
            "finished": self.finished, "current_period": self.current_period,
            "current_trend": self.current_trend, "trend_changes": self.trend_changes,
        }

    # ------------------------------------------------------------------ stream
    def next_record(self) -> tuple[dict, str] | None:
        """Return (feature record, actual category) for the next purchase, or None at the end."""
        if self.finished:
            return None
        row = self.dataset.iloc[self.pointer]
        self.pointer += 1
        full = {k: _plain(v) for k, v in row.to_dict().items()}
        record = feature_record(full)
        record["Record_ID"] = int(full["Record_ID"])
        return record, str(full["Target_Category"])

    def trend_change(self) -> dict:
        """Jump to the next trend period (controlled distribution change, demo only)."""
        if self.finished:
            return {"ok": False, "message": "The stream has ended. Reset the simulation to start again."}
        cur = self.current_period
        later = self.dataset.index[(self.dataset.index >= self.pointer) & (self.dataset["Period"] > cur)]
        if len(later) == 0:
            return {"ok": False, "message": "Already in the last trend period. Reset or generate a new dataset."}
        target = int(later[0])
        info = {
            "ok": True, "from_period": cur, "from_trend": self.current_trend,
            "to_period": int(self.dataset["Period"].iloc[target]),
            "to_trend": str(self.dataset["Trend"].iloc[target]),
            "skipped_records": target - self.pointer,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.pointer = target
        self.trend_changes.append(info)
        info["message"] = f"Trend changed: {info['from_trend']} → {info['to_trend']}"
        return info
