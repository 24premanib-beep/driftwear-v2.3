"""Shared look & feel: CSS, cards, badges and the drift-loop ribbon."""
from __future__ import annotations

import html

import streamlit as st

# ---- design tokens -----------------------------------------------------------
INK = "#1F1A2E"
MUTED = "#6B6580"
SURFACE = "#FFFFFF"
BG = "#F4F3F8"
LINE = "#E4E0EC"
ORCHID = "#A3246A"
LILAC = "#EFE8F6"
STABLE = "#0E8A6E"
WARN = "#B7790F"
DRIFT = "#D12F4B"

STATUS_META = {
    "STABLE": {"label": "Stable", "dot": "🟢", "color": STABLE, "bg": "#E3F4EF",
               "text": "No significant drift detected."},
    "WARNING": {"label": "Possible change", "dot": "🟡", "color": WARN, "bg": "#FBF1DC",
                "text": "Possible change detected — watching closely."},
    "DRIFT": {"label": "Concept drift detected", "dot": "🔴", "color": DRIFT, "bg": "#FBE4E8",
              "text": "Concept Drift Detected — Model Adaptation Triggered."},
}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Manrope:wght@400;500;600;700&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, p, label, input, textarea, button {{
  font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
h1, h2, h3, h4, .dw-display {{
  font-family: 'Bricolage Grotesque', 'Manrope', system-ui, sans-serif !important;
  letter-spacing: -0.02em; color: {INK};
}}
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1320px; }}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span {{ font-weight: 600; }}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"],
[data-testid="stSidebar"] a[aria-current="page"] {{ background: rgba(255,255,255,.10); border-radius: 10px; }}
[data-testid="stSidebar"] .stButton button {{
  background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.14);
  border-radius: 10px; font-weight: 600; width: 100%;
}}
[data-testid="stSidebar"] .stButton button:hover {{ border-color: #E07BB2; color: #fff; }}
[data-testid="stSidebar"] .stButton button[kind="primary"] {{ background: {ORCHID}; border-color: {ORCHID}; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.12); }}
.stButton button:focus-visible {{ outline: 3px solid #E07BB2; outline-offset: 2px; }}

/* page header */
.dw-head {{ margin-bottom: 1.2rem; }}
.dw-head h1 {{ font-size: 2.3rem; font-weight: 800; margin: 0; line-height: 1.1; }}
.dw-head p {{ color: {MUTED}; margin: .35rem 0 0; max-width: 70ch; font-size: 1rem; }}

/* KPI tiles */
.dw-kpi {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px;
  padding: 16px 18px 14px; height: 100%; }}
.dw-kpi .k-label {{ color: {MUTED}; font-size: .82rem; font-weight: 600; }}
.dw-kpi .k-value {{ font-family: 'Bricolage Grotesque', sans-serif; font-size: 1.75rem;
  font-weight: 700; color: {INK}; line-height: 1.2; margin-top: 4px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }}
.dw-kpi .k-sub {{ color: {MUTED}; font-size: .8rem; margin-top: 2px; }}
.dw-kpi.accent {{ border-top: 3px solid var(--acc, {ORCHID}); }}

/* status badge */
.dw-badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px;
  border-radius: 999px; font-size: .8rem; font-weight: 700; }}

/* the drift loop ribbon */
.dw-loop {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 20px;
  padding: 18px 20px; margin-bottom: 18px; }}
.dw-loop-top {{ display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
.dw-loop-top .state {{ font-family: 'Bricolage Grotesque', sans-serif; font-size: 1.5rem; font-weight: 800; }}
.dw-loop-top .meta {{ color: {MUTED}; font-size: .9rem; }}
.dw-stages {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; position: relative; }}
.dw-stage {{ position: relative; padding: 10px 12px; border-radius: 12px; text-align: left; }}
.dw-stage .s-name {{ font-weight: 700; font-size: .95rem; color: {INK}; }}
.dw-stage .s-note {{ font-size: .78rem; color: {MUTED}; }}
.dw-stage .s-bar {{ height: 6px; border-radius: 6px; background: {LINE}; margin-bottom: 8px; }}
.dw-stage.on .s-bar {{ background: var(--acc); }}
.dw-stage.live .s-bar {{ background: var(--acc); animation: dwpulse 1.4s ease-in-out infinite; }}
@keyframes dwpulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
@media (prefers-reduced-motion: reduce) {{ .dw-stage.live .s-bar {{ animation: none; }} }}
@media (max-width: 760px) {{ .dw-stages {{ grid-template-columns: repeat(2, 1fr); }} }}

/* drift alert */
.dw-alert {{ border-radius: 18px; padding: 18px 22px; margin-bottom: 16px;
  background: linear-gradient(120deg, #FBE4E8 0%, #FFFFFF 70%); border: 1px solid #F2B8C3; }}
.dw-alert .a-title {{ font-family: 'Bricolage Grotesque', sans-serif; font-size: 1.6rem;
  font-weight: 800; color: {DRIFT}; }}
.dw-alert .a-body {{ color: {INK}; margin-top: 4px; }}
.dw-flow {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
.dw-chip {{ background: #fff; border: 1px solid {LINE}; border-radius: 999px; padding: 4px 12px;
  font-size: .82rem; font-weight: 600; }}

/* prediction result */
.dw-result {{ background: {INK}; color: #fff; border-radius: 22px; padding: 26px 28px; }}
.dw-result .r-label {{ color: #CFC6E0; font-size: .9rem; font-weight: 600; }}
.dw-result .r-cat {{ font-family: 'Bricolage Grotesque', sans-serif; font-size: 3.2rem;
  font-weight: 800; line-height: 1; margin: 6px 0 4px; letter-spacing: -0.03em; }}
.dw-result .r-style {{ color: #F2B8D6; font-weight: 600; }}
.dw-result .r-meta {{ display: flex; gap: 18px; flex-wrap: wrap; margin-top: 16px; color: #CFC6E0; font-size: .88rem; }}
.dw-result .r-meta b {{ color: #fff; }}

/* pipeline */
.dw-pipe {{ display: flex; flex-direction: column; gap: 0; }}
.dw-pipe .p-step {{ display: grid; grid-template-columns: 34px 1fr; gap: 12px; align-items: start; }}
.dw-pipe .p-num {{ width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
  font-weight: 700; font-size: .85rem; background: {LINE}; color: {MUTED}; }}
.dw-pipe .p-step.done .p-num {{ background: {STABLE}; color: #fff; }}
.dw-pipe .p-step.alert .p-num {{ background: {DRIFT}; color: #fff; }}
.dw-pipe .p-body {{ padding-bottom: 14px; border-left: 2px solid {LINE}; margin-left: -29px;
  padding-left: 29px; }}
.dw-pipe .p-step:last-child .p-body {{ border-left-color: transparent; }}
.dw-pipe .p-title {{ font-weight: 700; color: {INK}; line-height: 30px; }}
.dw-pipe .p-desc {{ color: {MUTED}; font-size: .85rem; margin-top: -4px; }}

/* version transition */
.dw-version {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
.dw-version .v {{ font-family: 'Bricolage Grotesque', sans-serif; font-size: 2.4rem; font-weight: 800; }}
.dw-version .v.old {{ color: #A9A3B8; text-decoration: line-through; text-decoration-thickness: 2px; }}
.dw-version .arrow {{ font-size: 1.6rem; color: {MUTED}; }}

.dw-note {{ color: {MUTED}; font-size: .85rem; }}
.dw-empty {{ border: 1.5px dashed {LINE}; border-radius: 14px; padding: 22px; color: {MUTED};
  text-align: center; background: rgba(255,255,255,.5); }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 16px; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def page_header(title: str, subtitle: str = "") -> None:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f"<div class='dw-head'><h1>{esc(title)}</h1>{sub}</div>", unsafe_allow_html=True)


def kpi(label: str, value, sub: str = "", accent: str | None = None) -> None:
    style = f" style='--acc:{accent}'" if accent else ""
    cls = "dw-kpi accent" if accent else "dw-kpi"
    st.markdown(
        f"<div class='{cls}'{style}><div class='k-label'>{esc(label)}</div>"
        f"<div class='k-value' title='{esc(value)}'>{esc(value)}</div>"
        f"<div class='k-sub'>{esc(sub)}</div></div>",
        unsafe_allow_html=True,
    )


def badge_html(status: str) -> str:
    m = STATUS_META.get(status, STATUS_META["STABLE"])
    return (f"<span class='dw-badge' style='background:{m['bg']};color:{m['color']}'>"
            f"{m['dot']} {esc(m['label'])}</span>")


def pct(x, digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def empty_state(text: str) -> None:
    st.markdown(f"<div class='dw-empty'>{esc(text)}</div>", unsafe_allow_html=True)


def drift_loop(engine, running: bool) -> None:
    """The signature element: Learn → Predict → Monitor → Detect → Adapt, lit by real state."""
    status = engine.status
    m = STATUS_META[status]
    n = len(engine.history)
    last_event = engine.drift_events[-1] if engine.drift_events else None
    recent_adapt = last_event is not None and n - 1 - int(last_event["step"]) < 25

    if n == 0:
        headline, acc = "Model v1.0 trained — waiting for data", ORCHID
    elif recent_adapt:
        headline, acc = f"Adapted to the new trend, now running {engine.version}", STABLE
    else:
        headline, acc = m["label"], m["color"]

    on = {"learn": True, "predict": n > 0, "monitor": n > 0,
          "detect": status != "STABLE" or recent_adapt, "adapt": recent_adapt}
    notes = {
        "learn": f"{engine.version} on {engine.adaptations[-1]['records_used']} records",
        "predict": f"{n:,} predictions",
        "monitor": f"{engine.detector_name} on error stream",
        "detect": {"STABLE": "No drift", "WARNING": "Possible change",
                   "DRIFT": "Drift!"}[status] if not recent_adapt else f"{last_event['event_id']} confirmed",
        "adapt": (f"{last_event['from_version']} → {last_event['to_version']}"
                  if last_event else "Not needed yet"),
    }
    names = [("learn", "Learn"), ("predict", "Predict"), ("monitor", "Monitor"),
             ("detect", "Detect drift"), ("adapt", "Adapt")]
    stage_color = {"learn": ORCHID, "predict": ORCHID, "monitor": ORCHID,
                   "detect": WARN if status == "WARNING" and not recent_adapt else DRIFT,
                   "adapt": STABLE}
    cells = []
    for key, name in names:
        cls = "dw-stage"
        if on[key]:
            cls += " on"
            if running and key in ("predict", "monitor"):
                cls += " live"
        cells.append(
            f"<div class='{cls}' style='--acc:{stage_color[key]}'><div class='s-bar'></div>"
            f"<div class='s-name'>{name}</div><div class='s-note'>{esc(notes[key])}</div></div>"
        )
    meta = (f"Now streaming <b>{esc(engine.current_trend)}</b>, "
            f"{engine.remaining:,} records left" if not engine.finished else "Stream finished")
    st.markdown(
        f"<div class='dw-loop'><div class='dw-loop-top'>"
        f"<div class='state' style='color:{acc}'>{esc(headline)}</div>"
        f"<div class='meta'>{meta}</div></div>"
        f"<div class='dw-stages'>{''.join(cells)}</div></div>",
        unsafe_allow_html=True,
    )
