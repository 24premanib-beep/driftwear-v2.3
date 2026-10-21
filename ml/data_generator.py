"""
Synthetic, time-ordered fashion purchase data WITH built-in concept drift.

Each trend period uses a different "concept" – a different rule that maps a
customer's features to the category they buy next. The features look similar
across periods, but the relationship X -> y changes. That is exactly what
concept drift means, so a model trained on Period 1 will start failing in
Period 2.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml import config

# Concept tables: preference -> category for [low, mid, high] price bands.
CONCEPTS = {
    1: {  # Classic Tops & Dresses
        "Casual": ["Tops", "Tops", "Dresses"],
        "Formal": ["Tops", "Dresses", "Dresses"],
        "Sporty": ["Tops", "Bottoms", "Footwear"],
        "Trendy": ["Dresses", "Dresses", "Tops"],
        "Classic": ["Tops", "Dresses", "Outerwear"],
    },
    2: {  # Baggy Bottoms & Outerwear
        "Casual": ["Bottoms", "Bottoms", "Outerwear"],
        "Formal": ["Bottoms", "Outerwear", "Outerwear"],
        "Sporty": ["Bottoms", "Bottoms", "Outerwear"],
        "Trendy": ["Outerwear", "Bottoms", "Bottoms"],
        "Classic": ["Tops", "Outerwear", "Outerwear"],
    },
    3: {  # Sneakers & Accessories
        "Casual": ["Accessories", "Footwear", "Footwear"],
        "Formal": ["Accessories", "Accessories", "Footwear"],
        "Sporty": ["Footwear", "Footwear", "Footwear"],
        "Trendy": ["Accessories", "Footwear", "Accessories"],
        "Classic": ["Accessories", "Accessories", "Bottoms"],
    },
}

PREFERENCE_WEIGHTS = [0.28, 0.18, 0.18, 0.20, 0.16]
NOISE_RATE = 0.08          # random category (real-world randomness)
LOYALTY_RATE = 0.06        # customer repeats their previous category


def price_band(price: float) -> int:
    """0 = low (<1000), 1 = mid (1000-2500), 2 = high (>2500)."""
    if price < 1000:
        return 0
    if price <= 2500:
        return 1
    return 2


def concept_label(concept_id: int, preference: str, price: float,
                  season: str, discount: float, previous: str,
                  rng: np.random.Generator) -> str:
    """Apply a concept rule (plus a little noise) to produce the true label."""
    r = rng.random()
    if r < NOISE_RATE:
        return str(rng.choice(config.CATEGORIES))
    if r < NOISE_RATE + LOYALTY_RATE:
        return previous
    label = CONCEPTS[concept_id][preference][price_band(price)]
    # Small seasonal rule that holds in every period: winter clearance -> Outerwear
    if season == "Winter" and discount >= 45 and concept_id != 3:
        label = "Outerwear"
    return label


def generate_dataset(seed: int = config.DEFAULT_SEED,
                     periods: list[dict] | None = None,
                     n_customers: int = config.N_CUSTOMERS) -> pd.DataFrame:
    """Generate the full time-ordered dataset (all trend periods)."""
    rng = np.random.default_rng(seed)
    periods = periods or config.TREND_PERIODS

    # Per-customer state so Previous_Category / Frequency / Recency are consistent
    cust_ids = [f"C{1000 + i}" for i in range(n_customers)]
    cust_pref = {c: str(rng.choice(config.PREFERENCES, p=PREFERENCE_WEIGHTS)) for c in cust_ids}
    last_cat = {c: str(rng.choice(config.CATEGORIES)) for c in cust_ids}
    last_date = {c: None for c in cust_ids}
    count = {c: int(rng.integers(1, 6)) for c in cust_ids}

    total = sum(p["records"] for p in periods)
    start = pd.Timestamp("2024-01-01")
    # ~18 months of purchases, strictly increasing timestamps
    offsets = np.sort(rng.uniform(0, 540 * 24 * 3600, size=total))
    dates = [start + pd.Timedelta(seconds=float(s)) for s in offsets]

    rows, i = [], 0
    for p in periods:
        for _ in range(p["records"]):
            date = dates[i]
            cust = str(rng.choice(cust_ids))
            # preferences drift a little at individual level too
            pref = cust_pref[cust] if rng.random() > 0.15 else str(rng.choice(config.PREFERENCES))
            month = int(date.month)
            season = config.MONTH_TO_SEASON[month]
            price = float(np.round(np.clip(rng.lognormal(7.3, 0.6), 199, 7999), -1))
            discount = float(rng.choice([0, 5, 10, 15, 20, 25, 30, 40, 50, 60],
                                        p=[.22, .08, .14, .1, .12, .08, .1, .07, .06, .03]))
            if season == "Festive":
                discount = min(70.0, discount + 10)
            recency = 90 if last_date[cust] is None else max(0, (date - last_date[cust]).days)
            target = concept_label(p["period"], pref, price, season, discount, last_cat[cust], rng)

            rows.append({
                "Record_ID": i,
                "Customer_ID": cust,
                "Purchase_Date": date.strftime("%Y-%m-%d %H:%M"),
                "Previous_Category": last_cat[cust],
                "Purchase_Frequency": count[cust],
                "Recency": int(recency),
                "Season": season,
                "Month": month,
                "Price": price,
                "Discount": discount,
                "Customer_Preference": pref,
                "Target_Category": target,
                "Period": p["period"],
                "Trend": p["name"],
            })
            last_cat[cust], last_date[cust] = target, date
            count[cust] += 1
            i += 1

    return pd.DataFrame(rows)


def save_dataset(df: pd.DataFrame, path=config.DATASET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


if __name__ == "__main__":
    data = generate_dataset()
    save_dataset(data)
    print(data.groupby("Period")["Target_Category"].value_counts(normalize=True).round(2))
