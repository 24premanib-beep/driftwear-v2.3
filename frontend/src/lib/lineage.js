/** Model lineage and version helpers for the registry (derived from /api/models rows, nothing invented). */
import { KIND_LABELS } from "./format";

export function versionKey(v) {
  const m = /^v(\d+)\.(\d+)$/.exec(v || "");
  return m ? [Number(m[1]), Number(m[2])] : [0, 0];
}

export function compareVersions(a, b) {
  const [a1, a2] = versionKey(a);
  const [b1, b2] = versionKey(b);
  return a1 - b1 || a2 - b2;
}

/** Activating a version older than the active one is a rollback. */
export const isRollback = (target, active) => Boolean(active) && compareVersions(target, active) < 0;

/**
 * Lineage as an ordered list: each version after its parent (depth-first), with a depth for indentation
 * and the reason it exists. Versions whose parent is unknown start a new root.
 */
export function buildLineage(items = []) {
  const byVersion = new Map(items.map((v) => [v.version, v]));
  const children = new Map();
  const roots = [];
  [...items].sort((a, b) => compareVersions(a.version, b.version)).forEach((v) => {
    if (v.parent_version && byVersion.has(v.parent_version)) {
      if (!children.has(v.parent_version)) children.set(v.parent_version, []);
      children.get(v.parent_version).push(v);
    } else {
      roots.push(v);
    }
  });
  const out = [];
  const walk = (v, depth) => {
    out.push({ version: v.version, depth, kind: v.kind, reason: KIND_LABELS[v.kind] || v.kind, trigger: v.trigger,
      is_active: v.is_active, parent_version: v.parent_version, accuracy: v.accuracy, f1_score: v.f1_score,
      created_at: v.created_at });
    (children.get(v.version) || []).forEach((c) => walk(c, depth + 1));
  };
  roots.forEach((r) => walk(r, 0));
  return out;
}

/** Sensible default pair for "compare": the selected version against its parent (or the previous one). */
export function defaultComparison(items = [], selected) {
  const sorted = [...items].sort((a, b) => compareVersions(a.version, b.version));
  const target = sorted.find((v) => v.version === selected) || sorted[sorted.length - 1];
  if (!target) return [null, null];
  const parent = target.parent_version && sorted.find((v) => v.version === target.parent_version);
  const previous = sorted[sorted.indexOf(target) - 1];
  const base = parent || previous;
  return base ? [base.version, target.version] : [target.version, target.version];
}
