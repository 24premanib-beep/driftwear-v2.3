"""Adaptation pipeline, version transitions and adaptation history."""
import pandas as pd
import streamlit as st

from src import config
from utils import visualization as viz
from utils.charts import show
from utils.state import engine
from utils.ui import empty_state, esc, kpi, page_header, pct

PIPELINE = [
    ("Prediction", "The current model predicts every incoming purchase."),
    ("Performance monitoring", "Each result becomes 0 (correct) or 1 (wrong)."),
    ("Drift detection", "The detector watches the error stream for a significant change."),
    ("Drift confirmed", "Error rose past the drift threshold."),
    ("Recent data selected", "Records after the estimated change point form the training window."),
    ("Model retraining", "A new Random Forest is trained on that window only."),
    ("Updated model", "Saved with joblib and given a new version number."),
    ("New predictions", "The stream continues with the adapted model; the detector restarts."),
]


def _pipeline_html(eng) -> str:
    n = len(eng.history)
    has_drift = bool(eng.drift_events)
    states = []
    for i, _ in enumerate(PIPELINE):
        if i < 2:
            states.append("done" if n else "")
        elif i == 2:
            states.append("alert" if eng.status != "STABLE" and not has_drift else ("done" if n else ""))
        elif i == 3:
            states.append("alert" if has_drift else "")
        else:
            states.append("done" if has_drift else "")
    last = eng.drift_events[-1] if has_drift else None
    extra = {
        3: f"{last['event_id']} at record {last['step']:,}" if last else "",
        4: f"{last['window_size']} records selected" if last else "",
        6: f"{last['from_version']} → {last['to_version']}" if last else "",
    }
    rows = []
    for i, ((title, desc), stt) in enumerate(zip(PIPELINE, states)):
        mark = "✓" if stt == "done" else ("!" if stt == "alert" else str(i + 1))
        note = f" <b>{esc(extra[i])}</b>" if extra.get(i) else ""
        rows.append(f"<div class='p-step {stt}'><div class='p-num'>{mark}</div><div class='p-body'>"
                    f"<div class='p-title'>{esc(title)}</div><div class='p-desc'>{esc(desc)}{note}</div></div></div>")
    return f"<div class='dw-pipe'>{''.join(rows)}</div>"


def render():
    eng = engine()
    page_header("Model adaptation",
                "When drift is confirmed the model retrains on recent data only, then keeps refreshing "
                "itself as more of the new trend arrives.")
    ads = eng.adaptations
    drift_ads = [a for a in ads if a["type"] == "Drift adaptation"]
    refresh_ads = [a for a in ads if a["type"] == "Scheduled refresh"]

    c = st.columns(4)
    with c[0]:
        kpi("Adaptations", len(ads) - 1, "after initial training")
    with c[1]:
        kpi("Triggered by drift", len(drift_ads), "major version bumps", accent="#D12F4B")
    with c[2]:
        kpi("Refreshes", len(refresh_ads), "minor bumps with more new-trend data", accent="#0E8A6E")
    with c[3]:
        kpi("Current version", eng.version, "saved as models/model.pkl")

    st.write("")
    left, right = st.columns([1, 1.3], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Adaptation pipeline")
            st.markdown(_pipeline_html(eng), unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            st.markdown("#### Latest drift adaptation")
            if not drift_ads:
                empty_state("No drift adaptation yet. The model is still v1.0, trained on "
                            f"{eng.train_size} historical records.")
            else:
                a = drift_ads[-1]
                ev = next((e for e in eng.drift_events if e["event_id"] == a["trigger"]), {})
                st.markdown(f"<div class='dw-version'><span class='v old'>{esc(a['from_version'])}</span>"
                            f"<span class='arrow'>→</span><span class='v' style='color:#0E8A6E'>"
                            f"{esc(a['to_version'])}</span></div>", unsafe_allow_html=True)
                st.caption(f"Adapted at {a['timestamp']} (stream record {a['step']:,}, "
                           f"purchase date {str(a['purchase_date'])[:10]})")
                x1, x2, x3 = st.columns(3)
                with x1:
                    kpi("Before adaptation", pct(a["accuracy_before"]), "old model after trend change",
                        accent="#D12F4B")
                with x2:
                    kpi("After adaptation", pct(a["accuracy_after"]),
                        f"next {config.PERF_EVAL_WINDOW} records" if a["accuracy_after"] is not None
                        else "still collecting", accent="#0E8A6E")
                with x3:
                    kpi("Data used", f"{a['records_used']} rec.", f"records {a['window_start']:,}–{a['window_end']:,}")
                st.markdown(f"**Why this window?** The error sequence jumped at record "
                            f"{ev.get('change_point_step', a['window_start']):,}, so only records from there on "
                            f"reflect the new trend ({esc(a['data_period'])}).")
                later = [r for r in refresh_ads if r["step"] > a["step"]]
                if later:
                    st.markdown("**Kept learning:** " + ", ".join(
                        f"{r['to_version']} with {r['records_used']} records" for r in later))

    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("#### Model versions over the stream")
            show(viz.version_history(ads, len(eng.history)), "adapt_ver")
    with c2:
        with st.container(border=True):
            st.markdown("#### Performance before vs after")
            done = [e for e in eng.drift_events if e.get("accuracy_after") is not None]
            if done:
                show(viz.before_after_bars(done, height=300), "adapt_ba")
            else:
                empty_state("Appears after the first adaptation has been evaluated.")

    st.markdown("#### Adaptation history")
    table = pd.DataFrame(ads).reindex(columns=["to_version", "from_version", "type", "trigger", "step", "records_used",
                               "data_period", "train_accuracy", "accuracy_before", "accuracy_after",
                               "timestamp"])
    table = table.iloc[::-1].copy()
    for col in ("train_accuracy", "accuracy_before", "accuracy_after"):
        if col in table:
            table[col] = table[col].map(lambda v: pct(v) if pd.notna(v) else "—")
    if "step" in table:
        table["step"] = table["step"].map(lambda s: "historical" if s < 0 else f"{int(s):,}")
    if "trigger" in table:
        table["trigger"] = table["trigger"].fillna("—")
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "to_version": "Version", "from_version": "From", "type": "Type", "trigger": "Trigger",
        "step": "At record", "records_used": "Records used", "data_period": "Data from",
        "train_accuracy": "Train acc.", "accuracy_before": "Before", "accuracy_after": "After",
        "timestamp": "Timestamp"})
    archived = sorted(p.name for p in config.ARCHIVE_DIR.glob("*.pkl"))
    st.caption("Saved model files: " + ", ".join(archived) if archived else "No archived models yet.")
