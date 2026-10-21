"""Plotly charts used across the dashboard (one function per chart)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src import config
from utils.ui import DRIFT, INK, LINE, MUTED, ORCHID, STABLE, WARN

CATEGORY_COLORS = {
    "Tops": "#7A3E9D", "Bottoms": "#2F6FD0", "Dresses": "#E06C9F",
    "Footwear": "#3AA99F", "Outerwear": "#A67C52", "Accessories": "#C9A227",
}
PERIOD_TINTS = ["rgba(122,62,157,0.05)", "rgba(47,111,208,0.06)", "rgba(58,169,159,0.07)"]


def _style(fig: go.Figure, height: int = 340, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Manrope, system-ui, sans-serif", color=INK, size=12),
        hoverlabel=dict(font_family="Manrope, sans-serif"),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=False, linecolor=LINE, tickcolor=LINE, zeroline=False)
    fig.update_yaxes(gridcolor="#EEEAF3", zeroline=False)
    return fig


def _period_bands(fig: go.Figure, h: pd.DataFrame) -> None:
    """Shade the stream by trend period so drift lines have context."""
    if h.empty:
        return
    change = h["period"].ne(h["period"].shift()).to_numpy()
    starts = h.loc[change, ["step", "period", "trend"]].to_dict("records")
    last = int(h["step"].iloc[-1])
    for i, s in enumerate(starts):
        end = starts[i + 1]["step"] if i + 1 < len(starts) else last + 1
        fig.add_vrect(x0=s["step"] - 0.5, x1=end - 0.5, line_width=0, layer="below",
                      fillcolor=PERIOD_TINTS[(int(s["period"]) - 1) % 3])
        fig.add_annotation(x=s["step"], y=1.0, yref="paper", xanchor="left", yanchor="top",
                           text=f"P{s['period']}: {s['trend']}", showarrow=False,
                           font=dict(size=10, color=MUTED))


def _drift_lines(fig: go.Figure, events: list[dict]) -> None:
    for e in events:
        fig.add_vline(x=e["step"], line=dict(color=DRIFT, width=2, dash="dot"))
        fig.add_annotation(x=e["step"], y=0.9, yref="paper", text=f"⚠ {e['event_id']}",
                           showarrow=False, xanchor="left", font=dict(color=DRIFT, size=11),
                           bgcolor="rgba(255,255,255,.85)")


# ------------------------------------------------------------------ timelines
def accuracy_timeline(h: pd.DataFrame, events: list[dict], height: int = 360) -> go.Figure:
    fig = go.Figure()
    _period_bands(fig, h)
    fig.add_trace(go.Scatter(x=h["step"], y=h["baseline_rolling_accuracy"], name="Static model (v1.0, never updated)",
                             line=dict(color="#A9A3B8", width=2, dash="dash"),
                             hovertemplate="Step %{x}<br>Static accuracy %{y:.0%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=h["step"], y=h["rolling_accuracy"], name="Adaptive model",
                             line=dict(color=ORCHID, width=3),
                             customdata=h[["model_version"]],
                             hovertemplate="Step %{x}<br>Accuracy %{y:.0%}<br>%{customdata[0]}<extra></extra>"))
    _drift_lines(fig, events)
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%", title=f"Rolling accuracy ({config.ROLLING_WINDOW})")
    fig.update_xaxes(title="Records processed")
    return _style(fig, height)


def error_timeline(h: pd.DataFrame, events: list[dict], height: int = 380) -> go.Figure:
    fig = go.Figure()
    _period_bands(fig, h)
    fig.add_trace(go.Scatter(x=h["step"], y=h["rolling_error"], name="Prediction error (rolling)",
                             line=dict(color=INK, width=2.5), fill="tozeroy",
                             fillcolor="rgba(31,26,46,0.06)",
                             hovertemplate="Step %{x}<br>Error %{y:.0%}<extra></extra>"))
    warn = h[h["detector_status"] == "WARNING"]
    if not warn.empty:
        fig.add_trace(go.Scatter(x=warn["step"], y=warn["rolling_error"], mode="markers",
                                 name="Possible change (warning)",
                                 marker=dict(color=WARN, size=7, symbol="circle"),
                                 hovertemplate="Warning at step %{x}<extra></extra>"))
    wrong = h[~h["correct"].astype(bool)]
    fig.add_trace(go.Scatter(x=wrong["step"], y=[-0.04] * len(wrong), mode="markers",
                             name="Wrong prediction", marker=dict(color=DRIFT, size=4, symbol="line-ns-open"),
                             hovertemplate="Wrong at step %{x}<extra></extra>"))
    if events:
        ev = pd.DataFrame(events)
        y = h.set_index("step").loc[ev["step"], "rolling_error"].to_numpy()
        fig.add_trace(go.Scatter(x=ev["step"], y=y, mode="markers+text", name="Concept drift detected",
                                 marker=dict(color=DRIFT, size=16, symbol="x", line=dict(width=1, color="#fff")),
                                 text=ev["event_id"], textposition="top center",
                                 textfont=dict(color=DRIFT),
                                 hovertemplate="%{text} at step %{x}<extra></extra>"))
    _drift_lines(fig, events)
    fig.update_yaxes(range=[-0.08, 1.05], tickformat=".0%", title="Error rate")
    fig.update_xaxes(title="Records processed")
    return _style(fig, height)


def drift_timeline(h: pd.DataFrame, events: list[dict], adaptations: list[dict],
                   trend_changes: list[dict], height: int = 250) -> go.Figure:
    lanes = ["Trend change", "Possible change", "Drift detected", "Model updated"]
    fig = go.Figure()
    if trend_changes:
        tc = pd.DataFrame(trend_changes)
        fig.add_trace(go.Scatter(x=tc["step"], y=["Trend change"] * len(tc), mode="markers",
                                 marker=dict(symbol="star", size=16, color=ORCHID), name="Simulated trend change",
                                 text=tc["to_trend"], hovertemplate="Step %{x}<br>→ %{text}<extra></extra>"))
    if not h.empty:
        natural = h[h["period"].ne(h["period"].shift()) & (h["step"] > 0)]
        injected = {t["step"] for t in trend_changes}
        natural = natural[~natural["step"].isin(injected)]
        if not natural.empty:
            fig.add_trace(go.Scatter(x=natural["step"], y=["Trend change"] * len(natural), mode="markers",
                                     marker=dict(symbol="star-open", size=14, color=ORCHID),
                                     name="Natural trend change", text=natural["trend"],
                                     hovertemplate="Step %{x}<br>→ %{text}<extra></extra>"))
        warn = h[h["detector_status"] == "WARNING"]
        fig.add_trace(go.Scatter(x=warn["step"], y=["Possible change"] * len(warn), mode="markers",
                                 marker=dict(size=7, color=WARN, opacity=.7), name="Warning",
                                 hovertemplate="Step %{x}<extra></extra>"))
    if events:
        ev = pd.DataFrame(events)
        fig.add_trace(go.Scatter(x=ev["step"], y=["Drift detected"] * len(ev), mode="markers+text",
                                 marker=dict(symbol="x", size=16, color=DRIFT), text=ev["event_id"],
                                 textposition="top center", name="Drift",
                                 hovertemplate="%{text} at step %{x}<extra></extra>"))
    ad = [a for a in adaptations if a.get("step", -1) >= 0]
    if ad:
        ad = pd.DataFrame(ad)
        fig.add_trace(go.Scatter(x=ad["step"], y=["Model updated"] * len(ad), mode="markers+text",
                                 marker=dict(symbol="diamond", size=12,
                                             color=[STABLE if t == "Drift adaptation" else "#7FC8B5" for t in ad["type"]]),
                                 text=ad["to_version"], textposition="bottom center", name="Adaptation",
                                 hovertemplate="%{text} at step %{x}<extra></extra>"))
    fig.update_yaxes(categoryorder="array", categoryarray=lanes[::-1], showgrid=False)
    fig.update_xaxes(title="Records processed", range=[-5, max(len(h), 10) + 5])
    return _style(fig, height, legend=False)


# ------------------------------------------------------------------ categories
def category_mix_over_time(h: pd.DataFrame, bin_size: int = 50, height: int = 320) -> go.Figure:
    d = h.copy()
    d["bin"] = (d["step"] // bin_size) * bin_size
    mix = pd.crosstab(d["bin"], d["actual"], normalize="index").reindex(columns=config.CATEGORIES, fill_value=0)
    fig = go.Figure()
    for c in config.CATEGORIES:
        fig.add_trace(go.Scatter(x=mix.index, y=mix[c], name=c, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=CATEGORY_COLORS[c]),
                                 hovertemplate=f"{c}: %{{y:.0%}}<extra></extra>"))
    fig.update_yaxes(tickformat=".0%", range=[0, 1], title="Share of purchases")
    fig.update_xaxes(title=f"Records processed (bins of {bin_size})")
    return _style(fig, height)


def category_before_after(before: pd.Series, after: pd.Series, labels=("Before drift", "After drift"),
                          height: int = 320) -> go.Figure:
    b = before.value_counts(normalize=True).reindex(config.CATEGORIES, fill_value=0)
    a = after.value_counts(normalize=True).reindex(config.CATEGORIES, fill_value=0)
    fig = go.Figure([
        go.Bar(x=config.CATEGORIES, y=b, name=labels[0], marker_color="#C9BEDA",
               hovertemplate="%{x}: %{y:.0%}<extra></extra>"),
        go.Bar(x=config.CATEGORIES, y=a, name=labels[1], marker_color=ORCHID,
               hovertemplate="%{x}: %{y:.0%}<extra></extra>"),
    ])
    fig.update_layout(barmode="group", bargap=0.25)
    fig.update_yaxes(tickformat=".0%", title="Share of purchases")
    return _style(fig, height)


# ------------------------------------------------------------------ performance
def before_after_bars(events: list[dict], height: int = 340) -> go.Figure:
    ev = pd.DataFrame(events)
    fig = go.Figure([
        go.Bar(x=ev["event_id"], y=ev["accuracy_stable"], name="Old model, before trend change",
               marker_color="#C9BEDA", hovertemplate="%{y:.0%}<extra></extra>"),
        go.Bar(x=ev["event_id"], y=ev["accuracy_degraded"], name="Old model, after trend change",
               marker_color=DRIFT, hovertemplate="%{y:.0%}<extra></extra>"),
        go.Bar(x=ev["event_id"], y=ev["accuracy_after"], name="Adapted model",
               marker_color=STABLE, hovertemplate="%{y:.0%}<extra></extra>"),
    ])
    fig.update_layout(barmode="group", bargap=0.3)
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%", title="Accuracy")
    return _style(fig, height)


def adaptive_vs_static_by_period(h: pd.DataFrame, height: int = 320) -> go.Figure:
    g = h.groupby(["period", "trend"])[["correct", "baseline_correct"]].mean().reset_index()
    x = [f"P{p}: {t}" for p, t in zip(g["period"], g["trend"])]
    fig = go.Figure([
        go.Bar(x=x, y=g["baseline_correct"], name="Static model (no adaptation)", marker_color="#C9BEDA",
               hovertemplate="%{y:.1%}<extra></extra>"),
        go.Bar(x=x, y=g["correct"], name="Adaptive model", marker_color=ORCHID,
               hovertemplate="%{y:.1%}<extra></extra>"),
    ])
    fig.update_layout(barmode="group", bargap=0.3)
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%", title="Accuracy")
    return _style(fig, height)


def version_metrics_bars(df: pd.DataFrame, height: int = 320) -> go.Figure:
    fig = go.Figure()
    for col, color, name in [("accuracy", ORCHID, "Accuracy"), ("precision", "#2F6FD0", "Precision"),
                             ("recall", "#3AA99F", "Recall"), ("f1", "#C9A227", "F1-score")]:
        fig.add_trace(go.Bar(x=df["model_version"], y=df[col], name=name, marker_color=color,
                             hovertemplate=f"{name} %{{y:.1%}}<extra></extra>"))
    fig.update_layout(barmode="group", bargap=0.25)
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%")
    fig.update_xaxes(title="Model version (records it predicted)")
    return _style(fig, height)


def confusion_heatmap(h: pd.DataFrame, height: int = 380) -> go.Figure:
    cm = pd.crosstab(h["actual"], h["predicted"]).reindex(
        index=config.CATEGORIES, columns=config.CATEGORIES, fill_value=0)
    fig = go.Figure(go.Heatmap(
        z=cm.values, x=cm.columns, y=cm.index, text=cm.values, texttemplate="%{text}",
        colorscale=[[0, "#FFFFFF"], [0.4, "#E7C3D8"], [1, ORCHID]], showscale=False,
        hovertemplate="Actual %{y}<br>Predicted %{x}<br>%{z} records<extra></extra>"))
    fig.update_xaxes(title="Predicted", side="bottom")
    fig.update_yaxes(title="Actual", autorange="reversed")
    return _style(fig, height, legend=False)


def prediction_vs_actual_strip(h: pd.DataFrame, n: int = 60, height: int = 260) -> go.Figure:
    t = h.tail(n)
    fig = go.Figure()
    for c in config.CATEGORIES:
        a = t[t["actual"] == c]
        p = t[t["predicted"] == c]
        fig.add_trace(go.Scatter(x=a["step"], y=["Actual"] * len(a), mode="markers", name=c,
                                 legendgroup=c, marker=dict(size=11, color=CATEGORY_COLORS[c], symbol="square"),
                                 hovertemplate=f"Step %{{x}}<br>Actual: {c}<extra></extra>"))
        fig.add_trace(go.Scatter(x=p["step"], y=["Predicted"] * len(p), mode="markers", name=c,
                                 legendgroup=c, showlegend=False,
                                 marker=dict(size=11, color=CATEGORY_COLORS[c], symbol="circle"),
                                 hovertemplate=f"Step %{{x}}<br>Predicted: {c}<extra></extra>"))
    wrong = t[~t["correct"].astype(bool)]
    fig.add_trace(go.Scatter(x=wrong["step"], y=["Miss"] * len(wrong), mode="markers", name="Wrong",
                             marker=dict(size=9, color=DRIFT, symbol="x"),
                             hovertemplate="Wrong at step %{x}<extra></extra>"))
    fig.update_yaxes(categoryorder="array", categoryarray=["Miss", "Predicted", "Actual"], showgrid=False)
    fig.update_xaxes(title="Records processed")
    return _style(fig, height)


def probability_bars(probs: dict[str, float], height: int = 300) -> go.Figure:
    s = pd.Series(probs).reindex(config.CATEGORIES).fillna(0).sort_values()
    colors = [CATEGORY_COLORS[c] if v == s.max() else "#D9D2E4" for c, v in s.items()]
    fig = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h", marker_color=colors,
                           text=[f"{v:.0%}" for v in s.values], textposition="outside",
                           hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
    fig.update_xaxes(range=[0, 1.12], tickformat=".0%", showgrid=True, gridcolor="#EEEAF3")
    return _style(fig, height, legend=False)


def importance_bars(df: pd.DataFrame, height: int = 300) -> go.Figure:
    d = df.sort_values("importance")
    fig = go.Figure(go.Bar(x=d["importance"], y=d["label"], orientation="h", marker_color=INK,
                           hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
    fig.update_xaxes(tickformat=".0%", showgrid=True, gridcolor="#EEEAF3")
    return _style(fig, height, legend=False)


def version_history(adaptations: list[dict], n_steps: int, height: int = 300) -> go.Figure:
    rows = [a for a in adaptations]
    xs, ys, labels = [], [], []
    for a in rows:
        ma, mi = a["to_version"].lstrip("v").split(".")
        xs.append(max(a["step"], 0))
        ys.append(int(ma) + int(mi) / 10)
        labels.append(f"{a['to_version']} ({a['type']})")
    if not xs:
        return _style(go.Figure(), height)
    xs.append(max(n_steps, xs[-1]))
    ys.append(ys[-1])
    labels.append("current")
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers", line_shape="hv",
                               line=dict(color=ORCHID, width=3), text=labels,
                               marker=dict(size=[10] * (len(xs) - 1) + [0], color=ORCHID),
                               hovertemplate="Step %{x}<br>%{text}<extra></extra>"))
    fig.update_yaxes(title="Model version", tickformat=".1f", tickprefix="v")
    fig.update_xaxes(title="Records processed")
    return _style(fig, height, legend=False)
