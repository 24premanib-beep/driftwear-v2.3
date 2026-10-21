import { describe, expect, it } from "vitest";
import { bytes, dataDriftMeta, eventTone, healthMeta, pct, pts, statusMeta, timeAgo } from "../format";

describe("format", () => {
  it("formats percentages and missing values", () => {
    expect(pct(0.8234)).toBe("82.3%");
    expect(pct(1, 0)).toBe("100%");
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
  });
  it("describes relative times", () => {
    const now = Date.parse("2026-10-01T12:00:00Z");
    expect(timeAgo("2026-10-01T11:59:58Z", now)).toBe("just now");
    expect(timeAgo("2026-10-01T11:59:30Z", now)).toBe("30 s ago");
    expect(timeAgo("2026-10-01T11:50:00Z", now)).toBe("10 min ago");
    expect(timeAgo("2026-10-01T09:00:00Z", now)).toBe("3 h ago");
    expect(timeAgo(null, now)).toBe("");
  });
  it("formats signed percentage points", () => {
    expect(pts(0.1234)).toBe("+12.3 pts");
    expect(pts(-0.04)).toBe("−4.0 pts");
    expect(pts(0.0001)).toBe("±0.0 pts");
    expect(pts(null)).toBe("—");
  });
  it("maps detector states to one tone and a label (never colour alone)", () => {
    expect(statusMeta("STABLE")).toMatchObject({ label: "Stable", tone: "stable" });
    expect(statusMeta("WARNING")).toMatchObject({ label: "Warning", tone: "warning" });
    expect(statusMeta("DRIFT")).toMatchObject({ label: "Drift", tone: "drift" });
    expect(statusMeta("ADAPTING")).toMatchObject({ label: "Adapting", tone: "adapted" });
    expect(statusMeta("???")).toMatchObject({ label: "???", tone: "neutral" });
    expect(eventTone("DRIFT_DETECTED")).toBe("drift");
    expect(eventTone("MODEL_VERSION_CREATED")).toBe("adapted");
    expect(healthMeta("AT_RISK")).toMatchObject({ label: "At risk", tone: "warning" });
    expect(healthMeta(undefined).label).toBe("Unknown");
  });
  it("labels data drift as a shift, not as concept drift", () => {
    expect(dataDriftMeta("DRIFT").label).toBe("Significant shift");
    expect(dataDriftMeta("INSUFFICIENT_DATA").tone).toBe("neutral");
  });
  it("formats sizes", () => {
    expect(bytes(512)).toBe("512 B");
    expect(bytes(450110)).toBe("440 KB");
    expect(bytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
