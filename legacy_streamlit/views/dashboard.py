"""Main overview: loop status, KPIs, performance, category shift, drift timeline."""
import streamlit as st

from src import config
from src.evaluation import add_rolling_columns
from utils import visualization as viz
from utils.charts import show
from utils.state import engine
from utils.ui import STATUS_META, drift_loop, empty_state, kpi, page_header, pct


def category_shift_data(eng, h):
    """Categories before vs after the latest drift (or training data vs stream)."""
    if eng.drift_events:
        ev = eng.drift_events[-1]
        cp = int(ev["change_point_step"])
        before = h[(h["step"] < cp) & (h["step"] >= cp - 150)]["actual"]
        after = h[h["step"] >= cp]["actual"]
        if len(before) >= 10:
            return before, after, ("Before " + ev["event_id"], "After " + ev["event_id"])
        before = eng.dataset.iloc[: eng.train_size]["Target_Category"]
        return before, after, ("Historical training data", "After " + ev["event_id"])
    before = eng.dataset.iloc[: eng.train_size]["Target_Category"]
    return before, h["actual"], ("Historical training data", "Stream so far")


def render():
    eng = engine()
    page_header("Fashion concept drift monitor",
                "A Random Forest predicts each customer's next clothing category. "
                "When shopping trends shift, the drift detector notices the rising error and the model retrains itself.")
    drift_loop(eng, st.session_state.running)

    h = add_rolling_columns(eng.history_df)
    last = eng.last_prediction
    recent = eng.recent_metrics()
    m = STATUS_META[eng.status]
    last_drift = eng.drift_events[-1] if eng.drift_events else None

    cols = st.columns(6)
    with cols[0]:
        kpi("Current prediction", last["predicted"] if last else "—",
            (f"Actual: {last['actual']} {'✓' if last['correct'] else '✗'}") if last else "Start the stream")
    with cols[1]:
        kpi("Current accuracy", pct(recent["accuracy"]) if last else "—",
            f"Last {min(len(h), config.ROLLING_WINDOW)} predictions")
    with cols[2]:
        kpi("Model status", m["label"], m["text"], accent=m["color"])
    with cols[3]:
        kpi("Drift events", eng.n_drifts,
            f"Last at record {last_drift['step']:,}" if last_drift else "None yet")
    with cols[4]:
        kpi("Model version", eng.version, f"{len(eng.adaptations) - 1} adaptations")
    with cols[5]:
        kpi("Records processed", f"{len(h):,}", f"of {len(eng.dataset) - eng.train_size:,} in stream")

    st.write("")
    if h.empty:
        empty_state("No predictions yet. Press Start or Next in the sidebar to stream purchases through model v1.0. "
                    "Then press Simulate fashion trend change and watch the error rise until drift is detected.")
        return

    with st.container(border=True):
        st.markdown("#### Prediction performance over time")
        st.caption("Solid line: the adaptive model. Dashed line: the same v1.0 model if it were never updated. "
                   "Red dotted lines mark detected concept drift.")
        show(viz.accuracy_timeline(h, eng.drift_events), "dash_acc")

    c1, c2 = st.columns([1, 1.25])
    with c1:
        with st.container(border=True):
            st.markdown("#### Category mix before and after drift")
            before, after, labels = category_shift_data(eng, h)
            show(viz.category_before_after(before, after, labels, height=300), "dash_cat")
    with c2:
        with st.container(border=True):
            st.markdown("#### Drift timeline")
            st.caption("Trend changes, warnings, confirmed drift and model updates along the stream.")
            show(viz.drift_timeline(h, eng.drift_events, eng.adaptations, eng.trend_changes, height=300), "dash_tl")
