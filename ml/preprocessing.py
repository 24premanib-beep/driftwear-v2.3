"""Loading, validating and cleaning the purchase dataset."""
from __future__ import annotations

import pandas as pd

from ml import config

REQUIRED_COLUMNS = [
    "Customer_ID", "Purchase_Date", "Previous_Category", "Purchase_Frequency",
    "Recency", "Season", "Month", "Price", "Discount",
    "Customer_Preference", "Target_Category",
]


class DatasetError(ValueError):
    """Raised when the CSV cannot be used."""


def validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DatasetError(f"Dataset is missing required columns: {', '.join(missing)}")


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Handle missing values, duplicates, types and time ordering."""
    validate_columns(df)
    df = df.copy()

    # --- dates & ordering --------------------------------------------------
    df["Purchase_Date"] = pd.to_datetime(df["Purchase_Date"], errors="coerce")
    df = df.dropna(subset=["Purchase_Date", "Target_Category"])
    df = df.drop_duplicates(subset=[c for c in REQUIRED_COLUMNS])
    df = df.sort_values("Purchase_Date", kind="stable").reset_index(drop=True)

    # --- numeric columns: coerce + median fill -----------------------------
    for col in ["Purchase_Frequency", "Recency", "Month", "Price", "Discount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[col].median())
    df["Month"] = df["Month"].clip(1, 12).astype(int)
    df["Discount"] = df["Discount"].clip(0, 90)
    df["Price"] = df["Price"].clip(lower=0)

    # --- categorical columns: mode fill ------------------------------------
    df["Season"] = df["Season"].fillna(df["Month"].map(config.MONTH_TO_SEASON))
    for col in ["Previous_Category", "Customer_Preference", "Customer_ID"]:
        mode = df[col].mode()
        df[col] = df[col].fillna(mode.iloc[0] if not mode.empty else "Unknown").astype(str)

    df["Target_Category"] = df["Target_Category"].astype(str)

    # Optional columns produced by the generator
    if "Period" not in df.columns:
        df["Period"] = 1
    if "Trend" not in df.columns:
        df["Trend"] = "Uploaded data"
    df["Record_ID"] = range(len(df))
    return df


def load_dataset(path=config.DATASET_PATH) -> pd.DataFrame:
    if not path.exists():
        raise DatasetError(f"Dataset not found at {path}")
    try:
        raw = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise DatasetError(f"Could not read {path.name}: {exc}") from exc
    if raw.empty:
        raise DatasetError("Dataset is empty")
    return clean_dataset(raw)
