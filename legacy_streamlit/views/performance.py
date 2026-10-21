"""Accuracy, precision, recall, F1 and before/after adaptation comparisons."""
import streamlit as st

from src import config
from src.evaluation import classification_metrics, metrics_by_version
from utils import visualization as viz
from utils.charts import show
from utils.state import engine
from utils.ui import empty_state, kpi, page_header, pct


def render():
    eng = engine()
    page_header("Model performance",
                "Metrics are computed on the stream: each prediction is scored against the real purchase "
                "before the model ever trains on it.")
    h = eng.history_df
    if h.empty:
        empty_state("No predictions to evaluate yet. Process records from the sidebar.")
        return

    scope = st.radio("Evaluate", ["Whole stream", f"Last {config.ROLLING_WINDOW} records", "Current model version"],
                     horizontal=True, label_visibility="collapsed")
    if scope == "Whole stream":
        part = h
    elif scope.startswith("Last"):
        part = h.tail(config.ROLLING_WINDOW)
    else:
        part = h[h["model_version"] == eng.version]
    mt = classification_metrics(part["actual"].tolist(), part["predicted"].tolist())
    base = classification_metrics(part["actual"].tolist(), part["baseline_pred"].tolist())

    c = st.columns(6)
    with c[0]:
        kpi("Accuracy", pct(mt["accuracy"]), f"Static v1.0: {pct(base['accuracy'])}")
    with c[1]:
        kpi("Precision", pct(mt["precision"]), "Macro average")
    with c[2]:
        kpi("Recall", pct(mt["recall"]), "Macro average")
    with c[3]:
        kpi("F1-score", pct(mt["f1"]), f"Static v1.0: {pct(base['f1'])}")
    with c[4]:
        kpi("Prediction error", pct(mt["error"]), "1 − accuracy")
    with c[5]:
        kpi("Predictions", f"{mt['n']:,}", scope)

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("#### Before vs after adaptation")
            events = [e for e in eng.drift_events if e.get("accuracy_after") is not None]
            if events:
                st.caption(f"Accuracy of the old model before and after the trend changed, and of the adapted "
                           f"model over the next {config.PERF_EVAL_WINDOW} records.")
                show(viz.before_after_bars(events), "perf_ba")
            elif eng.drift_events:
                empty_state(f"Drift detected — the 'after' score appears once {config.PERF_EVAL_WINDOW} "
                            "more records have been processed.")
            else:
                empty_state("No adaptation yet. Trigger a trend change to create one.")
    with c2:
        with st.container(border=True):
            st.markdown("#### Adaptive vs static model per trend period")
            st.caption("Why drift detection matters: the never-updated model collapses when the trend changes.")
            show(viz.adaptive_vs_static_by_period(h), "perf_period")

    with st.container(border=True):
        st.markdown("#### Metrics by model version")
        show(viz.version_metrics_bars(metrics_by_version(h)), "perf_ver")

    c3, c4 = st.columns([1, 1.2])
    with c3:
        with st.container(border=True):
            st.markdown("#### Prediction vs actual")
            st.caption(f"Confusion matrix for: {scope.lower()}.")
            show(viz.confusion_heatmap(part), "perf_cm")
    with c4:
        with st.container(border=True):
            st.markdown("#### Latest 60 predictions")
            st.caption("Squares are real purchases, circles are predictions. A red cross marks a miss.")
            show(viz.prediction_vs_actual_strip(h, 60, height=330), "perf_strip")
