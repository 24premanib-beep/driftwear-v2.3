"""
Why did the model predict this category? (one prediction at a time)

Method: decision-path contributions for tree ensembles (the "Saabas" /
treeinterpreter method). No extra dependency and no background dataset:

  * In every decision tree, a record travels from the root to a leaf.
  * Each node holds the class distribution of the training records that
    reached it. Every split therefore moves the probability of the predicted
    class up or down, and that move is credited to the feature the split used.
  * Averaged over the 100 trees of the forest:

        P(predicted class) = base value (root average) + sum of contributions

    which holds exactly, so the explanation always adds up to the confidence
    shown next to the prediction.

One-hot columns (e.g. Season_Winter) and engineered columns (Final_Price,
Month_Sin/Month_Cos) are folded back into the eight input fields a person
filled in, using the same mapping as the global feature importance.

Contributions are signed: positive values pushed the model towards the
predicted category, negative values pushed it away. `share` is each field's
part of the total absolute movement, which is what the UI shows as a percentage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.feature_engineering import FEATURE_LABELS, RAW_FEATURES, original_feature_of

METHOD = "Decision-path contributions of the Random Forest (treeinterpreter / Saabas method)"


def _node_probabilities(tree) -> np.ndarray:
    """Class distribution per node, normalised (works whether value holds counts or fractions)."""
    value = tree.value[:, 0, :].astype(float)
    totals = value.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1.0
    return value / totals


def _tree_contributions(tree, x: np.ndarray, class_idx: int, n_features: int) -> tuple[float, np.ndarray]:
    probs = _node_probabilities(tree)
    left, right, feature, threshold = tree.children_left, tree.children_right, tree.feature, tree.threshold
    contrib = np.zeros(n_features)
    node = 0
    while left[node] != -1:                       # -1 marks a leaf
        f = feature[node]
        child = left[node] if x[f] <= threshold[node] else right[node]
        contrib[f] += probs[child, class_idx] - probs[node, class_idx]
        node = child
    return float(probs[0, class_idx]), contrib


def explain_prediction(model, X: pd.DataFrame, top_k: int | None = None) -> dict:
    """Explain the model's prediction for a one-row feature frame (output of record_to_frame).

    Returns {"method", "predicted", "probability", "base_value", "contributions": [...]}, where the
    contributions are sorted by absolute size and each has feature, label, value, contribution, share.
    """
    prep, clf = model.named_steps["prep"], model.named_steps["clf"]
    encoded = prep.transform(X)
    if hasattr(encoded, "toarray"):
        encoded = encoded.toarray()
    x = np.asarray(encoded, dtype=float)[0]
    proba = clf.predict_proba(encoded)[0]
    class_idx = int(np.argmax(proba))
    predicted = str(clf.classes_[class_idx])

    n_cols = x.shape[0]
    base, total = 0.0, np.zeros(n_cols)
    for est in clf.estimators_:
        b, c = _tree_contributions(est.tree_, x, class_idx, n_cols)
        base += b
        total += c
    n_trees = len(clf.estimators_)
    base /= n_trees
    total /= n_trees

    by_field: dict[str, float] = {f: 0.0 for f in RAW_FEATURES}
    for name, value in zip(prep.get_feature_names_out(), total):
        raw = original_feature_of(name)
        by_field[raw] = by_field.get(raw, 0.0) + float(value)

    abs_sum = sum(abs(v) for v in by_field.values()) or 1.0
    row = X.iloc[0]
    items = []
    for field, value in by_field.items():
        raw_value = row.get(field) if field in row.index else None
        if isinstance(raw_value, np.generic):
            raw_value = raw_value.item()
        items.append({
            "feature": field,
            "label": FEATURE_LABELS.get(field, field),
            "value": raw_value,
            "contribution": round(value, 5),
            "share": round(abs(value) / abs_sum, 4),
            "direction": "supports" if value >= 0 else "opposes",
        })
    items.sort(key=lambda it: abs(it["contribution"]), reverse=True)
    return {
        "method": METHOD,
        "predicted": predicted,
        "probability": round(float(proba[class_idx]), 5),
        "base_value": round(base, 5),
        "contributions": items[:top_k] if top_k else items,
    }
