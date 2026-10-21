/** Pure helpers for the WebSocket client (kept separate so they can be unit-tested). */

/** Exponential backoff with jitter: 0.5–1 × min(max, base × 2^attempt). */
export function backoffDelay(attempt, { base = 1000, max = 30000, random = Math.random } = {}) {
  const ceiling = Math.min(max, base * 2 ** attempt);
  return Math.round(ceiling / 2 + random() * (ceiling / 2));
}

/** Fold one server event into the per-stream status snapshot shown in the header ribbon. */
export function applyEvent(snapshot, ev) {
  const stream = ev?.stream;
  if (!snapshot || !stream || !snapshot[stream]) return snapshot;
  const cur = { ...snapshot[stream] };
  const d = ev.data || {};
  switch (ev.event) {
    case "PREDICTION_RESULT":
      if (d.status) cur.status = d.status;
      if (d.rolling_accuracy !== undefined) cur.rolling_accuracy = d.rolling_accuracy;
      if (d.step !== undefined) cur.records_processed = d.step + 1;
      break;
    case "WARNING_DETECTED":
    case "STATUS_CHANGED":
      if (d.status) cur.status = d.status;
      break;
    case "DRIFT_DETECTED":
      cur.status = "DRIFT";
      cur.adapting = true;
      cur.adapting_to = d.to_version;
      cur.last_drift_severity = ev.severity || d.severity;
      break;
    case "ADAPTATION_STARTED":
      cur.adapting = true;
      cur.adapting_to = d.to_version;
      break;
    case "ADAPTATION_COMPLETED":
    case "ADAPTATION_FAILED":
      cur.adapting = false;
      cur.status = "STABLE";            // the detector restarts for the (new or kept) model
      break;
    case "MODEL_VERSION_CREATED":
      if (ev.model_version) cur.model_version = ev.model_version;
      break;
    case "MODEL_ACTIVATED":
      if (ev.model_version) cur.model_version = ev.model_version;
      cur.status = "STABLE";            // monitoring restarts for the activated model
      cur.adapting = false;
      break;
    case "DETECTOR_CHANGED":
      if (d.detector) cur.detector = d.detector;
      if (d.status) cur.status = d.status;
      break;
    case "PERFORMANCE_UPDATED":
      if (d.rolling_accuracy !== undefined) cur.rolling_accuracy = d.rolling_accuracy;
      if (d.records_processed !== undefined) cur.records_processed = d.records_processed;
      if (d.status) cur.status = d.status;
      if (ev.model_version) cur.model_version = ev.model_version;
      break;
    case "SIMULATION_RESET":
      Object.assign(cur, { status: "STABLE", model_version: "v1.0", records_processed: 0, adapting: false });
      break;
    default:
      return snapshot;
  }
  return { ...snapshot, [stream]: cur };
}

/** Events that should make a page re-fetch its data. */
export const REFRESH_EVENTS = new Set([
  "PREDICTION_RESULT", "WARNING_DETECTED", "STATUS_CHANGED", "DRIFT_DETECTED", "ADAPTATION_COMPLETED",
  "ADAPTATION_FAILED", "MODEL_VERSION_CREATED", "MODEL_ACTIVATED", "DETECTOR_CHANGED", "RECORDS_PROCESSED",
  "DATA_UPLOADED", "SIMULATION_RESET", "TREND_CHANGED", "SIMULATION_STATE", "PERFORMANCE_UPDATED",
]);
