"""
DriftWear — Fashion category prediction with concept drift detection.

Run:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="DriftWear · Fashion Concept Drift", page_icon="🧵",
                   layout="wide", initial_sidebar_state="expanded")

from utils.state import drift_alert, init_state, sidebar_controls, stream_ticker  # noqa: E402
from utils.ui import inject_css  # noqa: E402
from views import (about, adaptation, dashboard, data_stream, drift_monitoring,  # noqa: E402
                   performance, prediction)

inject_css()
init_state()

with st.sidebar:
    st.markdown(
        "<div style='padding:4px 4px 10px'><div class='dw-display' style='font-family:Bricolage Grotesque,"
        "sans-serif;font-size:1.6rem;font-weight:800;color:#fff;letter-spacing:-.02em'>DriftWear</div>"
        "<div style='font-size:.82rem;color:#BDB4CF'>Fashion prediction that notices when trends change</div></div>",
        unsafe_allow_html=True,
    )

pages = [
    st.Page(dashboard.render, title="Dashboard", icon=":material/space_dashboard:", url_path="dashboard", default=True),
    st.Page(prediction.render, title="Prediction", icon=":material/styler:", url_path="prediction"),
    st.Page(drift_monitoring.render, title="Drift Monitoring", icon=":material/monitor_heart:", url_path="drift"),
    st.Page(performance.render, title="Model Performance", icon=":material/insights:", url_path="performance"),
    st.Page(data_stream.render, title="Data Stream", icon=":material/stream:", url_path="stream"),
    st.Page(adaptation.render, title="Model Adaptation", icon=":material/model_training:", url_path="adaptation"),
    st.Page(about.render, title="About Project", icon=":material/info:", url_path="about"),
]
nav = st.navigation(pages, position="sidebar")
sidebar_controls()
stream_ticker()

drift_alert()
nav.run()
