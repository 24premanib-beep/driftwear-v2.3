"""
Central configuration for the Fashion Concept Drift ML engine.

Moved from the original Streamlit prototype (src/config.py). Every algorithm
setting below is UNCHANGED; only the file paths differ, because predictions,
drift events and model metadata now live in PostgreSQL and model files go
through the backend's ModelStorageService.

Paths can be overridden with environment variables so the engine works the
same inside Docker and on a developer machine.
"""
import os
from pathlib import Path

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT_DIR / "data")
DATASET_PATH = Path(os.getenv("DATASET_PATH") or DATA_DIR / "fashion_purchases.csv")

# ----------------------------------------------------------------------------
# Domain vocabulary
# ----------------------------------------------------------------------------
CATEGORIES = ["Tops", "Bottoms", "Dresses", "Footwear", "Outerwear", "Accessories"]
SEASONS = ["Winter", "Summer", "Monsoon", "Festive"]
PREFERENCES = ["Casual", "Formal", "Sporty", "Trendy", "Classic"]

# Month -> season (Indian retail calendar)
MONTH_TO_SEASON = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Summer", 4: "Summer", 5: "Summer",
    6: "Monsoon", 7: "Monsoon", 8: "Monsoon", 9: "Monsoon",
    10: "Festive", 11: "Festive",
}

# Example styles shown next to a predicted category (presentation only)
STYLE_EXAMPLES = {
    "Tops": ["Fitted T-Shirt", "Oversized Shirt", "Crop Top", "Polo"],
    "Bottoms": ["Baggy Jeans", "Cargo Pants", "Wide-Leg Trousers", "Joggers"],
    "Dresses": ["Midi Dress", "Maxi Dress", "Shirt Dress", "Wrap Dress"],
    "Footwear": ["Chunky Sneakers", "Loafers", "Running Shoes", "Block Heels"],
    "Outerwear": ["Denim Jacket", "Puffer Jacket", "Blazer", "Bomber"],
    "Accessories": ["Tote Bag", "Statement Watch", "Sunglasses", "Bucket Hat"],
}

# ----------------------------------------------------------------------------
# Synthetic data / trend periods
# ----------------------------------------------------------------------------
# Each period follows a DIFFERENT purchasing concept (see data_generator.py).
TREND_PERIODS = [
    {"period": 1, "name": "Classic Tops & Dresses", "records": 900},
    {"period": 2, "name": "Baggy Bottoms & Outerwear", "records": 600},
    {"period": 3, "name": "Sneakers & Accessories", "records": 600},
]
N_CUSTOMERS = 150
DEFAULT_SEED = 42

# The first N records are "historical data" used to train model v1.0.
INITIAL_TRAIN_SIZE = 300

# ----------------------------------------------------------------------------
# Drift detection & adaptation
# ----------------------------------------------------------------------------
DEFAULT_DETECTOR = "DDM"            # "DDM", "ADWIN" or "PageHinkley"
DDM_WARM_START = 30                 # records before DDM starts judging
DDM_WARNING_THRESHOLD = 2.0         # sigma for "Possible change"
DDM_DRIFT_THRESHOLD = 3.0           # sigma for "Concept drift"
# After each (re)training the detector is primed with this many out-of-fold
# validation errors, so it knows the model's normal error level from record 1.
CALIBRATION_SIZE = 40

ROLLING_WINDOW = 50                 # window for rolling accuracy / error charts
MIN_ADAPTATION_WINDOW = 15          # minimum records used to retrain after drift
MAX_ADAPTATION_WINDOW = 300         # cap on the sliding window
MIN_SEGMENT_BEFORE = 12             # min records before a candidate change point
MIN_SEGMENT_AFTER = 5               # min records after it
# After a drift retrain (vN.0) the model refreshes itself as more
# new-pattern data arrives: +25 -> vN.1, +75 -> vN.2, +150 -> vN.3
CONSOLIDATION_STEPS = (25, 75, 150)
PERF_EVAL_WINDOW = 50               # records used for before/after comparison

RANDOM_STATE = 42

# ----------------------------------------------------------------------------
# Additions for the real-time backend (new; nothing above changed)
# ----------------------------------------------------------------------------
# How many labeled outcomes the engine keeps in memory for window selection and
# retraining. The adaptation window is capped at MAX_ADAPTATION_WINDOW, so this
# only needs to cover "records since the last detector reset" comfortably.
HISTORY_BUFFER = int(os.getenv("HISTORY_BUFFER") or "5000")
# Rolling window used for the live accuracy figure sent over WebSocket.
LIVE_ROLLING_WINDOW = ROLLING_WINDOW
