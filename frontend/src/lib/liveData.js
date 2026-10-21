/** Live Data page helpers (pure; unit-tested). */
export const newEventId = (now = new Date(), rand = Math.random) => `evt-${now.toISOString().slice(0, 10)}-${rand().toString(36).slice(2, 8)}`;

export const SAMPLE_EVENT = { customer_id: "C1023", previous_category: "Tops", customer_preference: "Casual", purchase_frequency: 4,
  recency: 12, price: 1299, discount: 20, purchase_date: "", season: "", actual_category: "" };

const NUMERIC_FIELDS = new Set(["purchase_frequency", "recency", "price", "discount", "month"]);

/** Form state → API payload. Empty optional fields are left out (the server derives month and season); numbers
 * are sent as numbers. Values that are not numbers are sent as typed so the server's validation reports them. */
export function buildEventPayload(form) {
  const out = {};
  Object.entries(form || {}).forEach(([k, v]) => {
    if (v === null || v === undefined) return;
    const value = typeof v === "string" ? v.trim() : v;
    if (value === "") return;
    if (NUMERIC_FIELDS.has(k) && typeof value === "string") {
      const n = Number(value);
      out[k] = Number.isFinite(n) ? n : value;
      return;
    }
    out[k] = value;
  });
  return out;
}

/** Event received → validated → prediction → prediction id → model version → actual outcome → error status. */
export function trackerSteps(result, outcome = null) {
  if (!result?.prediction) return [];
  const p = result.prediction;
  const out = outcome || result.outcome;
  const warnings = result.validation?.warnings?.length || 0;
  return [
    { key: "received", label: "Event received", status: "done", value: result.event_id || "No event id", time: result.received_at },
    { key: "validated", label: "Data validation", status: "done", value: warnings ? `Passed with ${warnings} warning${warnings > 1 ? "s" : ""}` : "All checks passed" },
    { key: "prediction", label: "Prediction generated", status: "done", value: p.predicted_category, detail: `${Math.round(p.confidence * 100)}% confidence` },
    { key: "prediction_id", label: "Prediction ID", status: "done", value: `#${p.id}`, time: p.created_at },
    { key: "model", label: "Model version", status: "done", value: p.model_version },
    { key: "outcome", label: "Actual outcome", status: out ? "done" : "pending", value: out ? out.actual_category : "Waiting for the real category",
      time: out?.outcome_at },
    { key: "error", label: "Error status", status: out ? (out.is_correct ? "done" : "failed") : "pending",
      value: out ? (out.is_correct ? "Correct (error = 0)" : "Wrong (error = 1)") : "Computed when the outcome arrives",
      detail: out ? `Detector ${out.status ?? out.detector_status}${out.new_model_version ? ` · model adapted to ${out.new_model_version}` : ""}` : null },
  ];
}

export function eventRowStatus(p) {
  if (!p?.actual_category) return { label: "Awaiting outcome", tone: "neutral" };
  return p.is_correct ? { label: "Correct", tone: "stable" } : { label: "Wrong", tone: "drift" };
}

/** How an external application sends the same event (shown on the page; the token is a placeholder). */
export function curlExample(origin, event) {
  return `curl -X POST ${origin}/api/events \\\n  -H "Authorization: Bearer <ACCESS_TOKEN>" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(event)}'`;
}

/**
 * The seven stages of a live event, for either a fresh POST /api/events response (`result`, optionally with a later
 * `outcome` response) or a stored prediction row (`row`, e.g. from the history table). Every value comes from the
 * server; a stage the backend has not reached is "pending", never assumed done.
 */
export function journey({ result = null, outcome = null, row = null } = {}) {
  const p = result?.prediction || row;
  if (!p) return [];
  const o = outcome || result?.outcome || null;
  const labeled = Boolean(o) || Boolean(row?.actual_category);
  const actual = o?.actual_category ?? row?.actual_category;
  const correct = o ? o.is_correct : row?.is_correct;
  const detector = o ? `${o.previous_status} → ${o.status}` : row?.detector_status;
  const scoredBy = o?.scored_version ?? row?.scored_version;
  const rescored = o?.rescored ?? row?.rescored;
  const warnings = result?.validation?.warnings?.length || 0;
  return [
    { key: "received", label: "Event received", status: "done", value: result?.event_id ?? row?.event_id ?? "No event id", time: result?.received_at ?? p.created_at },
    { key: "validated", label: "Input validated", status: "done",
      value: result ? (warnings ? `Passed with ${warnings} warning${warnings > 1 ? "s" : ""}` : "All checks passed") : "Passed (stored events are always valid)" },
    { key: "predicted", label: "Prediction generated", status: "done", value: p.predicted_category, detail: `${Math.round(p.confidence * 100)}% probability` },
    { key: "recorded", label: "Prediction ID and model version recorded", status: "done", value: `#${p.id}`, version: p.model_version, time: p.created_at },
    { key: "outcome", label: "Actual outcome", status: labeled ? "done" : "pending", value: labeled ? actual : "Awaiting the actual category",
      time: o ? null : row?.outcome_at },
    { key: "error", label: "Prediction error", status: labeled ? (correct ? "done" : "failed") : "pending",
      value: labeled ? (correct ? "Correct, error = 0" : "Wrong, error = 1") : "Computed when the outcome arrives",
      detail: labeled && rescored ? `Re-scored by ${scoredBy} because the model changed before the outcome arrived` : null },
    { key: "detector", label: "Drift detector updated", status: labeled ? "done" : "pending",
      value: labeled ? (detector ? `Detector ${detector}` : "Updated") : "The detector only reads labeled outcomes",
      detail: o?.drift_detected ? `Drift confirmed${o.new_model_version ? `; model adapted to ${o.new_model_version}` : ""}` : o?.adaptation_error ? `Adaptation failed: ${o.adaptation_error}` : null },
  ];
}
