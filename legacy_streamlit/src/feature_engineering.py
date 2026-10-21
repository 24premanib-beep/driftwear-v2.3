"""Feature preparation shared by training and prediction."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder

from src import config

CATEGORICAL_FEATURES = ["Previous_Category", "Season", "Customer_Preference"]
NUMERIC_FEATURES = [
    "Purchase_Frequency", "Recency", "Month", "Price", "Discount",
    "Final_Price", "Month_Sin", "Month_Cos",
]
RAW_FEATURES = [
    "Previous_Category", "Purchase_Frequency", "Recency", "Season",
    "Month", "Price", "Discount", "Customer_Preference",
]

# Friendly names used when explaining the model
FEATURE_LABELS = {
    "Previous_Category": "Previous category",
    "Purchase_Frequency": "Purchase frequency",
    "Recency": "Recency (days)",
    "Season": "Season",
    "Month": "Month",
    "Price": "Price",
    "Discount": "Discount",
    "Customer_Preference": "Customer preference",
}


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return the model input table (raw + engineered columns)."""
    X = df[RAW_FEATURES].copy()
    X["Final_Price"] = X["Price"] * (1 - X["Discount"] / 100.0)
    # cyclical month encoding: December is close to January
    X["Month_Sin"] = np.sin(2 * np.pi * X["Month"] / 12)
    X["Month_Cos"] = np.cos(2 * np.pi * X["Month"] / 12)
    return X


def record_to_frame(record: dict) -> pd.DataFrame:
    return build_features(pd.DataFrame([record]))


def build_preprocessor() -> ColumnTransformer:
    encoder = OneHotEncoder(
        categories=[config.CATEGORIES, config.SEASONS, config.PREFERENCES],
        handle_unknown="ignore",
    )
    return ColumnTransformer(
        [("cat", encoder, CATEGORICAL_FEATURES), ("num", "passthrough", NUMERIC_FEATURES)]
    )


def original_feature_of(encoded_name: str) -> str:
    """Map an encoded column name (e.g. 'cat__Season_Winter') back to its raw feature."""
    name = encoded_name.split("__", 1)[-1]
    for raw in RAW_FEATURES:
        if name == raw or name.startswith(raw + "_"):
            return raw
    if name in ("Final_Price",):
        return "Price"
    if name in ("Month_Sin", "Month_Cos"):
        return "Month"
    return name
