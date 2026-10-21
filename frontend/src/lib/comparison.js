/**
 * Before / during / after drift helpers. Input is GET /api/performance/comparison: every number shown comes
 * from the API (measured on labeled outcomes); these functions only reshape it for charts and text.
 */
export const PHASES = [
  { key: "before", label: "Before drift", tone: "stable" },
  { key: "during", label: "During drift", tone: "drift" },
  { key: "after", label: "After adaptation", tone: "adapted" },
];

export const METRICS = [
  { key: "accuracy", label: "Accuracy" },
  { key: "precision", label: "Precision" },
  { key: "recall", label: "Recall" },
  { key: "f1", label: "F1 score" },
  { key: "error_rate", label: "Error rate", lowerIsBetter: true },
];

const measured = (seg, key) => (seg?.n ? seg[key] ?? null : null);

/** Grouped-bar rows: one per metric, one value per phase. A phase without outcomes is null (no bar drawn). */
export function comparisonBars(ev) {
  if (!ev) return [];
  return METRICS.map((m) => ({ metric: m.label, key: m.key, before: measured(ev.before, m.key),
    during: measured(ev.during, m.key), after: measured(ev.after, m.key) }));
}

/** Shaded regions on the timeline: only phases that have outcomes. */
export function phaseRegions(ev) {
  if (!ev) return [];
  return PHASES.filter((p) => ev[p.key]?.n).map((p) => ({ phase: p.key, label: p.label, from: ev[p.key].from_step, to: ev[p.key].to_step }));
}

/** The part of the rolling series around one drift event, with `pad` records of context on each side. */
export function focusSeries(series, ev, pad = 40) {
  if (!series?.length || !ev?.focus) return series || [];
  const lo = ev.focus.from_step - pad;
  const hi = ev.focus.to_step + pad;
  const part = series.filter((p) => p.step >= lo && p.step <= hi);
  return part.length >= 2 ? part : series;
}

/** "+12.3 pts" with a tone: better is green, worse red (error rate: lower is better). */
export function deltaInfo(delta, lowerIsBetter = false) {
  if (delta === null || delta === undefined) return { text: "—", tone: "neutral" };
  const pts = delta * 100;
  if (Math.abs(pts) < 0.05) return { text: "±0.0 pts", tone: "neutral" };
  const better = lowerIsBetter ? pts < 0 : pts > 0;
  return { text: `${pts > 0 ? "+" : "−"}${Math.abs(pts).toFixed(1)} pts`, tone: better ? "stable" : "drift" };
}

export function verdict(ev) {
  if (!ev) return null;
  if (!ev.to_version) return { label: "Adaptation failed: the previous model was kept", tone: "drift" };
  if (ev.recovered === true) return { label: "Performance recovered after adaptation", tone: "stable" };
  if (ev.recovered === false) return { label: "Not recovered yet", tone: "drift" };
  return { label: "Measuring recovery: waiting for outcomes after the adaptation", tone: "warning" };
}

/** Which model served a phase (before and during: the old model; after: the adapted one). */
export const phaseVersion = (ev, phase) => (phase === "after" ? ev?.to_version || ev?.from_version : ev?.from_version);
