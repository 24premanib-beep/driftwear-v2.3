import { describe, expect, it } from "vitest";
import { comparisonBars, deltaInfo, focusSeries, phaseRegions, verdict } from "../comparison";

const seg = (n, acc, from = 0, to = 9) => ({ n, accuracy: acc, precision: acc, recall: acc, f1: acc, error_rate: n ? 1 - acc : null, from_step: from, to_step: to });
const EV = { before: seg(50, 0.9, 10, 59), during: seg(20, 0.25, 60, 79), after: seg(0, null), to_version: "v2.0", recovered: null,
  focus: { from_step: 10, to_step: 79 } };

describe("drift comparison helpers", () => {
  it("builds one row per metric and leaves unmeasured phases empty", () => {
    const rows = comparisonBars(EV);
    expect(rows.map((r) => r.key)).toEqual(["accuracy", "precision", "recall", "f1", "error_rate"]);
    expect(rows[0]).toMatchObject({ before: 0.9, during: 0.25, after: null });
    expect(comparisonBars(null)).toEqual([]);
  });
  it("shades only the phases that have outcomes", () => {
    expect(phaseRegions(EV)).toEqual([{ phase: "before", label: "Before drift", from: 10, to: 59 },
      { phase: "during", label: "During drift", from: 60, to: 79 }]);
  });
  it("describes deltas in the right direction", () => {
    expect(deltaInfo(0.123)).toEqual({ text: "+12.3 pts", tone: "stable" });
    expect(deltaInfo(0.2, true)).toEqual({ text: "+20.0 pts", tone: "drift" });
    expect(deltaInfo(null).text).toBe("—");
  });
  it("focuses the series on the event and states a verdict", () => {
    const series = Array.from({ length: 300 }, (_, i) => ({ step: i }));
    const part = focusSeries(series, EV, 5);
    expect(part[0].step).toBe(5);
    expect(part[part.length - 1].step).toBe(84);
    expect(verdict(EV).tone).toBe("warning");
    expect(verdict({ ...EV, recovered: true }).tone).toBe("stable");
    expect(verdict({ ...EV, to_version: null }).tone).toBe("drift");
  });
});
