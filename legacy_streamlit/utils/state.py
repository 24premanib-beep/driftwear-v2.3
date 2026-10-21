"""Session state, stream controls and the drift alert shared by every page."""
from __future__ import annotations

import time

import streamlit as st

from src import config
from src.drift_detector import RIVER_AVAILABLE, available_detectors
from src.stream_engine import StreamEngine
from utils.ui import esc

SPEEDS = {"Slow (1 / tick)": 1, "Normal (5 / tick)": 5, "Fast (15 / tick)": 15}


def init_state() -> StreamEngine:
    ss = st.session_state
    if "engine" not in ss:
        try:
            with st.spinner("Preparing data and training model v1.0…"):
                ss.engine = StreamEngine.load_or_create()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not start the simulation: {exc}")
            st.stop()
    ss.setdefault("running", False)
    ss.setdefault("speed_label", "Normal (5 / tick)")
    ss.setdefault("pause_on_drift", True)
    ss.setdefault("drift_flash", None)       # latest drift event + adaptation for the alert
    ss.setdefault("flash_animate", False)
    ss.setdefault("skip_tick", False)
    return ss.engine


def engine() -> StreamEngine:
    return st.session_state.engine


# ---------------------------------------------------------------- actions
def run_batch(n: int) -> None:
    ss = st.session_state
    eng = engine()
    if eng.finished:
        ss.running = False
        st.toast("The stream has ended. Reset the simulation or generate a new dataset.", icon="🏁")
        return
    try:
        batch = eng.process_batch(n, stop_on_drift=ss.pause_on_drift or n > 1)
    except Exception as exc:  # noqa: BLE001
        ss.running = False
        st.toast(f"Processing stopped: {exc}", icon="❗")
        return
    if batch.drift_events:
        ev = batch.drift_events[-1]
        ss.drift_flash = {"event": ev, "adaptation": batch.adaptations[-1] if batch.adaptations else None}
        ss.flash_animate = True
        if ss.pause_on_drift:
            ss.running = False
    else:
        for a in batch.adaptations:
            st.toast(f"Model refreshed with more new-trend data: {a['from_version']} → {a['to_version']}", icon="🔁")
    if batch.finished:
        ss.running = False
        st.toast("All records processed — stream finished.", icon="🏁")


def _start():
    st.session_state.running = True


def _pause():
    st.session_state.running = False


def _step_one():
    run_batch(1)


def _step_ten():
    # 10 records, but stop right after a drift so the adaptation can be shown
    run_batch(10)


def _trend_change():
    info = engine().simulate_trend_change()
    st.toast(info["message"], icon="👗" if info["ok"] else "ℹ️")


def _reset():
    ss = st.session_state
    ss.running = False
    ss.drift_flash = None
    engine().reset()
    st.toast("Simulation reset — model v1.0 retrained on historical data.", icon="↺")


def _new_dataset():
    ss = st.session_state
    ss.running = False
    ss.drift_flash = None
    engine().generate_new_dataset()
    st.toast(f"New dataset generated (seed {engine().dataset_seed}).", icon="🎲")


def _detector_changed():
    engine().set_detector(st.session_state.detector_choice)
    st.toast(f"Drift detector switched to {st.session_state.detector_choice}.", icon="📡")


# ---------------------------------------------------------------- sidebar
def sidebar_controls() -> None:
    ss = st.session_state
    eng = engine()
    with st.sidebar:
        st.divider()
        st.markdown("**Data stream**")
        c1, c2 = st.columns(2)
        if ss.running:
            c1.button("Pause", icon=":material/pause:", on_click=_pause, key="btn_pause")
        else:
            c1.button("Start", icon=":material/play_arrow:", on_click=_start, type="primary",
                      disabled=eng.finished, key="btn_start")
        c2.button("Next", icon=":material/skip_next:", on_click=_step_one,
                  disabled=eng.finished, key="btn_next", help="Process the next record")
        st.button("Process 10 records", icon=":material/fast_forward:", on_click=_step_ten,
                  disabled=eng.finished, key="btn_ten")
        st.button("Simulate fashion trend change", icon=":material/checkroom:", on_click=_trend_change,
                  disabled=eng.finished, key="btn_trend",
                  help="Jump the stream to the next trend period: the purchase pattern changes from here on.")

        done = len(eng.history)
        total = len(eng.dataset) - eng.train_size
        st.progress(min(1.0, (eng.pointer - eng.train_size) / max(total, 1)),
                    text=f"{done:,} processed, {eng.remaining:,} left")
        if ss.running:
            st.caption("🟣 Streaming live…")

        with st.expander("Settings", icon=":material/tune:"):
            st.selectbox("Stream speed", list(SPEEDS), key="speed_label")
            st.toggle("Pause when drift is detected", key="pause_on_drift",
                      help="Keeps the drift + adaptation moment on screen during a demo.")
            opts = available_detectors()
            if "detector_choice" not in ss or ss.detector_choice not in opts:
                ss.detector_choice = eng.detector_name if eng.detector_name in opts else opts[0]
            st.selectbox("Drift detector", opts, key="detector_choice", on_change=_detector_changed)
            if not RIVER_AVAILABLE:
                st.caption("River is not installed, so a built-in DDM with the same maths is used. "
                           "Run `pip install river` to enable ADWIN and Page-Hinkley.")

        c3, c4 = st.columns(2)
        c3.button("Reset", icon=":material/restart_alt:", on_click=_reset, key="btn_reset",
                  help="Clear logs and retrain v1.0 on the same dataset")
        c4.button("New data", icon=":material/casino:", on_click=_new_dataset, key="btn_new",
                  help="Generate a fresh synthetic dataset and start over")


def stream_ticker() -> None:
    """Auto-process records while the stream is running (a timed fragment)."""
    ss = st.session_state
    if not ss.running:
        return
    ss.skip_tick = True  # the fragment also executes once during the full run – skip that one

    def _tick():
        if ss.skip_tick:
            ss.skip_tick = False
            return
        if ss.running:
            run_batch(SPEEDS.get(ss.speed_label, 5))
            st.rerun()

    with st.sidebar:
        st.fragment(run_every=0.9)(_tick)()


# ---------------------------------------------------------------- alert
def drift_alert() -> None:
    """Prominent 'Concept drift detected → Adapting → Updated' banner after a drift."""
    ss = st.session_state
    flash = ss.get("drift_flash")
    if not flash:
        return
    ev, ad = flash["event"], flash["adaptation"]
    err = "—" if ev.get("error_rate") is None else f"{ev['error_rate']:.0%}"

    if ss.flash_animate:
        ss.flash_animate = False
        with st.status("⚠️ Concept drift detected", expanded=True, state="running") as s:
            st.write(f"Error rate since the trend changed: **{err}** (detected by {esc(ev['detector'])})")
            time.sleep(0.6)
            st.write(f"🔄 Adapting model… selecting the last **{ev['window_size']}** records")
            time.sleep(0.8)
            st.write(f"🧠 Retraining Random Forest on the new pattern")
            time.sleep(0.6)
            st.write(f"✅ Model updated: **{ev['from_version']} → {ev['to_version']}**")
            s.update(label=f"Model adapted: {ev['from_version']} → {ev['to_version']}", state="complete",
                     expanded=False)

    st.markdown(
        f"""<div class='dw-alert' role='alert'>
        <div class='a-title'>⚠️ Concept drift detected</div>
        <div class='a-body'>{esc(ev['event_id'])} at record {ev['step']:,}: the model was wrong on {err}
        of purchases after the trend changed. It was retrained on the {ev['window_size']} most recent records.</div>
        <div class='dw-flow'>
          <span class='dw-chip'>Errors increased</span>
          <span class='dw-chip'>{esc(ev['detector'])} confirmed drift</span>
          <span class='dw-chip'>🔄 Adaptation triggered</span>
          <span class='dw-chip' style='border-color:#0E8A6E;color:#0E8A6E'>Model updated {esc(ev['from_version'])} → {esc(ev['to_version'])}</span>
        </div></div>""",
        unsafe_allow_html=True,
    )
    if st.button("Dismiss alert", icon=":material/close:", key="dismiss_flash"):
        ss.drift_flash = None
        st.rerun()
