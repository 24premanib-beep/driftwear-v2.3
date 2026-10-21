/** Validation reports (CSV uploads and live events) as sentences people can act on. Nothing is re-validated here. */
const NUMERIC = /^-?\d+(\.\d+)?$/;
const quote = (v) => (NUMERIC.test(String(v)) ? String(v) : `"${v}"`);
const fmt = (x) => new Intl.NumberFormat().format(x || 0);

/** One problem: `Invalid value: Season = "XYZ" (row 5)`, `Missing value: Price`, `Unexpected field: bogus`. */
export function issueLine(issue) {
  const where = issue.row ? ` (row ${issue.row})` : "";
  const col = issue.column ?? issue.field;
  if (!col) return `${issue.message}${where}`;
  if (/unexpected/i.test(issue.message || "")) return `Unexpected field: ${col}${where}`;
  if (issue.value === null || issue.value === undefined || issue.value === "") {
    return /missing/i.test(issue.message || "") ? `Missing value: ${col}${where}` : `${col}: ${issue.message}${where}`;
  }
  return `Invalid value: ${col} = ${quote(issue.value)}${where}`;
}

/** Upload report → headline ("Upload rejected" / "Validation successful"), detail line and specific problems. */
export function summarizeUpload(report, { accepted, message } = {}) {
  if (!report) return null;
  const ok = accepted ?? Boolean(report.ok && report.valid_rows > 0);
  const lines = [];
  (report.missing_columns || []).forEach((c) => lines.push(`Missing column: ${c}`));
  (report.column_errors || []).filter((e) => !e.startsWith("Missing required columns")).forEach((e) => lines.push(e));
  const errors = report.errors || [];
  const issues = errors.slice(0, 8).map((e) => ({ text: issueLine(e), hint: e.message }));
  const detail = ok
    ? [`${fmt(report.valid_rows)} records accepted`, report.invalid_rows ? `${fmt(report.invalid_rows)} rejected` : null,
      report.duplicate_rows ? `${fmt(report.duplicate_rows)} duplicates skipped` : null].filter(Boolean).join(" · ")
    : message || report.decision || "No rows were queued.";
  return { ok, tone: ok ? (report.invalid_rows ? "warning" : "stable") : "drift", headline: ok ? "Validation successful" : "Upload rejected",
    detail, lines, issues, more: Math.max(0, (report.error_count ?? errors.length) - issues.length) };
}

/** Live-event 422 details [{field, value, message}] → lines with the rule as a hint. */
export function eventErrorLines(details) {
  return Array.isArray(details) ? details.map((d) => ({ text: issueLine(d), hint: d.message })) : [];
}
