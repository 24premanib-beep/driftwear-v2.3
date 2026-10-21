"""Project explanation for the viva."""
import streamlit as st

from src import config
from src.drift_detector import RIVER_AVAILABLE
from utils.ui import page_header


def render():
    page_header("About the project",
                "Fashion/clothing category prediction using concept drift detection and model adaptation.")

    c1, c2 = st.columns([1.3, 1], gap="large")
    with c1:
        st.markdown("""
#### The problem
A model trained on last season's purchases assumes the link between a customer's profile and what they buy
stays the same. In fashion it does not: trends, festivals, sales and personal taste change it. When that
relationship **P(category | customer features)** changes, we call it **concept drift**. The old model keeps
answering confidently, but more and more of its answers are wrong.

#### The objective
Build a system that notices this on its own and fixes itself:

**Learn → Predict → Monitor → Detect drift → Adapt → Predict again**

Fashion is the application domain; the drift loop is the contribution. This is not a recommender.

#### How it works here
1. **Learn.** A Random Forest (scikit-learn) is trained on the first 300 historical purchases and saved with joblib as **v1.0**.
2. **Predict.** Purchases stream in date order. For each one the model predicts the category before the real one is revealed.
3. **Monitor.** Each outcome becomes 0 (correct) or 1 (wrong).
4. **Detect.** The error stream goes into River's **DDM** detector. It reports *Stable*, *Possible change* (2σ) or *Concept drift* (3σ).
5. **Adapt.** On drift, the system estimates where the error jumped, takes the records after that point as a sliding window,
   retrains, saves the model and bumps the major version (**v1.0 → v2.0**). The detector is reset.
6. **Keep learning.** As more new-trend data arrives the model refreshes itself (**v2.1, v2.2, v2.3**).

A frozen copy of v1.0 predicts alongside the live model, so the benefit of adaptation is visible in every chart.
""")
    with c2:
        with st.container(border=True):
            st.markdown("#### Trend periods in the synthetic data")
            st.markdown("""
- **Period 1, Classic Tops & Dresses:** mostly Tops and Dresses.
- **Period 2, Baggy Bottoms & Outerwear:** the same kinds of customers now buy Bottoms and Outerwear.
- **Period 3, Sneakers & Accessories:** Footwear and Accessories take over.

Within each period the category depends on customer preference and price band, with a winter-sale rule,
some brand loyalty and 8% random noise, so the model can learn it but not perfectly.
""")
        with st.container(border=True):
            st.markdown("#### Why DDM?")
            st.markdown("It works directly on the error rate, has a built-in warning zone, and its rule fits on one line "
                        "(see Drift Monitoring). ADWIN and Page-Hinkley can be selected in the sidebar settings to compare.")
            if not RIVER_AVAILABLE:
                st.warning("River is not installed in this environment, so an identical built-in DDM is used.")

    st.markdown("#### Demo script")
    st.markdown(f"""
1. Open **Dashboard**: the loop shows model v1.0 and status *Stable*.
2. Press **Start** (or **Next** a few times). Predictions, actual results and errors appear on **Data Stream**.
3. Press **Simulate fashion trend change**. The stream jumps to the next trend period.
4. Keep processing. The error line on **Drift Monitoring** climbs; amber warning dots appear.
5. DDM confirms drift: the red **Concept drift detected** alert appears, the model adapts, **v1.0 → v2.0**.
6. Continue: accuracy recovers while the dashed static model stays low. Refreshes add v2.1 to v2.3.
7. Open **Model Performance** and **Model Adaptation** for the before vs after comparison.

Tip: keep *Pause when drift is detected* on (sidebar settings) so the moment stays on screen.
""")

    with st.expander("Files and structure", icon=":material/account_tree:"):
        st.code("""fashion-concept-drift/
├── app.py                    navigation + page wiring
├── data/                     fashion_purchases.csv, predictions.csv, drift_events.csv
├── models/                   model.pkl, baseline_model.pkl, model_metadata.json, archive/
├── src/
│   ├── config.py             all settings in one place
│   ├── data_generator.py     synthetic time-ordered data with 3 trend periods
│   ├── preprocessing.py      validation, missing values, duplicates, dates
│   ├── feature_engineering.py encoding + engineered features
│   ├── model.py              Random Forest train / predict / save / load
│   ├── drift_detector.py     River DDM / ADWIN / Page-Hinkley wrapper
│   ├── adaptation.py         change-point window + retraining
│   ├── evaluation.py         accuracy, precision, recall, F1
│   ├── storage.py            CSV/JSON/joblib (swap for a database later)
│   └── stream_engine.py      the Learn → Predict → Monitor → Detect → Adapt loop
├── utils/                    ui.py, visualization.py, state.py, charts.py
└── views/                    one file per page""", language="text")
        st.markdown(f"Key settings: initial training {config.INITIAL_TRAIN_SIZE} records, DDM warm-up "
                    f"{config.DDM_WARM_START}, warning {config.DDM_WARNING_THRESHOLD}σ, drift {config.DDM_DRIFT_THRESHOLD}σ, "
                    f"minimum adaptation window {config.MIN_ADAPTATION_WINDOW}, refreshes after "
                    f"{', '.join(map(str, config.CONSOLIDATION_STEPS))} records.")

    st.caption("Tech stack: Python, Pandas, NumPy, scikit-learn, River, Plotly, Streamlit, joblib, CSV/JSON.")
