> **Legacy prototype.** This is the original Streamlit version of the project, kept unchanged and
> self-contained for reference. The maintained application (FastAPI + PostgreSQL + WebSockets, React frontend)
> lives in the repository root — see [`../README.md`](../README.md). The ML algorithms are shared: they were moved
> to [`../ml/`](../ml/) without behavioural changes (verified record by record by `backend/tests/test_ml_engine.py`).
>
> Run this version from this folder: `pip install -r requirements.txt && streamlit run app.py`

# DriftWear: Fashion Category Prediction with Concept Drift Detection

An interactive Streamlit prototype that predicts a customer's **next clothing category** and,
more importantly, **notices when fashion trends change** and **adapts the model automatically**.

```
Learn → Predict → Monitor → Detect Drift → Adapt → Predict Again
```

Fashion is the application domain. The project's focus is concept drift detection (River) and model
adaptation (scikit-learn), driven entirely by the real prediction-error stream. Nothing is faked:
the status only turns red when the drift detector fires on actual errors.

---

## 1. Setup

Requires Python 3.10 to 3.12.

```bash
cd fashion-concept-drift
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501. On first launch it:

1. loads `data/fashion_purchases.csv` (or generates it if missing),
2. trains **model v1.0** on the first 300 historical records,
3. saves `models/model.pkl`, `models/baseline_model.pkl` and `models/model_metadata.json`.

State is saved after every step, so closing and reopening the app continues where you stopped.
Use **Reset** in the sidebar to start the stream again, or **New data** for a fresh synthetic dataset.

To regenerate the default dataset from the command line: `python -m src.data_generator`

---

## 2. Demo script (viva / presentation)

| Step | Action | What to point at |
|---|---|---|
| 1 | Open **Dashboard** | Loop shows v1.0, status *Stable* |
| 2 | Sidebar: **Start** (or **Next** a few times) | Predictions appear; open **Data Stream** to show prediction → actual → correct/wrong |
| 3 | Process some records | Error is fed to the detector as 0/1 |
| 4 | Click **Simulate fashion trend change** | Stream jumps to the next trend period |
| 5 | Keep processing | **Drift Monitoring**: error line climbs, amber warning dots |
| 6 | DDM fires | Big red **⚠️ Concept drift detected** alert |
| 7 | Automatic | **🔄 Adapting model…** status steps |
| 8 | Automatic | **Model updated: v1.0 → v2.0** |
| 9 | Continue streaming | Accuracy recovers; refreshes v2.1, v2.2, v2.3 while the dashed static model stays low |
| 10 | **Model Performance** / **Model Adaptation** | Before vs after adaptation charts and tables |

Keep **Pause when drift is detected** on (sidebar, Settings) so the drift moment stays on screen.
"Process 10 records" also stops right after a drift for the same reason.

---

## 3. How it works

### Data (`src/data_generator.py`)
2,100 time-ordered purchases from 150 customers over about 18 months, in three trend periods:

| Period | Trend | Dominant categories |
|---|---|---|
| 1 | Classic Tops & Dresses | Dresses 44%, Tops 36% |
| 2 | Baggy Bottoms & Outerwear | Bottoms 49%, Outerwear 40% |
| 3 | Sneakers & Accessories | Footwear 50%, Accessories 39% |

Each period uses a **different rule** mapping *(customer preference, price band)* to category, plus a winter-sale
rule, some brand loyalty and 8% noise. The inputs look the same across periods but the input → category
relationship changes: that is real concept drift, not just a change in label counts.

Fields: `Customer_ID, Purchase_Date, Previous_Category, Purchase_Frequency, Recency, Season, Month, Price,
Discount, Customer_Preference, Target_Category` (+ `Period`, `Trend` for display). Seasons follow an Indian retail
calendar (Winter, Summer, Monsoon, Festive).

### Preprocessing and features (`preprocessing.py`, `feature_engineering.py`)
Column validation, date parsing and time ordering, duplicate removal, median/mode filling of missing values,
clipping of invalid ranges, one-hot encoding of categorical fields, plus engineered `Final_Price` and
cyclical `Month_Sin` / `Month_Cos`.

### Model (`model.py`)
`RandomForestClassifier` (100 trees) inside a scikit-learn `Pipeline`, saved with joblib.
The confidence shown on the Prediction page is the forest's real `predict_proba` output.

### Drift detection (`drift_detector.py`)
For every record: predict → reveal actual → `error = 0/1` → `detector.update(error)`.

Default detector: **River DDM** (Drift Detection Method).

- `p` = error rate, `s = sqrt(p(1-p)/n)`, and the detector remembers the lowest `p_min + s_min`
- **Possible change** when `p + s > p_min + 2·s_min`
- **Concept drift** when `p + s > p_min + 3·s_min`

After every (re)training the detector is reset and **calibrated** with 40 out-of-fold validation errors of the
new model, so it knows the normal error level even if the trend changes a few records later.
ADWIN and Page-Hinkley can be selected in the sidebar settings for comparison.

### Adaptation (`adaptation.py`, `stream_engine.py`)
1. Estimate the **change point**: the split of the recent error sequence where the jump in error rate is most significant.
2. Take the records after it as the **sliding window** (at least 15, at most 300).
3. Retrain a fresh Random Forest on that window, save it, bump the major version (**v1.0 → v2.0**).
4. Reset and recalibrate the detector.
5. As more new-trend data arrives, refresh the model after +25, +75 and +150 records (**v2.1, v2.2, v2.3**).

A frozen copy of v1.0 (the **static model**) predicts every record too, so the value of adaptation is visible.

### Evaluation (`evaluation.py`)
Accuracy, macro precision, recall, F1, error rate, rolling accuracy (window 50), per-version metrics, and
before/after accuracy for each adaptation (old model before the change, old model after the change,
adapted model over the next 50 records).

Typical full-stream result with the default dataset:

| Period | Adaptive model | Static v1.0 |
|---|---|---|
| 1 | ~82% | ~82% |
| 2 | ~73% | ~18% |
| 3 | ~69% | ~5% |

---

## 4. Project structure

```
fashion-concept-drift/
├── app.py                     Streamlit entry: navigation + sidebar controls
├── .streamlit/config.toml     theme
├── data/
│   ├── fashion_purchases.csv  dataset (auto-generated if missing)
│   ├── predictions.csv        every processed record (created at runtime)
│   └── drift_events.csv       detected drift events (created at runtime)
├── models/
│   ├── model.pkl              current model (created at runtime)
│   ├── baseline_model.pkl     frozen v1.0 for comparison
│   ├── model_metadata.json    version, stream position, adaptation history
│   └── archive/               every model version
├── src/
│   ├── config.py              all settings
│   ├── data_generator.py
│   ├── preprocessing.py
│   ├── feature_engineering.py
│   ├── model.py
│   ├── drift_detector.py
│   ├── adaptation.py
│   ├── evaluation.py
│   ├── storage.py             all file I/O (replace with a DB class later)
│   └── stream_engine.py       the Learn → Predict → Monitor → Detect → Adapt loop
├── utils/
│   ├── ui.py                  CSS, cards, status badges, drift-loop ribbon
│   ├── visualization.py       Plotly charts
│   ├── charts.py              chart rendering helper
│   └── state.py               session state, stream controls, drift alert
├── views/                     one module per page
│   ├── dashboard.py  prediction.py  drift_monitoring.py  performance.py
│   └── data_stream.py  adaptation.py  about.py
├── requirements.txt
└── README.md
```

**Adding a backend later:** all reads/writes go through `src/storage.py` (`LocalStorage`). Write a class with the
same methods backed by a database and pass it to `StreamEngine(storage=...)`; the rest of the app stays the same.

---

## 5. Using your own CSV
Replace `data/fashion_purchases.csv` with a file containing the required columns (see above), time-ordered or with
valid dates, then press **Reset**. `Period`/`Trend` are optional. "Simulate fashion trend change" needs a `Period`
column with more than one value.

## 6. Tuning
Everything is in `src/config.py`: initial training size, DDM thresholds and warm-up, calibration size,
adaptation window limits, refresh schedule, rolling window.

## 7. Troubleshooting
- **"River is not installed" note in the sidebar:** run `pip install river`. Until then an identical built-in DDM is used.
- **App looks unstyled / sidebar light:** upgrade Streamlit: `pip install -U "streamlit>=1.46"`.
- **Strange state after changing code or library versions:** press **Reset**, or delete `models/*.pkl`,
  `models/model_metadata.json` and `data/predictions.csv`.
- **Stream feels slow:** choose *Fast* speed in the sidebar settings.
