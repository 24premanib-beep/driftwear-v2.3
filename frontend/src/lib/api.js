/**
 * Fetch wrapper for the DriftWear API.
 * Adds the bearer token, turns the backend's {"error": {...}} shape into an ApiError,
 * and signs the user out when the server says the session is no longer valid.
 */
const API_URL = (import.meta.env?.VITE_API_URL || "").replace(/\/$/, "");
const WS_URL = (import.meta.env?.VITE_WS_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(status, code, message, details = null, requestId = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Field errors as {field: message}, for inline form messages. */
  get fieldErrors() {
    if (!Array.isArray(this.details)) return {};
    return Object.fromEntries(this.details.filter((d) => d.field).map((d) => [d.field, d.message]));
  }
}

let getToken = () => null;
let onUnauthorized = () => {};

export function configureApi(options) {
  getToken = options.getToken ?? getToken;
  onUnauthorized = options.onUnauthorized ?? onUnauthorized;
}

export function buildUrl(path, query) {
  const url = `${API_URL}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function parseError(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  const err = body?.error;
  const fallback = res.status >= 500
    ? "The server could not complete the request. Try again in a moment."
    : `Request failed (${res.status}).`;
  return new ApiError(res.status, err?.code || "http_error", err?.message || fallback, err?.details ?? null,
    err?.request_id ?? null);
}

export async function api(path, { method = "GET", body, query, form, signal, raw = false } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) {
    payload = form;                        // FormData: the browser sets the multipart boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(buildUrl(path, query), { method, headers, body: payload, signal });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    const error = await parseError(res);
    if (res.status === 401 && token && !path.startsWith("/api/auth/login")) onUnauthorized(error);
    throw error;
  }
  if (raw) return res;
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res.text();
}

export function wsUrl() {
  if (WS_URL) return `${WS_URL}/ws`;
  if (API_URL) return `${API_URL.replace(/^http/, "ws")}/ws`;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

/** Download a file from an authenticated endpoint. */
export async function downloadFile(path, filename) {
  const res = await api(path, { raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
