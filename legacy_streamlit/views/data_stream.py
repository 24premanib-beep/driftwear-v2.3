"""The live purchase stream: latest record, feed, upcoming queue, category mix."""
import pandas as pd
import streamlit as st

from src import config
from src.evaluation import add_rolling_columns
from utils import visualization as viz
from utils.charts import show
from utils.state import engine
from utils.ui import STATUS_META, badge_html, empty_state, esc, page_header, pct

FEATURE_COLS = ["Customer_ID", "Previous_Category", "Purchase_Frequency", "Recency", "Season",
                "Month", "Price", "Discount", "Customer_Preference"]


def _last_record_card(eng, h):
    last = h.iloc[-1]
    rec = eng.feature_row(last["record_id"])
    ok = bool(last["correct"])
    colour = "#0E8A6E" if ok else "#D12F4B"
    st.markdown(
        f"""<div class='dw-loop' style='border-top:4px solid {colour}'>
        <div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'>
          <div style='color:#6B6580;font-weight:600'>Record {int(last['step']):,} of the stream, customer
          {esc(rec['Customer_ID'])}, {esc(str(last['purchase_date'])[:16])}</div>
          <div>{badge_html(last['detector_status'])}</div>
        </div>
        <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-top:12px'>
          <div><div class='dw-note'>Model predicted</div>
               <div class='dw-display' style='font-size:1.9rem;font-weight:800'>{esc(last['predicted'])}</div>
               <div class='dw-note'>{last['confidence']:.0%} confidence, {esc(last['model_version'])}</div></div>
          <div><div class='dw-note'>Customer actually bought</div>
               <div class='dw-display' style='font-size:1.9rem;font-weight:800'>{esc(last['actual'])}</div>
               <div class='dw-note'>{esc(last['trend'])}</div></div>
          <div><div class='dw-note'>Result</div>
               <div class='dw-display' style='font-size:1.9rem;font-weight:800;color:{colour}'>
               {'✓ Correct' if ok else '✗ Wrong'}</div>
               <div class='dw-note'>sent to detector as {0 if ok else 1}</div></div>
          <div><div class='dw-note'>Rolling error / accuracy</div>
               <div class='dw-display' style='font-size:1.9rem;font-weight:800'>{pct(last['rolling_error'], 0)}</div>
               <div class='dw-note'>accuracy {pct(last['rolling_accuracy'], 0)}, {eng.n_drifts} drift events</div></div>
        </div>
        <div class='dw-note' style='margin-top:10px'>Inputs: {esc(rec['Customer_Preference'])} shopper,
        ₹{rec['Price']:,.0f} at {rec['Discount']:.0f}% off, {esc(rec['Season'])}, previously bought
        {esc(rec['Previous_Category'])}, {int(rec['Purchase_Frequency'])} orders, last one {int(rec['Recency'])} days ago.</div>
        </div>""", unsafe_allow_html=True)


def render():
    eng = engine()
    page_header("Data stream",
                "Purchases arrive one at a time in date order. Use the sidebar to process the next record, "
                "ten records, or start the live stream.")
    h = add_rolling_columns(eng.history_df)

    if h.empty:
        empty_state("Nothing processed yet. Press Next in the sidebar to send the first purchase through the model.")
    else:
        _last_record_card(eng, h)

    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown("#### Processed purchases")
        if not h.empty:
            feed = h.tail(25).iloc[::-1]
            feats = eng.dataset.loc[feed["record_id"], FEATURE_COLS].reset_index(drop=True)
            view = pd.concat([feed[["step", "purchase_date"]].reset_index(drop=True), feats,
                              feed[["predicted", "actual", "correct", "confidence", "detector_status",
                                    "model_version"]].reset_index(drop=True)], axis=1)
            view["correct"] = view["correct"].map({True: "✓", False: "✗"})
            view["detector_status"] = view["detector_status"].map(lambda s: f"{STATUS_META[s]['dot']} {STATUS_META[s]['label']}")
            view["purchase_date"] = view["purchase_date"].astype(str).str[:16]
            view["confidence"] = view["confidence"] * 100
            st.dataframe(view, hide_index=True, width="stretch", height=420, column_config={
                "step": "Record", "purchase_date": "Date", "Customer_ID": "Customer",
                "Previous_Category": "Previous", "Purchase_Frequency": "Freq.", "Customer_Preference": "Preference",
                "Price": st.column_config.NumberColumn("Price", format="₹%d"),
                "Discount": st.column_config.NumberColumn("Disc.", format="%d%%"),
                "predicted": "Predicted", "actual": "Actual", "correct": "OK",
                "confidence": st.column_config.NumberColumn("Conf.", format="%.0f%%"),
                "detector_status": "Detector", "model_version": "Model",
            })
    with c2:
        st.markdown("#### Up next")
        st.caption(f"Currently streaming: {eng.current_trend}" if not eng.finished else "Stream finished.")
        nxt = eng.upcoming(10)
        if nxt.empty:
            empty_state("No more records. Reset the simulation or generate a new dataset.")
        else:
            up = nxt[["Purchase_Date", "Customer_ID", "Customer_Preference", "Price", "Period"]].copy()
            up["Purchase_Date"] = up["Purchase_Date"].dt.strftime("%Y-%m-%d")
            st.dataframe(up, hide_index=True, width="stretch", height=390, column_config={
                "Purchase_Date": "Date", "Customer_ID": "Customer", "Customer_Preference": "Preference",
                "Price": st.column_config.NumberColumn("Price", format="₹%d"), "Period": "Trend period"})
            st.caption("The actual category stays hidden until the model has made its prediction.")

    if not h.empty:
        with st.container(border=True):
            st.markdown("#### What customers bought over time")
            st.caption("Share of each category among real purchases. A trend change shows up as a shift in colours.")
            show(viz.category_mix_over_time(h), "stream_mix")

    with st.expander("Dataset and saved files", icon=":material/folder_open:"):
        ds = eng.dataset
        st.markdown(f"**fashion_purchases.csv**: {len(ds):,} records from "
                    f"{ds['Purchase_Date'].min():%d %b %Y} to {ds['Purchase_Date'].max():%d %b %Y}. "
                    f"The first {eng.train_size} are historical data used to train v1.0. Seed {eng.dataset_seed}.")
        mix = pd.crosstab(ds["Trend"], ds["Target_Category"], normalize="index").reindex(
            columns=config.CATEGORIES, fill_value=0)
        mix = mix.reindex([p["name"] for p in config.TREND_PERIODS if p["name"] in mix.index] +
                          [i for i in mix.index if i not in [p["name"] for p in config.TREND_PERIODS]])
        st.dataframe((mix * 100).round(0).astype(int).astype(str) + "%", width="stretch")
        d1, d2, d3 = st.columns(3)
        for col, path, label in [(d1, config.DATASET_PATH, "Dataset"), (d2, config.PREDICTIONS_PATH, "Predictions log"),
                                 (d3, config.DRIFT_EVENTS_PATH, "Drift events")]:
            if path.exists():
                col.download_button(f"Download {label}", path.read_bytes(), file_name=path.name,
                                    mime="text/csv", icon=":material/download:")
