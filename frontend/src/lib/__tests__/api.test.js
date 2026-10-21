import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, buildUrl, configureApi } from "../api";

function response(status, body, headers = { "content-type": "application/json" }) {
  return { ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k.toLowerCase()] }, json: async () => body };
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("builds query strings and skips empty values", () => {
    expect(buildUrl("/api/predictions", { page: 2, search: "", labeled: false, x: null })).toBe("/api/predictions?page=2&labeled=false");
  });
  it("sends the bearer token and JSON body", async () => {
    const fetch = vi.fn(async () => response(200, { ok: true }));
    vi.stubGlobal("fetch", fetch);
    configureApi({ getToken: () => "tok" });
    await api("/api/predict", { method: "POST", body: { a: 1 } });
    const [, init] = fetch.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(init.body).toBe('{"a":1}');
  });
  it("turns the backend error shape into ApiError with field errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(422, { error: { code: "validation_failed", message: "price: too low",
      details: [{ field: "price", message: "too low" }], request_id: "abc" } })));
    const err = await api("/api/predict", { method: "POST", body: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, code: "validation_failed", requestId: "abc" });
    expect(err.fieldErrors).toEqual({ price: "too low" });
  });
  it("signs out on 401 when a token was used", async () => {
    const onUnauthorized = vi.fn();
    configureApi({ getToken: () => "expired", onUnauthorized });
    vi.stubGlobal("fetch", vi.fn(async () => response(401, { error: { code: "not_authenticated", message: "Session ended" } })));
    await expect(api("/api/auth/me")).rejects.toThrow("Session ended");
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
  it("reports network failures clearly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api("/api/health").catch((e) => e);
    expect(err.code).toBe("network_error");
  });
});
