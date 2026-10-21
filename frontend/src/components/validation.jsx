/** Validation results, shown the same way for CSV uploads and live events (rules: ml/validation.py). */
import { AlertCircle } from "lucide-react";
import { Table, ToneIcon, tone } from "./ui";
import { num } from "../lib/format";
import { eventErrorLines, issueLine, summarizeUpload } from "../lib/validation";

/** "Upload rejected — Missing column: Customer_Preference" or "Validation successful — 2,100 records accepted". */
export function ValidationBanner({ report, accepted, message }) {
  const s = summarizeUpload(report, { accepted, message });
  if (!s) return null;
  const t = tone(s.tone);
  return (
    <div className={`rounded-lg border px-4 py-3.5 ${t.border} ${t.soft}`} role={s.ok ? "status" : "alert"}>
      <div className={`flex items-center gap-2 text-md font-semibold ${t.text}`}><ToneIcon tone={s.tone} className="h-5 w-5" />{s.headline}</div>
      <p className="mt-0.5 text-sm text-fg">{s.detail}</p>
      {(s.lines.length > 0 || s.issues.length > 0) && (
        <ul className="mt-2 space-y-1 text-sm">
          {s.lines.map((l) => <li key={l} className="font-medium text-fg">{l}</li>)}
          {s.issues.map((i, n) => <li key={`${i.text}-${n}`} className="text-fg">{i.text}<span className="text-muted"> — {i.hint}</span></li>)}
        </ul>
      )}
      {s.more > 0 && <p className="mt-1.5 text-xs text-muted">and {num(s.more)} more in the full report below.</p>}
    </div>
  );
}

/** A rejected live event: every problem the server found, one per line, with the rule that failed. */
export function EventErrors({ error }) {
  const lines = eventErrorLines(error?.details);
  if (!lines.length) return null;
  return (
    <div className="rounded-md border border-drift/35 bg-drift-soft/60 px-4 py-3 text-sm" role="alert">
      <p className="flex items-center gap-2 font-medium text-drift-ink"><AlertCircle className="h-4 w-4" aria-hidden="true" />
        Rejected by validation: the event never reached the model</p>
      <ul className="mt-1.5 space-y-1" aria-label="Validation problems">
        {lines.map((l, i) => <li key={`${l.text}-${i}`} className="text-fg">{l.text}<span className="text-muted"> — {l.hint}</span></li>)}
      </ul>
    </div>
  );
}

/** Row-level issues of an upload report (errors or warnings). */
export function IssueTable({ issues, total, kind = "error" }) {
  if (!issues?.length) return null;
  return (
    <div>
      <Table className="max-h-80 overflow-y-auto rounded-md border border-seam" caption={kind === "error" ? "Rejected rows" : "Warnings"}>
        <thead className="sticky top-0"><tr><th className="th">Row</th><th className="th">Column</th><th className="th">Value</th><th className="th">Problem</th></tr></thead>
        <tbody>
          {issues.map((i, n) => (
            <tr key={`${i.row}-${i.column}-${n}`}>
              <td className="td tabular">{i.row ?? "File"}</td>
              <td className="td">{i.column || i.field || "—"}</td>
              <td className="td max-w-[160px] truncate text-muted" title={i.value ?? ""}>{i.value === null || i.value === undefined || i.value === "" ? "(empty)" : String(i.value)}</td>
              <td className={`td ${kind === "error" ? "text-drift-ink" : "text-warning-ink"}`}>{i.message}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      {total > issues.length && <p className="mt-1.5 text-xs text-muted">Showing the first {num(issues.length)} of {num(total)}.</p>}
    </div>
  );
}

export { issueLine };
