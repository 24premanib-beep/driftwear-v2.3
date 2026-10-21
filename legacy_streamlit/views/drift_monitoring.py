"""Drift status, error stream with drift markers, and the drift event log."""
import pandas as pd
import streamlit as st

from src import config
from src.drift_detector import DETECTOR_INFO
from src.evaluation import add_rolling_columns
from utils import visualization as viz
from utils.charts import show
from utils.state import engine
from utils.ui import STATUS_META, empty_state, esc, kpi, page_header, pct


def render():
    eng = engine()
    page_header("Drift monitoring",
                "Every prediction becomes a 0 (correct) or 1 (wrong) and is fed to the River drift detector. "
                "Drift is declared only when that error stream changes significantly.")

    h = add_rolling_columns(eng.history_df)
    status = eng.status
    m = STATUS_META[status]
    last = eng.drift_events[-1] if eng.drift_events else None

    # ---- status hero -------------------------------------------------------
    st.markdown(
        f"<div class='dw-loop' style='border-left:6px solid {m['color']};background:linear-gradient(110deg,{m['bg']} 0%,#fff 60%)'>"
        f"<div style='font-size:.9rem;color:#6B6580;font-weight:600'>Current drift status</div>"
        f"<div class='dw-display' style='font-size:2.4rem;font-weight:800;color:{m['color']};line-height:1.15'>"
        f"{m['dot']} {esc(m['label'])}</div>"
        f"<div style='color:#1F1A2E;margin-top:4px'>{esc(m['text'])}</div>"
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-top:12px'>"
        + "".join(
            f"<span class='dw-chip' style='{'border-color:' + STATUS_META[s]['color'] + ';color:' + STATUS_META[s]['color'] if s == status else 'opacity:.55'}'>"
            f"{STATUS_META[s]['dot']} {STATUS_META[s]['label']}</span>" for s in ("STABLE", "WARNING", "DRIFT"))
        + "</div></div>", unsafe_allow_html=True)

    recent = h.tail(config.ROLLING_WINDOW)
    prev = h.iloc[-2 * config.ROLLING_WINDOW:-config.ROLLING_WINDOW] if len(h) > config.ROLLING_WINDOW else h.iloc[0:0]
    acc_now = recent["correct"].mean() if len(recent) else None
    acc_prev = prev["correct"].mean() if len(prev) else None
    trend = "—"
    if acc_now is not None and acc_prev is not None:
        d = (acc_now - acc_prev) * 100
        trend = f"{'▲' if d >= 0 else '▼'} {abs(d):.1f} pts"

    c = st.columns(6)
    with c[0]:
        kpi("Drift detector", eng.detector_name, eng.monitor.backend)
    with c[1]:
        kpi("Model version", eng.version)
    with c[2]:
        kpi("Drift events", eng.n_drifts)
    with c[3]:
        kpi("Last drift", f"#{last['step']:,}" if last else "—",
            str(last["purchase_date"])[:10] if last else "No drift yet")
    with c[4]:
        kpi("Error rate", pct(1 - acc_now) if acc_now is not None else "—", f"Last {len(recent)} predictions",
            accent=m["color"])
    with c[5]:
        kpi("Accuracy trend", trend, "vs previous window")

    st.write("")
    if h.empty:
        empty_state("The detector has no data yet. Process some records from the sidebar.")
        return

    with st.container(border=True):
        st.markdown("#### Prediction error vs time")
        st.caption("Red ticks at the bottom are individual wrong predictions. Amber dots mark the detector's warning "
                   "zone. Red crosses mark confirmed concept drift, after which the model is retrained.")
        show(viz.error_timeline(h, eng.drift_events), "drift_err")

    st.markdown("#### Drift events")
    if not eng.drift_events:
        empty_state("No drift yet. Press Simulate fashion trend change, then keep processing records.")
    else:
        ev = pd.DataFrame(eng.drift_events)
        table = pd.DataFrame({
            "Event": ev["event_id"],
            "Time": "Record " + ev["step"].map("{:,}".format) + " (" + ev["purchase_date"].astype(str).str[:10] + ")",
            "Trend period": "Period " + ev["period"].astype(str) + ": " + ev["trend"],
            "Error rate": ev["error_rate"].astype(float) * 100,
            "Detected after": ev["detection_delay"].astype(str) + " records",
            "Status": "🔴 " + ev["status"],
            "Action": "✅ " + ev["action"] + " (" + ev["from_version"] + " → " + ev["to_version"] + ")",
        })
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "Error rate": st.column_config.ProgressColumn("Error rate", format="%.0f%%", min_value=0, max_value=100),
        })

    with st.expander(f"How {eng.detector_name} decides", icon=":material/functions:"):
        st.markdown(DETECTOR_INFO[eng.detector_name])
        if eng.detector_name == "DDM":
            st.latex(r"p_i = \frac{\text{errors}}{i},\qquad s_i = \sqrt{\frac{p_i(1-p_i)}{i}}")
            st.latex(r"\text{Warning if } p_i + s_i > p_{min} + 2\,s_{min}\qquad"
                     r"\text{Drift if } p_i + s_i > p_{min} + 3\,s_{min}")
            st.markdown(f"The detector waits for **{config.DDM_WARM_START}** records before judging, and is reset "
                        "after every adaptation so it learns the new model's normal error level.")
        st.caption(f"After every (re)training the detector is reset and calibrated with the model's out-of-fold "
                   f"validation errors ({len(eng.detector_prime)} values), so it knows the normal error level "
                   f"before live data arrives. Values seen since the last reset: {eng.monitor.n_seen:,}.")
