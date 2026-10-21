"""
DATA drift: has the distribution of the INPUT features changed?

    Data drift    = P(X) changed      (e.g. prices got higher, more winter purchases)
    Concept drift = P(y | X) changed  (the same customer now buys something else)

DriftWear adapts on CONCEPT drift only: that is what DDM / ADWIN / Page-Hinkley
detect on the prediction-error stream. Data drift is reported next to it as a
diagnostic, because:
  * inputs can shift while the model stays accurate (no adaptation needed), and
  * the input mix can look unchanged while the relationship changes (concept
    drift with no data drift at all, which is exactly what the synthetic
    trend periods contain for price, discount and preference).
So this module never triggers retraining and never labels anything "concept drift".

Method (per feature, reference window vs current window):
  * Population Stability Index (PSI) for every feature
        numeric:     10 quantile bins taken from the reference window
        categorical: one bin per category
    PSI = sum((cur% - ref%) * ln(cur% / ref%)), with a small epsilon so empty bins are finite.
    Usual reading: < 0.10 stable, 0.10-0.25 moderate shift (WARNING), > 0.25 significant shift (DRIFT).
  * Kolmogorov-Smirnov two-sample test for numeric features (statistic + p-value), as a second opinion.

Data drift needs no labels, so the current window uses every recent input,
including predictions still waiting for their actual category.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from ml import config as ml_config
from ml.feature_engineering import FEATURE_LABELS

NUMERIC = ["Price", "Discount", "Purchase_Frequency", "Recency"]
CATEGORICAL = ["Previous_Category", "Customer_Preference", "Season", "Month"]
FEATURES = ["Previous_Category", "Customer_Preference", "Price", "Discount", "Season", "Month",
            "Purchase_Frequency", "Recency"]
VOCAB = {"Previous_Category": ml_config.CATEGORIES, "Customer_Preference": ml_config.PREFERENCES,
         "Season": ml_config.SEASONS, "Month": [str(m) for m in range(1, 13)]}
# Calendar features shift with the date by design; flagged so nobody mistakes seasonality for a problem.
CALENDAR = {"Season", "Month"}

PSI_WARNING = 0.10
PSI_DRIFT = 0.25
MIN_CURRENT = 30
MIN_REFERENCE = 50
EPS = 1e-4

STATUS_TEXT = {
    "STABLE": "Input distributions match the reference data.",
    "WARNING": "Some input distributions are shifting (moderate PSI).",
    "DRIFT": "Input distributions changed significantly (high PSI).",
    "INSUFFICIENT_DATA": "Not enough recent inputs to compare distributions yet.",
}
EXPLANATION = {
    "data_drift": "Data drift means the input data changed.",
    "concept_drift": "Concept drift means the relationship between the input and target changed.",
    "policy": "DriftWear retrains on confirmed concept drift (from the prediction-error stream). "
              "Data drift is shown for diagnosis only and never triggers adaptation on its own.",
}


def feature_status(psi: float | None) -> str:
    if psi is None:
        return "INSUFFICIENT_DATA"
    if psi > PSI_DRIFT:
        return "DRIFT"
    if psi > PSI_WARNING:
        return "WARNING"
    return "STABLE"


def _psi(ref_share: list[float], cur_share: list[float]) -> float:
    total = 0.0
    for r, c in zip(ref_share, cur_share):
        r, c = max(r, EPS), max(c, EPS)
        total += (c - r) * math.log(c / r)
    return float(total)


def _values(rows: list[dict], feature: str) -> list:
    out = []
    for r in rows:
        v = r.get(feature)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        out.append(v)
    return out


def _categorical(ref: list, cur: list, feature: str) -> dict:
    ref_s, cur_s = [str(int(v)) if feature == "Month" else str(v) for v in ref], \
                   [str(int(v)) if feature == "Month" else str(v) for v in cur]
    cats = list(VOCAB.get(feature, [])) or sorted(set(ref_s) | set(cur_s))
    cats += sorted((set(ref_s) | set(cur_s)) - set(cats))
    rc, cc = Counter(ref_s), Counter(cur_s)
    ref_share = [rc[c] / len(ref_s) for c in cats]
    cur_share = [cc[c] / len(cur_s) for c in cats]
    dist = [{"bucket": c, "reference": round(r, 4), "current": round(k, 4)}
            for c, r, k in zip(cats, ref_share, cur_share)]
    top = max(dist, key=lambda d: abs(d["current"] - d["reference"]))
    return {"psi": _psi(ref_share, cur_share), "distribution": dist,
            "top_shift": {"bucket": top["bucket"], "reference": top["reference"], "current": top["current"],
                          "change": round(top["current"] - top["reference"], 4)},
            "ks_statistic": None, "ks_pvalue": None, "reference_mean": None, "current_mean": None}


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:g}"


def _numeric(ref: list, cur: list) -> dict:
    r = np.asarray(ref, dtype=float)
    c = np.asarray(cur, dtype=float)
    inner = np.unique(np.quantile(r, np.linspace(0.1, 0.9, 9)))
    edges = np.concatenate([[-np.inf], inner, [np.inf]])
    rh = np.histogram(r, edges)[0] / len(r)
    ch = np.histogram(c, edges)[0] / len(c)
    labels = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if np.isinf(lo):
            labels.append(f"≤ {_fmt(hi)}")
        elif np.isinf(hi):
            labels.append(f"> {_fmt(lo)}")
        else:
            labels.append(f"{_fmt(lo)}–{_fmt(hi)}")
    try:
        from scipy.stats import ks_2samp          # scipy ships with scikit-learn
        ks = ks_2samp(r, c)
        ks_stat, ks_p = float(ks.statistic), float(ks.pvalue)
    except Exception:  # noqa: BLE001 - KS is a second opinion; PSI alone still decides the status
        ks_stat = ks_p = None
    dist = [{"bucket": lab, "reference": round(float(a), 4), "current": round(float(b), 4)}
            for lab, a, b in zip(labels, rh, ch)]
    return {"psi": _psi(list(rh), list(ch)), "distribution": dist, "top_shift": None,
            "ks_statistic": None if ks_stat is None else round(ks_stat, 4),
            "ks_pvalue": None if ks_p is None else round(ks_p, 6),
            "reference_mean": round(float(r.mean()), 2), "current_mean": round(float(c.mean()), 2)}


def compare(reference: list[dict], current: list[dict], *, reference_info: dict | None = None,
            current_info: dict | None = None) -> dict:
    """Compare two windows of feature records (dicts with the dataset's column names)."""
    base = {
        "thresholds": {"warning": PSI_WARNING, "drift": PSI_DRIFT},
        "reference": {**(reference_info or {}), "n": len(reference)},
        "current": {**(current_info or {}), "n": len(current)},
        "explanation": EXPLANATION, "triggers_adaptation": False,
        "method": "Population Stability Index per feature (10 quantile bins for numbers, one bin per "
                  "category); Kolmogorov-Smirnov test as a second opinion for numeric features.",
    }
    if len(current) < MIN_CURRENT or len(reference) < MIN_REFERENCE:
        need = []
        if len(current) < MIN_CURRENT:
            need.append(f"{MIN_CURRENT} recent inputs (have {len(current)})")
        if len(reference) < MIN_REFERENCE:
            need.append(f"{MIN_REFERENCE} reference records (have {len(reference)})")
        return {**base, "status": "INSUFFICIENT_DATA", "message": "No data available: needs " + " and ".join(need) + ".",
                "drift_score": None, "max_psi": None, "affected_features": [], "features": []}

    features = []
    for f in FEATURES:
        ref_v, cur_v = _values(reference, f), _values(current, f)
        if len(ref_v) < MIN_REFERENCE or len(cur_v) < MIN_CURRENT:
            continue
        res = _categorical(ref_v, cur_v, f) if f in CATEGORICAL else _numeric(ref_v, cur_v)
        psi = round(res["psi"], 4)
        features.append({"feature": f, "label": FEATURE_LABELS.get(f, f),
                         "kind": "categorical" if f in CATEGORICAL else "numeric",
                         "calendar": f in CALENDAR, **res, "psi": psi, "status": feature_status(psi)})
    features.sort(key=lambda x: x["psi"], reverse=True)
    psis = [x["psi"] for x in features]
    max_psi = max(psis) if psis else None
    status = feature_status(max_psi)
    affected = [x["feature"] for x in features if x["status"] != "STABLE"]
    message = STATUS_TEXT[status]
    if affected and all(f in CALENDAR for f in affected):
        message += " Only calendar features moved, which is expected as time passes."
    return {**base, "status": status, "message": message,
            "drift_score": round(float(np.mean(psis)), 4) if psis else None,
            "max_psi": max_psi, "affected_features": affected, "features": features}
