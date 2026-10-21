import { describe, expect, it } from "vitest";
import { applyEvent, backoffDelay } from "../realtime";

const snap = { live: { status: "STABLE", model_version: "v1.0", detector: "DDM", records_processed: 10 } };

describe("backoffDelay", () => {
  it("grows exponentially, is capped, and is jittered", () => {
    expect(backoffDelay(0, { random: () => 0 })).toBe(500);
    expect(backoffDelay(0, { random: () => 1 })).toBe(1000);
    expect(backoffDelay(3, { random: () => 1 })).toBe(8000);
    expect(backoffDelay(20, { random: () => 1 })).toBe(30000);
  });
});

describe("applyEvent", () => {
  it("follows the drift → adaptation → new version sequence", () => {
    let s = applyEvent(snap, { event: "WARNING_DETECTED", stream: "live", data: { status: "WARNING" } });
    expect(s.live.status).toBe("WARNING");
    s = applyEvent(s, { event: "DRIFT_DETECTED", stream: "live", data: { to_version: "v2.0" } });
    expect(s.live).toMatchObject({ status: "DRIFT", adapting: true, adapting_to: "v2.0" });
    s = applyEvent(s, { event: "ADAPTATION_COMPLETED", stream: "live", data: {} });
    s = applyEvent(s, { event: "MODEL_VERSION_CREATED", stream: "live", model_version: "v2.0", data: {} });
    expect(s.live).toMatchObject({ status: "STABLE", adapting: false, model_version: "v2.0" });
  });
  it("tracks results and ignores other streams or unknown events", () => {
    const s = applyEvent(snap, { event: "PREDICTION_RESULT", stream: "live", data: { status: "STABLE", rolling_accuracy: 0.8, step: 41 } });
    expect(s.live.records_processed).toBe(42);
    expect(applyEvent(snap, { event: "PREDICTION_RESULT", stream: "simulation", data: {} })).toBe(snap);
    expect(applyEvent(snap, { event: "SOMETHING_ELSE", stream: "live", data: {} })).toBe(snap);
    expect(applyEvent(null, { event: "PREDICTION_RESULT", stream: "live" })).toBe(null);
  });
});
