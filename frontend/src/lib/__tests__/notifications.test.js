import { describe, expect, it } from "vitest";
import { buildNotifications, categorize, countUnread, isNotification, isToast, notificationLink, toastContent } from "../notifications";

const drift = { event: "DRIFT_DETECTED", stream: "live", timestamp: "2026-10-04T10:00:01.000+00:00", detector: "DDM",
  severity: "High", model_version: "v1.0", message: "Concept drift detected", data: { step: 412, from_version: "v1.0", to_version: "v2.0" } };

describe("notifications", () => {
  it("categorizes backend events", () => {
    expect(categorize(drift)).toBe("DRIFT");
    expect(categorize({ event: "WARNING_DETECTED" })).toBe("WARNING");
    expect(categorize({ event: "MODEL_VERSION_CREATED" })).toBe("MODEL");
    expect(categorize({ event: "DETECTOR_CHANGED" })).toBe("SYSTEM");
    expect(categorize({ event: "PREDICTION_CREATED" })).toBe("INFO");
  });
  it("keeps routine simulation traffic out of the notification center", () => {
    expect(isNotification({ event: "PREDICTION_CREATED", stream: "live" })).toBe(true);
    expect(isNotification({ event: "PREDICTION_CREATED", stream: "simulation" })).toBe(false);
    expect(isNotification({ event: "PREDICTION_RESULT", stream: "live" })).toBe(false);
    expect(isNotification({ event: "SIMULATION_STATE", stream: "simulation" })).toBe(false);
    expect(isNotification(drift)).toBe(true);
  });
  it("builds toasts from the event payload only", () => {
    expect(isToast(drift)).toBe(true);
    expect(isToast({ event: "PREDICTION_CREATED" })).toBe(false);
    const t = toastContent(drift);
    expect(t.title).toBe("Concept drift detected");
    expect(t.facts).toEqual([["Detector", "DDM"], ["Severity", "High"], ["Model", "v1.0"], ["Record", 412]]);
    const rollback = toastContent({ event: "MODEL_ACTIVATED", stream: "live", model_version: "v1.0", data: { rollback: true, from_version: "v2.0" } });
    expect(rollback.title).toBe("Model rollback completed");
  });
  it("merges, dedupes, sorts and counts unread", () => {
    const older = { ...drift, event: "MODEL_VERSION_CREATED", timestamp: "2026-10-04T10:00:00.000+00:00" };
    const items = buildNotifications([drift], [drift, older, { event: "PREDICTION_RESULT", stream: "live", timestamp: "x" }]);
    expect(items.map((e) => e.event)).toEqual(["DRIFT_DETECTED", "MODEL_VERSION_CREATED"]);
    expect(countUnread(items, null)).toBe(2);
    expect(countUnread(items, "2026-10-04T10:00:00.500+00:00")).toBe(1);
  });
  it("links each notification to the page that explains it, within the user's role", () => {
    expect(notificationLink(drift, { staff: true })).toBe("/app/drift-performance");
    expect(notificationLink({ ...drift, stream: "simulation" }, { staff: true })).toBe("/app/drift-performance?stream=simulation");
    expect(notificationLink({ event: "MODEL_ACTIVATED", stream: "live" }, { staff: true })).toBe("/app/models");
    expect(notificationLink(drift, { staff: false })).toBe("/app");
    expect(notificationLink({ event: "PREDICTION_CREATED", stream: "live" })).toBe("/app/live");
  });
});
