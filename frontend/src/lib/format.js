/** Formatting and state vocabulary. Missing values are shown as "—" (or "N/A" where the brief asks), never as 0. */
export const pct = (x, digits = 1) =>
  x === null || x === undefined || Number.isNaN(Number(x)) ? "—" : `${(Number(x) * 100).toFixed(digits)}%`;

/** Percentage points, signed: +12.3 pts / −4.0 pts. */
export const pts = (x, digits = 1) => {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  const v = Number(x) * 100;
  if (Math.abs(v) < 0.05) return "±0.0 pts";
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)} pts`;
};

export const num = (x) => (x === null || x === undefined ? "—" : new Intl.NumberFormat().format(x));

export const money = (x) =>
  x === null || x === undefined ? "—" : `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(x)}`;

export function dateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function timeOnly(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function timeAgo(value, now = Date.now()) {
  if (!value) return "";
  const t = new Date(value).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return dateTime(value);
}

export function bytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const shortHash = (h) => (h ? `${h.slice(0, 12)}…` : "—");

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
}

/**
 * Detector states. `tone` picks the reserved state colour; the UI always pairs it with an icon and the label,
 * so state is never carried by colour alone.
 */
export const STATUS = {
  STABLE: { label: "Stable", tone: "stable", meaning: "Prediction errors are at their normal level." },
  WARNING: { label: "Warning", tone: "warning", meaning: "Errors are rising. The detector is watching closely; nothing changes yet." },
  DRIFT: { label: "Drift", tone: "drift", meaning: "A sustained rise in errors is confirmed: the input → category relationship changed." },
  ADAPTING: { label: "Adapting", tone: "adapted", meaning: "A new model is being trained on data from after the change." },
};

export const statusMeta = (status) => STATUS[status] || { label: status || "Unknown", tone: "neutral", meaning: "" };

export const EVENT_LABELS = {
  PREDICTION_CREATED: "New prediction",
  PREDICTION_RESULT: "Outcome scored",
  WARNING_DETECTED: "Warning",
  STATUS_CHANGED: "Detector status changed",
  DRIFT_DETECTED: "Concept drift confirmed",
  ADAPTATION_STARTED: "Adaptation started",
  ADAPTATION_COMPLETED: "Adaptation completed",
  ADAPTATION_FAILED: "Adaptation failed",
  MODEL_VERSION_CREATED: "New model version",
  MODEL_ACTIVATED: "Model activated",
  PERFORMANCE_UPDATED: "Performance updated",
  DETECTOR_CHANGED: "Detector changed",
  DATA_UPLOADED: "Data uploaded",
  RECORDS_PROCESSED: "Uploaded records processed",
  SIMULATION_STATE: "Simulation updated",
  TREND_CHANGED: "Fashion trend changed",
  SIMULATION_RESET: "Simulation reset",
  PIPELINE_ERROR: "Pipeline error",
};

/** Tone of a backend event (for its icon). */
export function eventTone(name) {
  if (["DRIFT_DETECTED", "ADAPTATION_FAILED", "PIPELINE_ERROR"].includes(name)) return "drift";
  if (name === "WARNING_DETECTED") return "warning";
  if (["ADAPTATION_STARTED", "ADAPTATION_COMPLETED", "MODEL_VERSION_CREATED", "MODEL_ACTIVATED"].includes(name)) return "adapted";
  if (name === "STATUS_CHANGED") return "stable";
  return "neutral";
}

export const KIND_LABELS = { initial: "Initial model", drift: "Drift adaptation", refresh: "Scheduled refresh", manual: "Manual retrain" };

/** Where a prediction came from, in the words people use. */
export const SOURCE_LABELS = { api: "Prediction form", event: "Live event", upload: "CSV upload", simulation: "Simulation" };

/** Model health bands (computed by the backend: /api/models/health). */
export const HEALTH = {
  HEALTHY: { label: "Healthy", tone: "stable" },
  AT_RISK: { label: "At risk", tone: "warning" },
  DEGRADED: { label: "Degraded", tone: "drift" },
  UNKNOWN: { label: "Unknown", tone: "neutral" },
};
export const healthMeta = (band) => HEALTH[band] || HEALTH.UNKNOWN;

/** Component health (System monitoring, /health/*). */
export const COMPONENT = {
  healthy: { label: "Healthy", tone: "stable" },
  warning: { label: "Warning", tone: "warning" },
  error: { label: "Error", tone: "drift" },
};
export const componentMeta = (status) => COMPONENT[status] || { label: status || "Unknown", tone: "neutral" };

/** Data drift status per feature (PSI bands). PSI is diagnostic: the label never says "drift" alone. */
export const dataDriftMeta = (status) => ({
  STABLE: { label: "Stable", tone: "stable" },
  WARNING: { label: "Moderate shift", tone: "warning" },
  DRIFT: { label: "Significant shift", tone: "drift" },
  INSUFFICIENT_DATA: { label: "Not enough data", tone: "neutral" },
}[status] || { label: status || "Unknown", tone: "neutral" });
