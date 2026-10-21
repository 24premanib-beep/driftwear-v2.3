"""
Analytics for the dashboard, drift-monitoring and performance pages.

Pure functions over plain rows (no database, no web framework), so they are
easy to test. Input rows are labeled outcomes, oldest first:

    {"step", "ts", "predicted", "actual", "correct", "baseline_predicted", "baseline_correct",
     "model_version", "status", "error", "shadow", "period", "trend"}

`error` is the 0/1 value the detector saw (it can differ from `not correct`
when a late label was re-scored by a newer model).
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from ml import config
from ml.evaluation import classification_metrics

STATUS_ORDER = ["STABLE", "WARNING", "DRIFT"]


def _r(x, d: int = 4):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else round(float(x), d)


def _frame(rows: list[dict]) -> pd.DataFrame:
    cols = ["step", "ts", "predicted", "actual", "correct", "baseline_predicted", "baseline_correct",
            "model_version", "status", "error", "shadow", "period", "trend"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["correct"] = df["correct"].astype(bool).astype(int)
    df["baseline_correct"] = df["baseline_correct"].fillna(False).astype(bool).astype(int)
    df["error"] = df["error"].fillna(1 - df["correct"]).astype(int)
    return df.sort_values("step").reset_index(drop=True)


def _sample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """Stride-sample long series (rolling values are computed first, so nothing is lost
    in the curve); warning/drift points are delivered exactly by drift_markers()."""
    if len(df) <= max_points:
        return df
    stride = -(-len(df) // max_points)
    keep = (df.index % stride == 0) | (df.index == df.index[-1])
    return df[keep]


# ----------------------------------------------------------------------------- series
def performance_series(rows: list[dict], window: int = config.ROLLING_WINDOW, max_points: int = 1500) -> list[dict]:
    df = _frame(rows)
    if df.empty:
        return []
    df["accuracy"] = df["correct"].rolling(window, min_periods=1).mean()
    df["baseline_accuracy"] = df["baseline_correct"].rolling(window, min_periods=1).mean()
    df["error_rate"] = df["error"].rolling(window, min_periods=1).mean()
    out = _sample(df, max_points)
    return [{"step": int(r.step), "timestamp": r.ts, "accuracy": _r(r.accuracy), "baseline_accuracy": _r(r.baseline_accuracy),
             "error_rate": _r(r.error_rate), "error": int(r.error), "status": r.status,
             "model_version": r.model_version} for r in out.itertuples()]


def drift_markers(rows: list[dict], drift_events: list[dict], versions: list[dict]) -> dict:
    df = _frame(rows)
    warnings = []
    shadow: dict[str, list[int]] = {}
    if not df.empty:
        prev = df["status"].shift(fill_value="STABLE")
        for r in df[(df["status"] == "WARNING") & (prev != "WARNING")].itertuples():
            warnings.append({"step": int(r.step), "timestamp": r.ts})
        for r in df.itertuples():
            for name, st in (r.shadow or {}).items():
                if st == "DRIFT":
                    shadow.setdefault(name, []).append(int(r.step))
    drifts = [{"step": d["stream_step"], "event_key": d["event_key"], "detector": d["detector"],
               "change_point_step": d["change_point_step"], "from_version": d["previous_model_version"],
               "to_version": d["new_model_version"], "action": d["action"], "timestamp": d.get("detected_at")}
              for d in drift_events]
    adaptations = [{"step": v["created_step"], "version": v["version"], "kind": v["kind"],
                    "timestamp": v.get("created_at")}
                   for v in versions if (v.get("created_step") or -1) >= 0]
    return {"warnings": warnings, "drifts": drifts, "adaptations": adaptations, "shadow_drifts": shadow}


def status_counts(rows: list[dict]) -> dict[str, int]:
    c = Counter(r.get("status") for r in rows)
    return {s: int(c.get(s, 0)) for s in STATUS_ORDER}


# ----------------------------------------------------------------------------- metrics
def summary_metrics(rows: list[dict]) -> dict:
    df = _frame(rows)
    if df.empty:
        empty = classification_metrics([], [])
        return {"adaptive": empty, "baseline": empty, "n": 0}
    def rounded(m: dict) -> dict:
        return {k: _r(v) if isinstance(v, float) else v for k, v in m.items()}
    adaptive = classification_metrics(df["actual"].tolist(), df["predicted"].tolist())
    baseline = classification_metrics(df["actual"].tolist(), df["baseline_predicted"].fillna("").tolist())
    return {"adaptive": rounded(adaptive), "baseline": rounded(baseline), "n": int(len(df))}


def confusion(rows: list[dict]) -> dict:
    labels = list(config.CATEGORIES)
    idx = {c: i for i, c in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for r in rows:
        a, p = r.get("actual"), r.get("predicted")
        if a in idx and p in idx:
            m[idx[a]][idx[p]] += 1
    return {"labels": labels, "matrix": m, "axis": "rows = actual, columns = predicted"}


def by_version(rows: list[dict]) -> list[dict]:
    df = _frame(rows)
    out = []
    for version, g in df.groupby("model_version", sort=False):
        m = classification_metrics(g["actual"].tolist(), g["predicted"].tolist())
        out.append({"version": version, "n": int(len(g)), "first_step": int(g["step"].min()),
                    "last_step": int(g["step"].max()), "accuracy": _r(m["accuracy"]),
                    "precision": _r(m["precision"]), "recall": _r(m["recall"]), "f1": _r(m["f1"]),
                    "baseline_accuracy": _r(g["baseline_correct"].mean())})
    return sorted(out, key=lambda x: x["first_step"])


def by_period(rows: list[dict]) -> list[dict]:
    df = _frame(rows)
    if df.empty or df["period"].isna().all():
        return []
    out = []
    for period, g in df.dropna(subset=["period"]).groupby("period"):
        out.append({"period": int(period), "trend": g["trend"].mode().iloc[0] if g["trend"].notna().any() else None,
                    "n": int(len(g)), "adaptive_accuracy": _r(g["correct"].mean()),
                    "static_accuracy": _r(g["baseline_correct"].mean())})
    return out


def before_after(drift_events: list[dict]) -> list[dict]:
    return [{"event_key": d["event_key"], "step": d["stream_step"], "detector": d["detector"],
             "accuracy_stable": d.get("accuracy_stable"), "accuracy_degraded": d.get("accuracy_degraded"),
             "accuracy_after": d.get("accuracy_after"), "from_version": d.get("previous_model_version"),
             "to_version": d.get("new_model_version")} for d in drift_events]


def category_mix(rows: list[dict], last_n: int = 200) -> list[dict]:
    """Share of actual vs predicted categories in the most recent outcomes."""
    recent = rows[-last_n:]
    actual = Counter(r["actual"] for r in recent)
    predicted = Counter(r["predicted"] for r in recent)
    n = max(1, len(recent))
    return [{"category": c, "actual": _r(actual.get(c, 0) / n), "predicted": _r(predicted.get(c, 0) / n)}
            for c in config.CATEGORIES]


def performance_report(rows: list[dict], drift_events: list[dict]) -> dict:
    return {
        "summary": summary_metrics(rows),
        "confusion_matrix": confusion(rows),
        "by_version": by_version(rows),
        "by_period": by_period(rows),
        "before_after": before_after(drift_events),
        "category_mix": category_mix(rows),
    }


def recent_window_metrics(rows: list[dict], window: int = config.PERF_EVAL_WINDOW) -> dict:
    recent = rows[-window:]
    if not recent:
        return {"accuracy": None, "error_rate": None, "n": 0}
    acc = sum(bool(r["correct"]) for r in recent) / len(recent)
    return {"accuracy": _r(acc), "error_rate": _r(1 - acc), "n": len(recent)}


# ----------------------------------------------------------------------------- drift severity & impact
def drift_severity(accuracy_stable: float | None, accuracy_degraded: float | None,
                   error_rate: float | None = None) -> str:
    """High / Medium / Low, from how far accuracy fell between the stable and the degraded segment.

    Falls back to the degraded error rate when there is no stable segment to compare with.
    """
    if accuracy_stable is not None and accuracy_degraded is not None:
        drop = float(accuracy_stable) - float(accuracy_degraded)
        return "High" if drop >= 0.30 else "Medium" if drop >= 0.15 else "Low"
    if error_rate is not None:
        return "High" if error_rate >= 0.60 else "Medium" if error_rate >= 0.40 else "Low"
    return "Low"


def _segment(df: pd.DataFrame, start: int, end: int) -> dict:
    """Classification metrics of the labeled outcomes with step in [start, end)."""
    part = df[(df["step"] >= start) & (df["step"] < end)] if not df.empty else df
    if part.empty:
        return {"accuracy": None, "precision": None, "recall": None, "f1": None, "error_rate": None, "n": 0,
                "from_step": int(start), "to_step": int(end - 1)}
    m = classification_metrics(part["actual"].tolist(), part["predicted"].tolist())
    return {"accuracy": _r(m["accuracy"]), "precision": _r(m["precision"]), "recall": _r(m["recall"]),
            "f1": _r(m["f1"]), "error_rate": _r(m["error"]), "n": int(len(part)),
            "from_step": int(part["step"].min()), "to_step": int(part["step"].max())}


def drift_impact(rows: list[dict], drift_events: list[dict], window: int = config.PERF_EVAL_WINDOW,
                 min_after: int = 10) -> list[dict]:
    """Before / during / after metrics around every drift event, measured on real outcomes.

    before = up to `window` outcomes before the estimated change point (the old model, still fine)
    during = change point .. detection (the old model failing; what the detector reacted to)
    after  = the `window` outcomes after detection (the adapted model)
    Nothing is estimated: a segment with no outcomes is returned with n = 0 and null metrics.
    """
    df = _frame(rows)
    events = sorted(drift_events, key=lambda d: d["stream_step"])
    out = []
    for i, d in enumerate(events):
        step = int(d["stream_step"])
        cp = int(d["change_point_step"]) if d.get("change_point_step") is not None else step
        prev = int(events[i - 1]["stream_step"]) + 1 if i else 0
        before = _segment(df, max(prev, cp - window), cp)
        during = _segment(df, cp, step + 1)
        nxt = int(events[i + 1]["stream_step"]) if i + 1 < len(events) else None
        after_end = step + 1 + window if nxt is None else min(step + 1 + window, nxt)
        after = _segment(df, step + 1, after_end)
        recovered = None
        if after["n"] >= min_after and after["accuracy"] is not None and during["accuracy"] is not None:
            target = before["accuracy"] if before["accuracy"] is not None else during["accuracy"]
            recovered = bool(after["accuracy"] >= target - 0.05 or after["accuracy"] >= during["accuracy"] + 0.10)
        out.append({
            "event_key": d["event_key"], "step": step, "change_point_step": cp, "detector": d["detector"],
            "severity": drift_severity(d.get("accuracy_stable"), d.get("accuracy_degraded"), d.get("error_rate")),
            "from_version": d.get("previous_model_version"), "to_version": d.get("new_model_version"),
            "action": d.get("action"), "detected_at": d.get("detected_at"),
            "before": before, "during": during, "after": after,
            "after_complete": after["n"] >= min(window, max(0, (nxt or 10**9) - step - 1)),
            "recovered": recovered,
            "recovery_rule": "after-adaptation accuracy is within 5 points of the pre-drift accuracy, "
                             "or at least 10 points above the accuracy during drift",
        })
    return out


def latest_cycle(markers: dict, impact: list[dict], records_processed: int) -> list[dict]:
    """The most recent detect → adapt → recover cycle as ordered stages (for the dashboard timeline).

    Every stage is backed by stored data; stages that have not happened yet are 'pending' or 'none'.
    """
    last = impact[-1] if impact else None
    warn = None
    if last:
        prior = [w for w in markers.get("warnings", []) if w["step"] <= last["step"]]
        warn = prior[-1] if prior else None
    elif markers.get("warnings"):
        warn = markers["warnings"][-1]
    stages = [{"key": "prediction", "label": "Prediction", "status": "done" if records_processed else "none",
               "step": records_processed - 1 if records_processed else None,
               "detail": f"{records_processed} outcomes processed" if records_processed else "No outcomes yet"}]
    stages.append({"key": "warning", "label": "Warning", "status": "done" if warn else "none",
                   "step": warn["step"] if warn else None,
                   "detail": "Error rate entered the warning zone" if warn else "No warning before the last drift"})
    if not last:
        for key, label in (("drift", "Drift"), ("retraining", "Retraining"), ("new_model", "New model"),
                           ("recovery", "Recovery")):
            stages.append({"key": key, "label": label, "status": "none", "step": None, "detail": "No drift yet"})
        return stages
    adapted = last["to_version"] is not None
    stages.append({"key": "drift", "label": "Drift", "status": "done", "step": last["step"],
                   "detail": f"{last['event_key']} by {last['detector']} ({last['severity']} severity)"})
    stages.append({"key": "retraining", "label": "Retraining", "status": "done" if adapted else "failed",
                   "step": last["step"], "detail": f"Window from record {last['change_point_step']}" if adapted
                   else (last.get("action") or "Adaptation failed")})
    stages.append({"key": "new_model", "label": "New model", "status": "done" if adapted else "none",
                   "step": last["step"], "detail": f"{last['from_version']} → {last['to_version']}" if adapted
                   else f"{last['from_version']} kept"})
    rec = last["recovered"]
    after = last["after"]
    stages.append({"key": "recovery", "label": "Recovery",
                   "status": "done" if rec else "pending" if rec is None else "failed",
                   "step": after["to_step"] if after["n"] else None,
                   "detail": (f"Accuracy {after['accuracy']:.0%} over {after['n']} outcomes after adaptation"
                              if after["n"] else "Measured once outcomes arrive after the adaptation")})
    return stages


# ----------------------------------------------------------------------------- before / during / after comparison
METRIC_KEYS = ("accuracy", "precision", "recall", "f1", "error_rate")


def window_metrics(rows: list[dict], window: int | None = None) -> dict:
    """Accuracy / precision / recall / F1 / error rate of the last `window` labeled outcomes (all if None)."""
    part = rows[-window:] if window else rows
    if not part:
        return {"accuracy": None, "precision": None, "recall": None, "f1": None, "error_rate": None, "n": 0}
    m = classification_metrics([r["actual"] for r in part], [r["predicted"] for r in part])
    return {"accuracy": _r(m["accuracy"]), "precision": _r(m["precision"]), "recall": _r(m["recall"]),
            "f1": _r(m["f1"]), "error_rate": _r(m["error"]), "n": len(part)}


def _p(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def _deltas(a: dict, b: dict) -> dict:
    return {k: None if not a.get("n") or not b.get("n") or a.get(k) is None or b.get(k) is None
            else round(b[k] - a[k], 4) for k in METRIC_KEYS}


def _trend_change(df: pd.DataFrame, start: int, end: int, ts: dict) -> dict | None:
    """The data's own trend label changing inside [start, end] (only datasets that carry Period, i.e. simulation)."""
    if df.empty or df["period"].isna().all():
        return None
    part = df[(df["step"] >= start) & (df["step"] <= end)].dropna(subset=["period"])
    if len(part) < 2:
        return None
    periods, trends, steps = part["period"].astype(int).tolist(), part["trend"].tolist(), part["step"].tolist()
    idx = next((j for j in range(len(periods) - 1, 0, -1) if periods[j] != periods[j - 1]), None)
    if idx is None:
        return None
    return {"step": int(steps[idx]), "timestamp": ts.get(int(steps[idx])), "from_period": periods[idx - 1],
            "to_period": periods[idx], "from_trend": trends[idx - 1], "to_trend": trends[idx],
            "source": "Trend label carried by the records (simulation ground truth)"}


def _pooled(df: pd.DataFrame, ranges: list[tuple[int, int]]) -> dict:
    if df.empty or not ranges:
        return {"accuracy": None, "precision": None, "recall": None, "f1": None, "error_rate": None, "n": 0}
    mask = pd.Series(False, index=df.index)
    for lo, hi in ranges:
        mask |= (df["step"] >= lo) & (df["step"] <= hi)
    part = df[mask]
    return window_metrics([{"actual": a, "predicted": p} for a, p in zip(part["actual"], part["predicted"])])


def drift_comparison(rows: list[dict], drift_events: list[dict], versions: list[dict], *,
                     warnings: list[dict] | None = None, served: dict | None = None,
                     window: int = config.PERF_EVAL_WINDOW, min_after: int = 10) -> dict:
    """Before drift / during drift / after adaptation for every drift event, from real labeled outcomes.

    The three phases are exactly drift_impact()'s segments (so the dashboard and this view always agree). Each
    event adds what a presentation needs: the drift timestamp and detector, the versions before and after, the
    warning that preceded it, the data's own trend change when known, how many outcomes each model handled,
    metric deltas, and the six-stage story normal → trend change → errors rise → drift → adaptation → recovery.
    """
    df = _frame(rows)
    events = sorted(drift_events, key=lambda d: d["stream_step"])
    impacts = drift_impact(rows, events, window, min_after)
    ts = {int(r["step"]): r.get("ts") for r in rows}
    if warnings is None:
        warnings = drift_markers(rows, [], [])["warnings"]
    by_version = {v["version"]: v for v in versions}
    served = served or {}
    last_step = int(df["step"].max()) if not df.empty else -1
    out = []
    for i, (d, imp) in enumerate(zip(events, impacts)):
        step, cp = imp["step"], imp["change_point_step"]
        prev = int(events[i - 1]["stream_step"]) + 1 if i else 0
        nxt = int(events[i + 1]["stream_step"]) if i + 1 < len(events) else None
        for phase in ("before", "during", "after"):
            seg = imp[phase]
            seg["from_ts"] = ts.get(seg["from_step"]) if seg["n"] else None
            seg["to_ts"] = ts.get(seg["to_step"]) if seg["n"] else None
        warn = next((w for w in reversed(warnings) if prev <= w["step"] <= step), None)
        trend = _trend_change(df, prev, step, ts)
        after_end = (nxt - 1) if nxt is not None else last_step
        n_before = int(((df["step"] >= prev) & (df["step"] <= step)).sum()) if not df.empty else 0
        n_after = int(((df["step"] > step) & (df["step"] <= after_end)).sum()) if not df.empty else 0
        from_v, to_v = imp["from_version"], imp["to_version"]
        new = by_version.get(to_v) if to_v else None
        adaptation = None if new is None else {
            "version": new["version"], "created_at": new.get("created_at"), "records_used": new.get("training_records"),
            "window_start": new.get("window_start"), "window_end": new.get("window_end"),
            "validation_accuracy": new.get("accuracy"), "kind": new.get("kind")}
        b, du, a = imp["before"], imp["during"], imp["after"]
        rec = imp["recovered"]
        story = [
            {"key": "normal", "label": "Normal performance", "status": "done" if b["n"] else "none",
             "step": b["to_step"] if b["n"] else None, "timestamp": b["to_ts"],
             "detail": f"Accuracy {_p(b['accuracy'])} on {b['n']} outcomes with {from_v}" if b["n"]
             else "No outcomes before the change"},
            {"key": "trend_change", "label": "Trend changes", "status": "done",
             "step": trend["step"] if trend else cp, "timestamp": trend["timestamp"] if trend else ts.get(cp),
             "detail": f"{trend['from_trend']} → {trend['to_trend']}" if trend
             else f"Change point estimated at record {cp}"},
            {"key": "errors_rise", "label": "Error rate increases", "status": "done" if du["n"] else "none",
             "step": warn["step"] if warn else cp, "timestamp": warn.get("timestamp") if warn else ts.get(cp),
             "detail": f"Error rate {_p(b['error_rate'])} → {_p(du['error_rate'])}"
                       + (f"; warning at record {warn['step']}" if warn else "")},
            {"key": "drift", "label": "Drift detected", "status": "done", "step": step, "timestamp": imp["detected_at"],
             "detail": f"{imp['detector']}, {imp['severity']} severity, record {step}"},
            {"key": "adaptation", "label": "Model adaptation", "status": "done" if to_v else "failed", "step": step,
             "timestamp": adaptation["created_at"] if adaptation else imp["detected_at"],
             "detail": f"{from_v} → {to_v} ({adaptation['records_used'] if adaptation else '?'} records)" if to_v
             else f"{imp['action']}; {from_v} kept"},
            {"key": "recovery", "label": "Performance recovery",
             "status": "done" if rec else "pending" if rec is None else "failed",
             "step": a["to_step"] if a["n"] else None, "timestamp": a["to_ts"],
             "detail": (f"Accuracy {_p(du['accuracy'])} → {_p(a['accuracy'])} over {a['n']} outcomes" if a["n"]
                        else "Measured once outcomes arrive after the adaptation")},
        ]
        out.append({
            **imp, "drift_event_id": d.get("id"), "warning": warn, "trend_change": trend, "adaptation": adaptation,
            "predictions": {"before_adaptation": n_before, "after_adaptation": n_after,
                            "before_range": [prev, step], "after_range": [step + 1, after_end] if n_after else None,
                            "served_by_version": {v: served.get(v) for v in (from_v, to_v) if v}},
            "deltas": {"during_vs_before": _deltas(b, du), "after_vs_during": _deltas(du, a),
                       "after_vs_before": _deltas(b, a)},
            "story": story,
            "focus": {"from_step": max(prev, cp - window), "to_step": a["to_step"] if a["n"] else step},
        })
    pooled = {phase: _pooled(df, [(e[phase]["from_step"], e[phase]["to_step"]) for e in out if e[phase]["n"]])
              for phase in ("before", "during", "after")}
    return {"events": out, "pooled": pooled,
            "definitions": {
                "before": f"Up to {window} outcomes before the estimated change point (old model, still working)",
                "during": "Change point to detection: the old model failing, which the detector reacted to",
                "after": f"Up to {window} outcomes after the adapted model took over",
                "predictions": "Labeled outcomes handled by the old model (since the previous drift) and by the "
                               "new model (until the next drift or now)"}}


def activation_timeline(versions: list[dict], activations: list[dict]) -> list[dict]:
    """Which model became active when: versions created by training/adaptation plus admin activations and
    rollbacks, newest first. Built only from stored rows."""
    def iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    items = []
    for v in versions:
        initial = v.get("kind") == "initial"
        items.append({"timestamp": iso(v.get("created_at")), "action": "trained" if initial else "adapted",
                      "kind": v.get("kind"), "from_version": v.get("parent_version"), "to_version": v["version"],
                      "reason": v.get("trigger"), "actor": "System", "at_step": v.get("created_step")})
    for a in activations:
        actor = a.get("user_name") or (f"User #{a['user_id']}" if a.get("user_id") else "System")
        items.append({"timestamp": iso(a.get("created_at")), "action": a["action"], "kind": None,
                      "from_version": a["from_version"], "to_version": a["to_version"], "reason": a.get("reason"),
                      "actor": actor, "at_step": a.get("at_step")})
    return sorted(items, key=lambda x: str(x["timestamp"] or ""), reverse=True)
