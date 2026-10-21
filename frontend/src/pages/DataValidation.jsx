import { Link } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { IssueTable, ValidationBanner } from "../components/validation";
import { Badge, Empty, ErrorNote, Loading, Measure, Measures, PageHeader, Panel, Table } from "../components/ui";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Data } from "../lib/endpoints";
import { dateTime, num, pct, timeAgo } from "../lib/format";
import { useApi, useQueryParam } from "../lib/hooks";
import { issueLine } from "../lib/validation";

function UploadReport({ id }) {
  const up = useApi(() => Data.uploadReport(id), [id]);
  if (up.loading && !up.data) return <Loading label={`Loading the report for upload #${id}…`} rows={3} />;
  if (up.error) return <ErrorNote error={up.error} onRetry={() => up.reload()} />;
  const rep = up.data?.report;
  if (!rep) return <p className="text-sm text-muted">This upload has no stored report.</p>;
  return (
    <div className="space-y-4">
      <ValidationBanner report={rep} accepted={up.data.status === "accepted"} message={rep.decision} />
      {rep.errors?.length > 0 && <section><h3 className="mb-2 text-sm font-semibold text-drift-ink">Rejected rows</h3><IssueTable issues={rep.errors} total={rep.error_count} kind="error" /></section>}
      {rep.warnings?.length > 0 && <section><h3 className="mb-2 text-sm font-semibold text-warning-ink">Warnings</h3><IssueTable issues={rep.warnings} total={rep.warning_count} kind="warning" /></section>}
      <details className="text-sm">
        <summary className="link inline-block">Technical details (raw report)</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-canvas p-3 text-xs">{JSON.stringify({ ...rep, preview: undefined }, null, 2)}</pre>
      </details>
    </div>
  );
}

export default function DataValidation() {
  const v = useApi(() => Data.validation(), []);
  useLiveRefresh(() => v.reload({ silent: true }), "live", { events: new Set(["DATA_UPLOADED", "PREDICTION_CREATED"]), delay: 1000 });
  const [reportId, setReportId] = useQueryParam("upload", "");
  const d = v.data;
  return (
    <>
      <PageHeader title="Data validation"
        lede="Nothing enters the pipeline unchecked. CSV rows and live events pass the same rules; anything invalid is reported with its reason and never turned into a prediction."
        actions={<Link to="/app/data" className="btn btn-secondary">Upload a CSV</Link>} />
      <ErrorNote error={v.error} onRetry={() => v.reload()} className="mb-6" />
      {v.loading && !d ? <Loading label="Loading validation rules and results…" rows={5} /> : d && (
        <div className="space-y-6">
          <section aria-label="CSV uploads">
            <h2 className="mb-2 text-md font-semibold text-fg">CSV uploads</h2>
            <Measures>
              <Measure label="Uploads accepted" value={num(d.csv.uploads_accepted)} />
              <Measure label="Uploads rejected" value={num(d.csv.uploads_rejected)} tone={d.csv.uploads_rejected ? "drift" : undefined} sub="Missing columns or strict mode" />
              <Measure label="Rows accepted" value={num(d.csv.valid_rows)} sub={`of ${num(d.csv.total_rows)} rows checked`} />
              <Measure label="Rows rejected" value={num(d.csv.invalid_rows)} tone={d.csv.invalid_rows ? "warning" : undefined} />
              <Measure label="Duplicates skipped" value={num(d.csv.duplicate_rows)} sub="In-file and previously queued" />
            </Measures>
          </section>
          <section aria-label="Live events">
            <h2 className="mb-2 text-md font-semibold text-fg">Live events</h2>
            <Measures>
              <Measure label="Accepted" value={num(d.live.accepted)} />
              <Measure label="Rejected" value={num(d.live.rejected)} tone={d.live.rejected ? "warning" : undefined} sub={d.live.last_rejection_at ? `Last ${timeAgo(d.live.last_rejection_at)}` : "None"} />
              <Measure label="Rejection rate" value={d.live.rejection_rate === null || d.live.rejection_rate === undefined ? "N/A" : pct(d.live.rejection_rate)} sub="Of all live events" />
            </Measures>
          </section>

          <div className="grid items-start gap-6 xl:grid-cols-2">
            <Panel title="The rules" description="Generated from the rules the server applies (ml/validation.py)">
              <ul className="space-y-1.5 text-sm text-fg">{d.rules.checks.map((c) => <li key={c} className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-faint" aria-hidden="true" />{c}</li>)}</ul>
              <div className="mt-5 grid gap-5 border-t border-seam pt-4 sm:grid-cols-2">
                <div>
                  <h3 className="mb-1.5 text-sm font-semibold text-fg">Numeric limits</h3>
                  <ul className="space-y-1 text-sm text-muted">{d.rules.numeric.map((n) => (
                    <li key={n.column}><span className="text-fg">{n.column}</span>: {n.min_exclusive ? `more than ${n.min}` : `at least ${n.min}`}, at most {num(n.max)}{n.integer ? ", whole number" : ""}</li>))}
                  </ul>
                </div>
                <div>
                  <h3 className="mb-1.5 text-sm font-semibold text-fg">Allowed values</h3>
                  <ul className="space-y-1 text-sm text-muted">{Object.entries(d.rules.choices).map(([k, vals]) => <li key={k}><span className="text-fg">{k}</span>: {vals.join(", ")}</li>)}</ul>
                </div>
              </div>
              <dl className="mt-5 space-y-2 border-t border-seam pt-4 text-sm">
                <div><dt className="font-medium text-fg">CSV, default</dt><dd className="text-muted">{d.rules.policy.csv_default}</dd></div>
                <div><dt className="font-medium text-fg">CSV, strict</dt><dd className="text-muted">{d.rules.policy.csv_strict}</dd></div>
                <div><dt className="font-medium text-fg">Live events</dt><dd className="text-muted">{d.rules.policy.events}</dd></div>
                <div><dt className="font-medium text-fg">Fields</dt><dd className="text-muted">Live events need {d.rules.event_required_fields.join(", ")}; optional: {d.rules.event_optional_fields.join(", ")}. Any other field is rejected.</dd></div>
              </dl>
            </Panel>
            <Panel title="Most common problems" description="Among recently rejected live events">
              {d.top_rejection_reasons.length ? (
                <ul className="divide-y divide-seam">
                  {d.top_rejection_reasons.map((r) => (
                    <li key={`${r.field}-${r.message}`} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                      <span><code className="text-fg">{r.field || "event"}</code><span className="text-muted"> — {r.message}</span></span>
                      <span className="tabular text-muted">{num(r.count)}×</span>
                    </li>))}
                </ul>
              ) : <p className="text-sm text-muted">No live event has been rejected. Every one so far passed validation.</p>}
            </Panel>
          </div>

          <Panel title="Recent CSV uploads" description="Open a report to see every rejected row and why" flush>
            {d.recent_uploads.length ? (
              <Table caption="Recent CSV uploads">
                <thead><tr><th className="th">Upload</th><th className="th">File</th><th className="th">Result</th><th className="th">Rows</th>
                  <th className="th">Accepted</th><th className="th">Rejected</th><th className="th">Duplicates</th><th className="th">When</th><th className="th" /></tr></thead>
                <tbody>
                  {d.recent_uploads.map((u) => (
                    <tr key={u.id} className={String(reportId) === String(u.id) ? "bg-plum-50/70" : ""}>
                      <td className="td tabular text-muted">#{u.id}</td><td className="td font-medium">{u.filename}</td>
                      <td className="td">{u.status === "accepted" ? <Badge tone="stable" icon>Accepted</Badge> : <Badge tone="drift" icon>Rejected</Badge>}</td>
                      <td className="td tabular">{num(u.total_rows)}</td><td className="td tabular">{num(u.valid_rows)}</td><td className="td tabular">{num(u.invalid_rows)}</td>
                      <td className="td tabular">{num(u.duplicate_rows)}</td><td className="td whitespace-nowrap text-muted" title={dateTime(u.created_at)}>{timeAgo(u.created_at)}</td>
                      <td className="td text-right"><button type="button" className="link text-sm" aria-expanded={String(reportId) === String(u.id)}
                        onClick={() => setReportId(String(reportId) === String(u.id) ? "" : String(u.id))}>{String(reportId) === String(u.id) ? "Hide report" : "View report"}</button></td>
                    </tr>))}
                </tbody>
              </Table>
            ) : <Empty title="No uploads yet">Upload a labeled CSV on the Data management page; its validation report appears here.</Empty>}
            {reportId && <div className="border-t border-seam p-5"><UploadReport id={reportId} /></div>}
          </Panel>

          <Panel title="Rejected live events" description="Stored with the errors that stopped them. None of them reached the model." flush>
            {d.recent_rejections.length ? (
              <Table caption="Rejected live events">
                <thead><tr><th className="th">When</th><th className="th">Event ID</th><th className="th">Sent as</th><th className="th">By</th><th className="th">Problems</th></tr></thead>
                <tbody>
                  {d.recent_rejections.map((r) => (
                    <tr key={r.id}>
                      <td className="td whitespace-nowrap text-muted" title={dateTime(r.created_at)}>{timeAgo(r.created_at)}</td>
                      <td className="td"><code className="text-xs">{r.event_id || "—"}</code></td>
                      <td className="td">{r.source === "batch" ? `Batch item ${r.batch_index + 1}` : "Single event"}</td>
                      <td className="td text-muted">{r.user_name || "—"}</td>
                      <td className="td text-sm"><ul className="space-y-0.5">{r.errors.map((e, i) => <li key={i} className="text-drift-ink">{issueLine(e)}<span className="text-muted"> — {e.message}</span></li>)}</ul></td>
                    </tr>))}
                </tbody>
              </Table>
            ) : <p className="px-5 py-5 text-sm text-muted">No rejected live events.</p>}
          </Panel>
        </div>
      )}
    </>
  );
}
