import { describe, expect, it } from "vitest";
import { buildEventPayload, eventRowStatus, journey, newEventId, trackerSteps } from "../liveData";

const RESULT = { event_id: "evt-1", received_at: "2026-10-04T10:00:00Z", validation: { warnings: [] }, outcome: null,
  prediction: { id: 12, predicted_category: "Tops", confidence: 0.62, model_version: "v2.0", created_at: "2026-10-04T10:00:00Z" } };

describe("live data helpers", () => {
  it("builds a payload without empty optional fields and never guesses numbers", () => {
    expect(buildEventPayload({ event_id: " evt-1 ", customer_id: "", price: "1299", discount: "20", season: "", purchase_frequency: 4, actual_category: "" }))
      .toEqual({ event_id: "evt-1", price: 1299, discount: 20, purchase_frequency: 4 });
    expect(buildEventPayload({ price: "abc" })).toEqual({ price: "abc" });
  });
  it("creates readable event ids", () => {
    expect(newEventId(new Date("2026-10-04T10:00:00Z"), () => 0.123456)).toMatch(/^evt-2026-10-04-[a-z0-9]+$/);
  });
  it("tracks an event from receipt to error status", () => {
    const steps = trackerSteps(RESULT);
    expect(steps.map((s) => s.key)).toEqual(["received", "validated", "prediction", "prediction_id", "model", "outcome", "error"]);
    expect(steps[3].value).toBe("#12");
    expect(steps[5].status).toBe("pending");
    const done = trackerSteps(RESULT, { actual_category: "Bottoms", is_correct: false, status: "WARNING", new_model_version: null });
    expect(done[6]).toMatchObject({ status: "failed", value: "Wrong (error = 1)" });
    expect(eventRowStatus({ actual_category: null }).label).toBe("Awaiting outcome");
    expect(eventRowStatus({ actual_category: "Tops", is_correct: true }).tone).toBe("stable");
  });
  it("follows an event through the seven pipeline stages without assuming the outcome", () => {
    const fresh = journey({ result: RESULT });
    expect(fresh.map((s) => s.key)).toEqual(["received", "validated", "predicted", "recorded", "outcome", "error", "detector"]);
    expect(fresh.slice(4).map((s) => s.status)).toEqual(["pending", "pending", "pending"]);
    const scored = journey({ result: RESULT, outcome: { actual_category: "Tops", is_correct: true, previous_status: "STABLE", status: "WARNING",
      scored_version: "v2.1", rescored: true, drift_detected: false } });
    expect(scored[5]).toMatchObject({ status: "done", value: "Correct, error = 0" });
    expect(scored[5].detail).toMatch(/Re-scored by v2.1/);
    expect(scored[6].value).toBe("Detector STABLE → WARNING");
    const stored = journey({ row: { id: 7, event_id: "evt-7", predicted_category: "Dresses", confidence: 0.4, model_version: "v1.0",
      actual_category: "Tops", is_correct: false, detector_status: "STABLE", created_at: "2026-10-04T10:00:00Z" } });
    expect(stored[0].value).toBe("evt-7");
    expect(stored[5]).toMatchObject({ status: "failed" });
    expect(journey({})).toEqual([]);
  });
});
