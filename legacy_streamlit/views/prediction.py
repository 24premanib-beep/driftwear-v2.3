"""Predict the next clothing category for one customer."""
import re

import streamlit as st

from src import config
from src.data_generator import price_band
from src.model import feature_importance, predict_record
from utils import visualization as viz
from utils.charts import show
from utils.state import engine
from utils.ui import STATUS_META, badge_html, esc, page_header

CUSTOMER_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
AUTO = "Auto (from month)"


def _fill_from_latest():
    eng = engine()
    rec = eng.feature_row(eng.history[-1]["record_id"]) if eng.history else eng.dataset.iloc[eng.pointer - 1].to_dict()
    ss = st.session_state
    ss.p_cust = str(rec["Customer_ID"])
    ss.p_prev = rec["Previous_Category"]
    ss.p_freq = int(rec["Purchase_Frequency"])
    ss.p_rec = int(rec["Recency"])
    ss.p_month = int(rec["Month"])
    ss.p_season = rec["Season"]
    ss.p_price = float(rec["Price"])
    ss.p_disc = int(rec["Discount"])
    ss.p_pref = rec["Customer_Preference"]


def _style_hint(category: str, preference: str, price: float) -> str:
    options = config.STYLE_EXAMPLES[category]
    idx = (config.PREFERENCES.index(preference) + price_band(price)) % len(options)
    return options[idx]


def render():
    eng = engine()
    page_header("Predict the next purchase",
                f"Uses the live model ({eng.version}). After a drift the same inputs can give a different answer, "
                "because the model has learned the new trend.")

    ss = st.session_state
    defaults = dict(p_cust="C1001", p_prev="Tops", p_freq=6, p_rec=21, p_month=4, p_season=AUTO,
                    p_price=1499.0, p_disc=10, p_pref="Casual")
    for k, v in defaults.items():
        ss.setdefault(k, v)

    left, right = st.columns([1, 1.15], gap="large")
    with left:
        with st.container(border=True):
            st.button("Fill from latest stream record", icon=":material/input:", on_click=_fill_from_latest)
            with st.form("predict_form", border=False):
                st.text_input("Customer ID", key="p_cust", max_chars=20)
                a, b = st.columns(2)
                a.selectbox("Previous category", config.CATEGORIES, key="p_prev")
                b.selectbox("Customer preference", config.PREFERENCES, key="p_pref")
                a.number_input("Purchase frequency (orders so far)", 1, 500, key="p_freq")
                b.number_input("Recency (days since last order)", 0, 730, key="p_rec")
                a.selectbox("Month", list(range(1, 13)), key="p_month",
                            format_func=lambda m: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                                                   "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1])
                b.selectbox("Season", [AUTO] + config.SEASONS, key="p_season")
                a.number_input("Price (₹)", 50.0, 50000.0, step=50.0, key="p_price")
                b.slider("Discount (%)", 0, 90, key="p_disc")
                submitted = st.form_submit_button("Predict category", type="primary", icon=":material/auto_awesome:")

        if submitted:
            cust = ss.p_cust.strip()
            if not CUSTOMER_RE.match(cust):
                st.error("Customer ID can use letters, numbers, - and _ only (up to 20 characters).")
            else:
                season = config.MONTH_TO_SEASON[ss.p_month] if ss.p_season == AUTO else ss.p_season
                record = {
                    "Customer_ID": cust, "Previous_Category": ss.p_prev,
                    "Purchase_Frequency": ss.p_freq, "Recency": ss.p_rec, "Season": season,
                    "Month": ss.p_month, "Price": ss.p_price, "Discount": float(ss.p_disc),
                    "Customer_Preference": ss.p_pref,
                }
                try:
                    pred, conf, probs = predict_record(eng.model, record)
                    base_pred, base_conf, _ = predict_record(eng.baseline_model, record)
                    ss.pred_result = dict(record=record, pred=pred, conf=conf, probs=probs,
                                          base_pred=base_pred, base_conf=base_conf,
                                          version=eng.version, status=eng.status)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Prediction failed: {exc}")

    with right:
        res = ss.get("pred_result")
        if not res:
            st.markdown(
                "<div class='dw-result'><div class='r-label'>Predicted next purchase</div>"
                "<div class='r-cat' style='color:#6B6580'>Waiting</div>"
                "<div class='r-style'>Fill in the form and press Predict category</div></div>",
                unsafe_allow_html=True)
            return
        rec = res["record"]
        hint = _style_hint(res["pred"], rec["Customer_Preference"], rec["Price"])
        m = STATUS_META[res["status"]]
        known = (eng.dataset["Customer_ID"] == rec["Customer_ID"]).sum()
        st.markdown(
            f"<div class='dw-result'><div class='r-label'>Predicted next purchase for {esc(rec['Customer_ID'])}</div>"
            f"<div class='r-cat'>{esc(res['pred'])}</div>"
            f"<div class='r-style'>Style idea: {esc(hint)}</div>"
            f"<div class='r-meta'><span>Confidence <b>{res['conf']:.0%}</b></span>"
            f"<span>Model <b>{esc(res['version'])}</b></span>"
            f"<span>Drift status <b style='color:{m['color']};filter:brightness(1.6)'>{m['dot']} {esc(m['label'])}</b></span>"
            f"</div></div>", unsafe_allow_html=True)
        st.caption(("Known customer with " + f"{known} purchases in the dataset. ") if known else "New customer ID. ")
        if res["version"] != "v1.0":
            same = res["base_pred"] == res["pred"]
            st.info(f"The original v1.0 model would predict **{res['base_pred']}** ({res['base_conf']:.0%}). "
                    + ("Both models agree." if same else "The adapted model disagrees because the trend has changed."))
        st.markdown("##### Probability for each category")
        st.caption("Real Random Forest probabilities: the average vote of 100 decision trees.")
        show(viz.probability_bars(res["probs"], height=260), "pred_prob")

    st.markdown("##### What the current model relies on")
    st.caption(f"Feature importance of {eng.version}, grouped back to the form inputs.")
    c1, c2 = st.columns([1.2, 1])
    with c1:
        show(viz.importance_bars(feature_importance(eng.model), height=300), "pred_imp")
    with c2:
        st.markdown(f"Drift status right now: {badge_html(eng.status)}", unsafe_allow_html=True)
        st.markdown(
            "The synthetic trends mainly depend on **customer preference** and **price**, so those "
            "usually dominate. After an adaptation, compare this chart: the model keeps the same inputs "
            "but learns a different mapping to categories — that is concept drift.")
