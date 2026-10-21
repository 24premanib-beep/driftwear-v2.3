import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CloudUpload, DatabaseZap, Download, FileSpreadsheet } from "lucide-react";
import { PairedBars, C } from "../components/charts";
import { IssueTable, ValidationBanner } from "../components/validation";
import { Badge, Disclosure, Empty, ErrorNote, Loading, Measure, Measures, Notice, PageHeader, Pagination, Panel, Spinner, Table } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Data, Drift } from "../lib/endpoints";
import { bytes, dateTime, money, num, timeAgo } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { useMeta } from "../lib/meta";

function Report({ report }) {
  const missing = Object.entries(report.missing_values || {}).filter(([, v]) => v);
  return (
    <div className="space-y-5">
      <Measures>
        <Measure label="Rows in the file" value={num(report.total_rows)} />
        <Measure label="Accepted and queued" value={num(report.valid_rows)} tone={report.valid_rows ? "stable" : undefined} sub="Waiting to be processed" />
        <Measure label="Rejected" value={num(report.invalid_rows)} tone={report.invalid_rows ? "drift" : undefined} sub="Never reach the model" />
        <Measure label="Duplicates skipped" value={num(report.duplicate_rows)} sub="In the file or uploaded before" />
      </Measures>
      {missing.length > 0 && <p className="text-sm text-muted">Missing values: {missing.map(([k, v]) => `${k} (${v})`).join(", ")}</p>}
      {report.errors?.length > 0 && <section><h3 className="mb-2 text-sm font-semibold text-drift-ink">Rejected rows ({num(report.error_count)} problems)</h3><IssueTable issues={report.errors} total={report.error_count} kind="error" /></section>}
      {report.warnings?.length > 0 && <section><h3 className="mb-2 text-sm font-semibold text-warning-ink">Warnings ({num(report.warning_count)})</h3><IssueTable issues={report.warnings} total={report.warning_count} kind="warning" /></section>}
      {report.preview?.length > 0 && (
        <Disclosure summary={`Preview of accepted rows (${report.preview.length})`}>
          <Table className="rounded-md border border-seam" caption="Preview of accepted rows">
            <thead><tr>{Object.keys(report.preview[0]).map((k) => <th key={k} className="th">{k}</th>)}</tr></thead>
            <tbody>{report.preview.map((r, i) => <tr key={i}>{Object.values(r).map((v, j) => <td key={j} className="td whitespace-nowrap">{String(v ?? "")}</td>)}</tr>)}</tbody>
          </Table>
        </Disclosure>
      )}
    </div>
  );
}

function Uploader({ rules, onUploaded }) {
  const meta = useMeta();
  const input = useRef(null);
  const [file, setFile] = useState(null);
  const [drag, setDrag] = useState(false);
  const [strict, setStrict] = useState(false);
  const upload = useAction((f) => Data.upload(f, strict));
  const tooBig = file && file.size > meta.max_upload_mb * 1024 * 1024;
  const wrongType = file && !/\.csv$/i.test(file.name);
  const report = upload.result?.report || upload.error?.details?.report;
  const choose = (f) => { if (f) { setFile(f); upload.reset(); } };
  return (
    <div className="space-y-5">
      <label onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files?.[0]); }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-9 text-center transition-colors ${drag ? "border-navy bg-navy-50" : "border-navy-200 bg-canvas/50 hover:border-navy-300"}`}>
        {file ? <FileSpreadsheet className="h-7 w-7 text-navy" aria-hidden="true" /> : <CloudUpload className="h-7 w-7 text-muted" aria-hidden="true" />}
        <span className="mt-2 text-sm font-medium text-fg">{file ? file.name : "Drop a CSV file here, or choose one"}</span>
        <span className="mt-1 text-xs text-muted">{file ? `${bytes(file.size)} · choose another file to replace it` : `UTF-8 CSV with a header row, up to ${meta.max_upload_mb} MB, labeled with Target_Category`}</span>
        <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => choose(e.target.files?.[0])} />
      </label>
      {tooBig && <ErrorNote error={{ message: `This file is larger than ${meta.max_upload_mb} MB. Split it into smaller files.` }} title="File too large" />}
      {wrongType && <ErrorNote error={{ message: "Only .csv files are accepted." }} title="Not a CSV file" />}
      {rules && (
        <Disclosure summary="Expected columns and rules">
          <p className="text-sm text-fg">Required: {rules.csv_required_columns.map((c) => <code key={c} className="mr-1.5 text-xs">{c}</code>)}</p>
          <p className="mt-1.5 text-sm text-muted">Optional: {rules.csv_optional_columns.join(", ")}. Any other column is ignored with a warning.</p>
          <ul className="mt-3 list-disc space-y-0.5 pl-5 text-sm text-muted">{rules.checks.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="mt-3 text-sm"><Link to="/app/validation" className="link">All validation rules and recent reports</Link></p>
        </Disclosure>
      )}
      <fieldset>
        <legend className="mb-2 text-sm font-medium text-fg">When some rows are invalid</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {[[false, "Keep the valid rows", rules?.policy?.csv_default || "Valid rows are queued; every rejected row is listed with its reason."],
            [true, "Reject the whole file (strict)", rules?.policy?.csv_strict || "Any invalid row rejects the whole file."]].map(([value, label, text]) => (
            <label key={label} className={`flex cursor-pointer gap-2.5 rounded-md border px-3 py-2.5 text-sm ${strict === value ? "border-navy bg-navy-50/60" : "border-seam-strong bg-raised hover:border-navy-300"}`}>
              <input type="radio" name="strict" className="mt-1 accent-[#172036]" checked={strict === value} onChange={() => { setStrict(value); upload.reset(); }} />
              <span><span className="block font-medium text-fg">{label}</span><span className="block text-xs text-muted">{text}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-primary" disabled={!file || tooBig || wrongType || upload.busy}
          onClick={async () => { const r = await upload.run(file); if (r) onUploaded(); }}>
          {upload.busy ? <Spinner /> : <CloudUpload className="h-4 w-4" aria-hidden="true" />}{upload.busy ? "Validating every row…" : "Validate and upload"}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => Data.downloadTemplate().catch(() => {})}>
          <Download className="h-4 w-4" aria-hidden="true" />Download template
        </button>
      </div>
      {upload.error && !report && <ErrorNote error={upload.error} title={upload.error.status === 413 ? "File too large" : "Upload failed"} />}
      {report && (
        <div className="space-y-5 border-t border-seam pt-5" aria-live="polite">
          <ValidationBanner report={report} accepted={Boolean(upload.result)} message={upload.result?.message || upload.error?.message} />
          {upload.result && report.valid_rows > 0 && (
            <p className="text-sm text-muted">Accepted rows are queued, not yet predicted. They join the live stream when they are processed below, in purchase-date order.</p>
          )}
          <Report report={report} />
        </div>
      )}
    </div>
  );
}

function ProcessQueue({ pending, canProcess, onDone }) {
  const [count, setCount] = useState(100);
  const action = useAction(() => Drift.processUploaded(Number(count)));
  const r = action.result;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">Queued records run through the live pipeline in purchase-date order: prediction, comparison with the actual category, detector update and, on confirmed drift, adaptation.</p>
      <p className="figure text-2xl text-navy">{num(pending)} <span className="text-sm font-normal text-muted">records waiting</span></p>
      {canProcess ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="block text-sm"><span className="mb-1 block text-xs text-muted">How many</span>
            <select className="input input-sm w-auto" value={count} onChange={(e) => setCount(e.target.value)}>
              {[10, 50, 100, 250, 500].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button type="button" className="btn btn-primary" disabled={!pending || action.busy} onClick={async () => { if (await action.run()) onDone(); }}>
            {action.busy && <Spinner />}{action.busy ? "Processing…" : "Process records"}
          </button>
        </div>
      ) : <p className="text-sm text-muted">Only administrators can process queued records.</p>}
      <ErrorNote error={action.error} />
      {r && (
        <Notice tone={r.drift_events?.length ? "drift" : "stable"} title={`Processed ${num(r.processed)} records`}>
          {num(r.correct)} predicted correctly; {num(r.remaining)} still waiting.
          {r.drift_events?.length > 0 && ` Drift confirmed ${r.drift_events.length} time(s); new model ${r.new_versions?.join(", ") || "not created"}.`} Active model: {r.model_version}.
        </Notice>
      )}
    </div>
  );
}

export default function DataManagement() {
  const { isAdmin } = useAuth();
  const meta = useMeta();
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ status: "", category: "", search: "" });
  const stats = useApi(() => Data.statistics(), []);
  const rules = useApi(() => Data.validation(), []);
  const uploads = useApi(() => Data.uploads({ page_size: 10 }), []);
  const records = useApi(() => Data.records({ ...filters, page, page_size: 20 }), [page, filters.status, filters.category, filters.search]);
  const refreshAll = () => { stats.reload({ silent: true }); uploads.reload({ silent: true }); records.reload({ silent: true }); };
  useLiveRefresh(refreshAll, "live", { events: new Set(["DATA_UPLOADED", "RECORDS_PROCESSED"]), delay: 500 });
  const s = stats.data;
  const mix = s ? Object.entries(s.by_target_category || {}).map(([category, n]) => ({ category, n })) : [];

  return (
    <>
      <PageHeader title="Data management"
        lede="Feed the live stream with labeled CSV files. Every row is validated before it can reach the model; re-uploaded rows are skipped; problems are reported, never silently fixed." />
      <ErrorNote error={stats.error} onRetry={() => stats.reload()} className="mb-6" />
      <div className="space-y-6">
        {s && (
          <Measures>
            <Measure label="Uploaded records" value={num(s.records.total)} sub={`${num(s.uploads.count)} upload${s.uploads.count === 1 ? "" : "s"}`} />
            <Measure label="Waiting" value={num(s.records.pending)} sub="Queued for the live stream" />
            <Measure label="Processed" value={num(s.records.processed)} sub="Predicted and scored" />
            <Measure label="Rows rejected" value={num(s.uploads.invalid_rows)} tone={s.uploads.invalid_rows ? "warning" : undefined} sub={`${num(s.uploads.duplicate_rows)} duplicates skipped`} />
            <Measure label="Average price" value={money(s.avg_price)} sub={s.avg_discount !== null ? `Average discount ${s.avg_discount}%` : undefined} />
          </Measures>
        )}
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Panel title="Upload a CSV file" description="1. Choose a file  2. Check the expected columns  3. Choose how to treat invalid rows  4. Validate">
            {isAdmin ? <Uploader rules={rules.data?.rules} onUploaded={refreshAll} />
              : <Empty title="Uploading is limited to administrators">You can review every upload, its validation report and the queued records here and on the Data validation page.</Empty>}
          </Panel>
          <div className="space-y-6">
            <Panel title="Queued records"><ProcessQueue pending={s?.records.pending || 0} canProcess={isAdmin} onDone={refreshAll} /></Panel>
            <Panel title="Uploaded records by actual category">
              {mix.length ? <PairedBars rows={mix} x="category" a={{ key: "n", name: "Records", color: C.ink }} fmt={num} height={220} />
                : <p className="text-sm text-muted">No uploaded records yet.</p>}
            </Panel>
          </div>
        </div>

        <Panel title="Upload history" description="Open a report on the Data validation page to see every rejected row." flush>
          <ErrorNote error={uploads.error} onRetry={() => uploads.reload()} className="m-4" />
          {uploads.data?.items?.length ? (
            <Table caption="Upload history">
              <thead><tr><th className="th">Upload</th><th className="th">File</th><th className="th">Result</th><th className="th">Rows</th>
                <th className="th">Accepted</th><th className="th">Rejected</th><th className="th">Duplicates</th><th className="th">When</th><th className="th" /></tr></thead>
              <tbody>
                {uploads.data.items.map((u) => (
                  <tr key={u.id}>
                    <td className="td tabular text-muted">#{u.id}</td><td className="td font-medium">{u.filename}</td>
                    <td className="td">{u.status === "accepted" ? <Badge tone="stable" icon>Accepted</Badge> : <Badge tone="drift" icon>Rejected</Badge>}</td>
                    <td className="td tabular">{num(u.total_rows)}</td><td className="td tabular">{num(u.valid_rows)}</td>
                    <td className="td tabular">{num(u.invalid_rows)}</td><td className="td tabular">{num(u.duplicate_rows)}</td>
                    <td className="td whitespace-nowrap text-muted" title={dateTime(u.created_at)}>{timeAgo(u.created_at)}</td>
                    <td className="td text-right"><Link to={`/app/validation?upload=${u.id}`} className="link text-sm">Report</Link></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : uploads.loading ? <Loading label="Loading uploads…" rows={2} className="px-5" />
            : <Empty title="Select a CSV file to begin validating data" icon={DatabaseZap}>Download the template, fill it with labeled purchases and upload it. Every upload and its report is listed here.</Empty>}
        </Panel>

        <Panel title="Uploaded records" flush>
          <div className="grid grid-cols-1 gap-3 border-b border-seam p-4 sm:grid-cols-3">
            <label className="block"><span className="mb-1 block text-xs text-muted">Status</span>
              <select className="input input-sm" value={filters.status} onChange={(e) => { setPage(1); setFilters({ ...filters, status: e.target.value }); }}>
                <option value="">Waiting and processed</option><option value="pending">Waiting</option><option value="processed">Processed</option>
              </select></label>
            <label className="block"><span className="mb-1 block text-xs text-muted">Actual category</span>
              <select className="input input-sm" value={filters.category} onChange={(e) => { setPage(1); setFilters({ ...filters, category: e.target.value }); }}>
                <option value="">Any</option>{meta.categories.map((c) => <option key={c}>{c}</option>)}
              </select></label>
            <label className="block"><span className="mb-1 block text-xs text-muted">Customer ID</span>
              <input className="input input-sm" placeholder="Press Enter to search"
                onKeyDown={(e) => e.key === "Enter" && (setPage(1), setFilters({ ...filters, search: e.currentTarget.value.trim() }))} /></label>
          </div>
          {records.loading && !records.data ? <Loading label="Loading records…" rows={4} className="px-5" />
            : records.error ? <ErrorNote error={records.error} onRetry={() => records.reload()} className="m-4" />
              : records.data?.items?.length ? (
                <>
                  <Table caption="Uploaded records">
                    <thead><tr><th className="th">Purchase date</th><th className="th">Customer</th><th className="th">Previous</th>
                      <th className="th">Season</th><th className="th">Price</th><th className="th">Discount</th><th className="th">Actual</th><th className="th">Status</th></tr></thead>
                    <tbody>
                      {records.data.items.map((r) => (
                        <tr key={r.id}>
                          <td className="td whitespace-nowrap">{dateTime(r.purchase_date)}</td><td className="td">{r.customer_id}</td>
                          <td className="td">{r.previous_category}</td><td className="td">{r.season}</td><td className="td tabular">{money(r.price)}</td>
                          <td className="td tabular">{r.discount}%</td><td className="td font-medium">{r.target_category}</td>
                          <td className="td">{r.status === "processed" ? <Badge tone="stable" icon>Processed</Badge> : <Badge icon>Waiting</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                  <Pagination page={records.data.page} pages={records.data.pages} total={records.data.total} onChange={setPage} />
                </>
              ) : <p className="px-5 py-5 text-sm text-muted">No records match. Rows that pass validation appear here after an upload.</p>}
        </Panel>
      </div>
    </>
  );
}
