/**
 * The DriftWear API, one function per endpoint. Pages call these instead of composing paths, so every request
 * shape lives in one place and matches the backend (see /docs). All functions return the parsed JSON response
 * or throw an ApiError (status, code, message, details) from ./api.
 */
import { api, downloadFile } from "./api";

const post = (path, body, query) => api(path, { method: "POST", body: body ?? {}, query });

export const Auth = {
  login: (email, password) => post("/api/auth/login", { email, password }),
  register: (name, email, password) => post("/api/auth/register", { name, email, password }),
  me: () => api("/api/auth/me"),
  logout: () => post("/api/auth/logout"),
};

export const Meta = { get: () => api("/api/meta") };

export const Overview = {
  dashboard: (stream) => api("/api/dashboard", { query: { stream } }),
  recentEvents: (limit = 100, stream) => api("/api/events/recent", { query: { limit, stream } }),
};

export const Performance = {
  summary: (stream) => api("/api/performance", { query: { stream } }),
  comparison: (stream) => api("/api/performance/comparison", { query: { stream } }),
};

export const Drift = {
  status: (stream) => api("/api/drift/status", { query: { stream } }),
  events: (stream, limit = 200) => api("/api/drift/events", { query: { stream, limit } }),
  statistics: (stream) => api("/api/drift/statistics", { query: { stream } }),
  data: (stream, window, reference) => api("/api/drift/data", { query: { stream, window, reference } }),
  processUploaded: (count) => post("/api/drift/process", { stream: "live", count }),
  setDetector: (stream, detector) => post("/api/drift/detector", { stream, detector }),
};

export const Predictions = {
  predict: (input) => post("/api/predict", input),
  list: (query) => api("/api/predictions", { query }),
  get: (id) => api(`/api/predictions/${id}`),
  recordOutcome: (id, actualCategory) => post(`/api/predictions/${id}/outcome`, { actual_category: actualCategory }),
};

export const Events = {
  send: (event) => post("/api/events", event),
  sendBatch: (events) => post("/api/events/batch", { events }),
  /** `ref` is {event_id} or {prediction_id}, whichever the producer has. */
  outcome: (ref, actualCategory) => post("/api/events/outcome", { ...ref, actual_category: actualCategory }),
  outcomes: (outcomes) => post("/api/events/outcomes", { outcomes }),
  summary: () => api("/api/events/summary"),
  rejections: (query) => api("/api/events/rejections", { query }),
};

export const Data = {
  upload: (file, strict) => {
    const form = new FormData();
    form.append("file", file);
    return api("/api/data/upload", { method: "POST", form, query: strict ? { strict: "true" } : undefined });
  },
  records: (query) => api("/api/data", { query }),
  statistics: () => api("/api/data/statistics"),
  uploads: (query) => api("/api/data/uploads", { query }),
  uploadReport: (id) => api(`/api/data/uploads/${id}`),
  validation: () => api("/api/data/validation"),
  downloadTemplate: () => downloadFile("/api/data/template", "driftwear_template.csv"),
};

export const Models = {
  list: (stream) => api("/api/models", { query: { stream } }),
  get: (stream, version) => api(`/api/models/${encodeURIComponent(version)}`, { query: { stream } }),
  current: (stream) => api("/api/models/current", { query: { stream } }),
  health: (stream) => api("/api/models/health", { query: { stream } }),
  compare: (stream, a, b) => api("/api/models/compare", { query: { stream, a, b } }),
  activations: (stream) => api("/api/models/activations", { query: { stream } }),
  rollback: (stream, toVersion, reason) => post("/api/models/rollback", { stream, to_version: toVersion, reason }),
  activate: (stream, version, reason) => post(`/api/models/${encodeURIComponent(version)}/activate`, { stream, reason }),
  retrainNow: (stream) => post("/api/models/adapt", { stream }),
};

export const Simulation = {
  state: () => api("/api/simulation/state"),
  start: (speed, pauseOnDrift) => post("/api/simulation/start", { speed, pause_on_drift: pauseOnDrift }),
  pause: () => post("/api/simulation/pause"),
  step: (count, stopOnDrift) => post("/api/simulation/step", { count, stop_on_drift: stopOnDrift }),
  changeTrend: () => post("/api/simulation/trend-change"),
  reset: (regenerate) => post("/api/simulation/reset", { regenerate }),
};

export const System = {
  monitoring: (stream) => api("/api/system/monitoring", { query: { stream } }),
  health: (component) => api(component ? `/api/health/${component}` : "/api/health"),
};

export const Audit = {
  list: (query) => api("/api/audit-logs", { query }),
  facets: () => api("/api/audit-logs/facets"),
};

export const Users = {
  list: () => api("/api/users"),
  update: (id, changes) => api(`/api/users/${id}`, { method: "PATCH", body: changes }),
};
