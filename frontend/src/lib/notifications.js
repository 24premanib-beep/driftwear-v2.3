/**
 * Notification center + toasts. Pure functions over the events the backend pushes over WebSocket
 * (and /api/events/recent). Nothing here creates events: every notification is a real backend event.
 */
import { EVENT_LABELS } from "./format";

export const CATEGORIES = {
  DRIFT: { label: "Drift", tone: "drift" },
  WARNING: { label: "Warnings", tone: "warning" },
  MODEL: { label: "Model", tone: "adapted" },
  INFO: { label: "Data", tone: "neutral" },
  SYSTEM: { label: "System", tone: "neutral" },
};

const BY_EVENT = {
  PREDICTION_CREATED: "INFO", PREDICTION_RESULT: "INFO", DATA_UPLOADED: "INFO", RECORDS_PROCESSED: "INFO",
  STATUS_CHANGED: "INFO",
  WARNING_DETECTED: "WARNING",
  DRIFT_DETECTED: "DRIFT", ADAPTATION_FAILED: "DRIFT",
  ADAPTATION_STARTED: "MODEL", ADAPTATION_COMPLETED: "MODEL", MODEL_VERSION_CREATED: "MODEL", MODEL_ACTIVATED: "MODEL",
  DETECTOR_CHANGED: "SYSTEM", PIPELINE_ERROR: "SYSTEM", TREND_CHANGED: "SYSTEM", SIMULATION_RESET: "SYSTEM",
};

export function categorize(ev) {
  return BY_EVENT[ev?.event] || "SYSTEM";
}

/** Events worth a notification. Routine per-record simulation traffic is left to the activity feeds. */
export function isNotification(ev) {
  if (!ev || !BY_EVENT[ev.event]) return false;
  if (ev.event === "PREDICTION_RESULT") return false;                          // shown in feeds, too frequent here
  if (ev.event === "PREDICTION_CREATED") return ev.stream === "live";
  if (ev.event === "STATUS_CHANGED") return ev.stream === "live";
  return true;
}

/** Events that also pop up as a toast, wherever the user is in the app. */
const TOAST_EVENTS = new Set(["DRIFT_DETECTED", "ADAPTATION_STARTED", "MODEL_VERSION_CREATED", "MODEL_ACTIVATED",
  "ADAPTATION_FAILED", "PIPELINE_ERROR"]);
export const isToast = (ev) => TOAST_EVENTS.has(ev?.event);

export function eventKey(ev) {
  return `${ev.event}|${ev.stream ?? ""}|${ev.timestamp}|${ev.data?.prediction_id ?? ""}|${ev.data?.step ?? ""}`;
}

export function notificationTitle(ev) {
  const title = {
    DRIFT_DETECTED: "Concept drift detected",
    ADAPTATION_STARTED: "Model adaptation started",
    MODEL_VERSION_CREATED: "New model created",
    MODEL_ACTIVATED: ev?.data?.rollback ? "Model rollback completed" : "Model activated",
    WARNING_DETECTED: `${ev?.detector || "Detector"} entered warning state`,
  }[ev?.event];
  return title || EVENT_LABELS[ev?.event] || ev?.event || "Event";
}

/** Title and labelled facts for a toast, taken only from the event payload. */
export function toastContent(ev) {
  const d = ev.data || {};
  const facts = [];
  if (ev.event === "DRIFT_DETECTED") {
    facts.push(["Detector", ev.detector || d.detector], ["Severity", ev.severity || d.severity],
      ["Model", ev.model_version || d.from_version], ["Record", d.step]);
  } else if (ev.event === "ADAPTATION_STARTED") {
    facts.push(["From", d.from_version], ["Training", d.to_version],
      ["Window", d.window_start !== undefined ? `records ${d.window_start}–${d.window_end}` : undefined]);
  } else if (ev.event === "MODEL_VERSION_CREATED") {
    facts.push(["Version", ev.model_version || d.version], ["Trigger", d.trigger], ["Records used", d.records_used]);
  } else if (ev.event === "MODEL_ACTIVATED") {
    facts.push(["Version", ev.model_version || d.to_version], ["Previous", d.from_version]);
  }
  if (ev.stream === "simulation") facts.push(["Stream", "Simulation"]);
  return {
    title: notificationTitle(ev),
    message: ev.message,
    facts: facts.filter(([, v]) => v !== undefined && v !== null && v !== ""),
    category: categorize(ev),
    timestamp: ev.timestamp,
  };
}

/** Merge live (WebSocket) and initial (API) events, dedupe, keep notifications only, newest first. */
export function buildNotifications(live = [], initial = [], limit = 60) {
  const seen = new Set();
  const out = [];
  for (const ev of [...live, ...initial]) {
    if (!isNotification(ev)) continue;
    const key = eventKey(ev);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(ev);
  }
  out.sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)));
  return out.slice(0, limit);
}

export function countUnread(items, lastSeen) {
  if (!lastSeen) return items.length;
  return items.filter((e) => String(e.timestamp) > String(lastSeen)).length;
}

/** Where a notification leads. Staff go to the investigation pages; users to the pages they can open. */
export function notificationLink(ev, { staff = false } = {}) {
  const q = ev?.stream === "simulation" ? "?stream=simulation" : "";
  if (!staff) {
    if (["PREDICTION_CREATED", "PREDICTION_RESULT"].includes(ev?.event)) return "/app/live";
    return `/app${q}`;
  }
  switch (ev?.event) {
    case "DRIFT_DETECTED": return `/app/drift-performance${q}`;
    case "WARNING_DETECTED":
    case "STATUS_CHANGED":
    case "DETECTOR_CHANGED": return `/app/drift${q}`;
    case "ADAPTATION_STARTED":
    case "ADAPTATION_COMPLETED":
    case "ADAPTATION_FAILED": return `/app/adaptation${q}`;
    case "MODEL_VERSION_CREATED":
    case "MODEL_ACTIVATED": return `/app/models${q}`;
    case "DATA_UPLOADED":
    case "RECORDS_PROCESSED": return "/app/data";
    case "PREDICTION_CREATED":
    case "PREDICTION_RESULT": return ev?.stream === "simulation" ? "/app/simulation" : "/app/live";
    case "TREND_CHANGED":
    case "SIMULATION_RESET": return "/app/simulation";
    case "PIPELINE_ERROR": return "/app/system";
    default: return `/app${q}`;
  }
}
