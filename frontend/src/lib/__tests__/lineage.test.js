import { describe, expect, it } from "vitest";
import { buildLineage, compareVersions, defaultComparison, isRollback } from "../lineage";

const items = [
  { version: "v1.0", parent_version: null, kind: "initial", is_active: false },
  { version: "v2.0", parent_version: "v1.0", kind: "drift", is_active: false },
  { version: "v2.1", parent_version: "v2.0", kind: "refresh", is_active: false },
  { version: "v1.1", parent_version: "v1.0", kind: "manual", is_active: false },
  { version: "v3.0", parent_version: "v2.1", kind: "drift", is_active: true },
];

describe("lineage", () => {
  it("orders versions numerically", () => {
    expect(["v2.1", "v10.0", "v1.0", "v2.0"].sort(compareVersions)).toEqual(["v1.0", "v2.0", "v2.1", "v10.0"]);
  });
  it("walks parents before children with depth", () => {
    const l = buildLineage(items);
    expect(l.map((n) => `${n.version}:${n.depth}`)).toEqual(["v1.0:0", "v1.1:1", "v2.0:1", "v2.1:2", "v3.0:3"]);
    expect(l.find((n) => n.version === "v2.0").reason).toBe("Drift adaptation");
  });
  it("detects rollbacks and picks a comparison pair", () => {
    expect(isRollback("v2.0", "v3.0")).toBe(true);
    expect(isRollback("v3.1", "v3.0")).toBe(false);
    expect(defaultComparison(items, "v3.0")).toEqual(["v2.1", "v3.0"]);
    expect(defaultComparison(items, "v1.0")).toEqual(["v1.0", "v1.0"]);
    expect(defaultComparison([], "v1.0")).toEqual([null, null]);
  });
});
