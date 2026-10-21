"""Data drift (input distributions) is measured separately from concept drift."""
import numpy as np

from app.services import data_drift as DD
from ml.simulation import SimulationFeed
from ml.stream_engine import DriftEngine


def _rows(n, seed=0, price_mu=7.3, pref_weights=None):
    rng = np.random.default_rng(seed)
    prefs = ["Casual", "Formal", "Sporty", "Trendy", "Classic"]
    return [{"Price": float(np.clip(rng.lognormal(price_mu, 0.5), 199, 49999)),
             "Discount": float(rng.choice([0, 10, 20, 30])), "Purchase_Frequency": int(rng.integers(1, 20)),
             "Recency": int(rng.integers(0, 120)), "Customer_Preference": str(rng.choice(prefs, p=pref_weights)),
             "Previous_Category": "Tops", "Season": "Summer", "Month": 4} for _ in range(n)]


def test_same_distribution_is_stable():
    res = DD.compare(_rows(400, 1), _rows(300, 2))
    assert res["status"] == "STABLE" and res["affected_features"] == [] and res["max_psi"] < DD.PSI_WARNING
    assert res["triggers_adaptation"] is False
    assert res["explanation"]["data_drift"] == "Data drift means the input data changed."


def test_price_shift_is_flagged_on_price_only():
    res = DD.compare(_rows(400, 1), _rows(300, 2, price_mu=8.2))
    price = next(f for f in res["features"] if f["feature"] == "Price")
    assert res["status"] == "DRIFT" and price["status"] == "DRIFT" and price["psi"] > DD.PSI_DRIFT
    assert price["ks_pvalue"] is not None and price["ks_pvalue"] < 0.01
    assert price["current_mean"] > price["reference_mean"]
    assert res["affected_features"] == ["Price"]
    assert abs(sum(b["reference"] for b in price["distribution"]) - 1) < 0.01


def test_categorical_shift_reports_the_biggest_change():
    res = DD.compare(_rows(400, 1), _rows(300, 2, pref_weights=[0.05, 0.05, 0.05, 0.8, 0.05]))
    pref = next(f for f in res["features"] if f["feature"] == "Customer_Preference")
    assert pref["status"] == "DRIFT" and pref["top_shift"]["bucket"] == "Trendy" and pref["top_shift"]["change"] > 0.4


def test_insufficient_data_is_reported_not_guessed():
    res = DD.compare(_rows(400, 1), _rows(10, 2))
    assert res["status"] == "INSUFFICIENT_DATA" and res["features"] == [] and res["drift_score"] is None
    assert "No data available" in res["message"]


def _concept_drift_seen(train, stream_rows):
    eng, _ = DriftEngine.bootstrap("simulation", train)
    statuses = []
    for rec in stream_rows:
        p = eng.predict(rec)
        statuses.append(eng.record_outcome(rec, rec["Target_Category"], p.predicted, p.model_version).status)
    return "DRIFT" in statuses


def test_data_drift_and_concept_drift_are_independent_on_the_synthetic_stream():
    """Within trend period 1 the concept is fixed, yet inputs drift (purchase counts grow, seasons turn):
    data drift WITHOUT concept drift. Across the period 1 → 2 change, price and preference keep their
    distribution while the purchase rule changes: concept drift WITHOUT drift in those inputs."""
    data = SimulationFeed.from_seed().dataset
    p1 = data[data["Period"] == 1]
    train, early, late = p1.iloc[:300], p1.iloc[300:600], p1.iloc[600:900]

    within = {f["feature"]: f for f in DD.compare(early.to_dict("records"), late.to_dict("records"))["features"]}
    assert within["Purchase_Frequency"]["status"] == "DRIFT"         # input distribution changed...
    assert not _concept_drift_seen(train, p1.iloc[300:900].to_dict("records"))   # ...but no concept drift

    p2 = data[data["Period"] == 2].iloc[:300]
    across = {f["feature"]: f for f in DD.compare(early.to_dict("records"), p2.to_dict("records"))["features"]}
    assert across["Price"]["status"] == "STABLE" and across["Customer_Preference"]["status"] == "STABLE"
    assert _concept_drift_seen(train, p2.to_dict("records"))         # while the X → y relationship changed
