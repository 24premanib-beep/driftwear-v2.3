import { Fragment, useState } from "react";
import { ChevronRight, RefreshCw, ScrollText, Server } from "lucide-react";
import { Badge, DefinitionList, Empty, ErrorNote, Loading, PageHeader, Pagination, Panel, SimulationChip, Table, ToneIcon } from "../components/ui";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Audit } from "../lib/endpoints";
import { dateTime, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";

const EMPTY = { action: "", actor: "", resource: "", severity: "", stream: "", date_from: "", date_to: "" };
const SEVERITY = { info: ["Info", "info"], warning: ["Warning", "warning"], critical: ["Critical", "drift"] };
const AUDIT_EVENTS = new Set(["DRIFT_DETECTED", "ADAPTATION_STARTED", "ADAPTATION_COMPLETED", "ADAPTATION_FAILED",
  "MODEL_VERSION_CREATED", "MODEL_ACTIVATED", "DETECTOR_CHANGED", "SIMULATION_RESET", "DATA_UPLOADED", "PIPELINE_ERROR"]);
const GROUPS = [["auth.*", "Sign-in and accounts"], ["prediction.*", "Predictions"], ["event.*", "Live events"], ["data.*", "Data uploads"],
  ["drift.*", "Drift detection"], ["model.*", "Models: retraining, activation, rollback"], ["config.*", "Configuration"], ["simulation.*", "Simulation"], ["user.*", "User management"]];

function toQuery(f, page) {
  return {
    page, page_size: 25, action: f.action || undefined, resource: f.resource || undefined, severity: f.severity || undefined,
    stream: f.stream || undefined, system: f.actor === "system" ? true : undefined,
    user_id: f.actor && f.actor !== "system" ? f.actor : undefined,
    date_from: f.date_from ? `${f.date_from}T00:00:00` : undefined, date_to: f.date_to ? `${f.date_to}T23:59:59` : undefined,
  };
}

function detailValue(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return <code className="break-all text-xs">{JSON.stringify(v)}</code>;
  return String(v);
}

export default function AuditLogs() {
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const facets = useApi(() => Audit.facets(), []);
  const logs = useApi(() => Audit.list(toQuery(filters, page)), [JSON.stringify(filters), page]);
  useLiveRefresh(() => { logs.reload({ silent: true }); facets.reload({ silent: true }); }, null, { delay: 1500, events: AUDIT_EVENTS });
  const set = (key) => (e) => { setPage(1); setOpen(null); setFilters({ ...filters, [key]: e.target.value }); };
  const f = facets.data;
  const data = logs.data;
  const active = Object.values(filters).filter(Boolean).length;
  const select = (key, label, options, any = "Any") => (
    <label className="block min-w-0"><span className="mb-1 block text-xs text-muted">{label}</span>
      <select className="input input-sm" value={filters[key]} onChange={set(key)}>
        <option value="">{any}</option>{options}
      </select>
    </label>
  );

  return (
    <>
      <PageHeader title="Audit logs"
        lede="Who did what and when, and every action the pipeline took on its own: drift detection, retraining, new versions, activations and rollbacks. Passwords, tokens and secrets are never recorded."
        actions={<button type="button" className="btn btn-secondary" onClick={() => logs.reload()}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh</button>} />
      <Panel flush>
        <div className="grid grid-cols-2 gap-3 border-b border-seam p-4 md:grid-cols-4 xl:grid-cols-7">
          {select("action", "Action", <>
            <optgroup label="Groups">{GROUPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>
            {f?.actions?.length > 0 && <optgroup label="Exact action">{f.actions.map((a) => <option key={a} value={a}>{a}</option>)}</optgroup>}
          </>, "All actions")}
          {select("actor", "Who", <>
            <option value="system">The pipeline (system)</option>
            {f?.users?.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.email}</option>)}
          </>, "Everyone")}
          {select("resource", "Resource", f?.resources?.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>))}
          {select("severity", "Severity", (f?.severities || ["info", "warning", "critical"]).map((s) => <option key={s} value={s}>{SEVERITY[s]?.[0] || s}</option>))}
          {select("stream", "Stream", <><option value="live">Live</option><option value="simulation">Simulation</option></>)}
          <label className="block min-w-0"><span className="mb-1 block text-xs text-muted">From</span><input type="date" className="input input-sm" value={filters.date_from} onChange={set("date_from")} /></label>
          <label className="block min-w-0"><span className="mb-1 block text-xs text-muted">To</span><input type="date" className="input input-sm" value={filters.date_to} onChange={set("date_to")} /></label>
          {active > 0 && <div className="col-span-2 md:col-span-4 xl:col-span-7"><button type="button" className="btn btn-quiet btn-sm" onClick={() => { setFilters(EMPTY); setPage(1); }}>Clear {active} filter{active > 1 ? "s" : ""}</button></div>}
        </div>
        <ErrorNote error={logs.error} onRetry={() => logs.reload()} className="m-4" />
        {logs.loading && !data ? <Loading label="Loading audit entries…" rows={6} className="px-5" /> : data?.items?.length ? (
          <>
            <Table caption="Audit entries, newest first">
              <thead><tr><th className="th w-8"><span className="sr-only">Expand</span></th><th className="th">When</th><th className="th">Severity</th><th className="th">Action</th>
                <th className="th">Who</th><th className="th">Resource</th><th className="th">Stream</th><th className="th">IP address</th></tr></thead>
              <tbody>
                {data.items.map((it) => {
                  const [sev, t] = SEVERITY[it.severity] || [it.severity, "neutral"];
                  const isOpen = open === it.id;
                  return (
                    <Fragment key={it.id}>
                      <tr className="row-link" onClick={() => setOpen(isOpen ? null : it.id)}>
                        <td className="td"><button type="button" className="rounded text-muted hover:text-fg" aria-expanded={isOpen} aria-label={`Details of ${it.action}`}
                          onClick={(e) => { e.stopPropagation(); setOpen(isOpen ? null : it.id); }}>
                          <ChevronRight className={`h-4 w-4 transition-transform ${isOpen ? "rotate-90" : ""}`} aria-hidden="true" /></button></td>
                        <td className="td whitespace-nowrap text-muted" title={dateTime(it.created_at)}>{timeAgo(it.created_at)}</td>
                        <td className="td"><span className="inline-flex items-center gap-1.5 text-sm"><ToneIcon tone={t} className="h-3.5 w-3.5" />{sev}</span></td>
                        <td className="td"><code className="text-[12.5px] text-fg">{it.action}</code></td>
                        <td className="td">{it.user ? <span title={it.user.email}>{it.actor}</span> : <span className="inline-flex items-center gap-1.5 text-muted"><Server className="h-3.5 w-3.5" aria-hidden="true" />Pipeline</span>}</td>
                        <td className="td text-muted">{it.resource?.replace("_", " ")}{it.resource_id ? <span className="text-fg"> {it.resource_id}</span> : ""}</td>
                        <td className="td">{it.stream === "simulation" ? <SimulationChip /> : it.stream ? <Badge tone="navy">Live</Badge> : <span className="text-faint">—</span>}</td>
                        <td className="td text-muted">{it.ip_address || "—"}</td>
                      </tr>
                      {isOpen && (
                        <tr><td colSpan={8} className="border-b border-seam bg-canvas/60 px-6 py-4">
                          <DefinitionList columns={3} items={[["Recorded", dateTime(it.created_at)], ["Entry", `#${it.id}`],
                            ...Object.entries(it.details || {}).map(([k, v]) => [k.replace(/_/g, " "), detailValue(v)])]} />
                          {!Object.keys(it.details || {}).length && <p className="mt-2 text-sm text-muted">No further details were recorded for this action.</p>}
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </Table>
            <Pagination page={data.page} pages={data.pages} total={data.total} onChange={(p) => { setPage(p); setOpen(null); }} noun="entries" />
          </>
        ) : <Empty title={active ? "No audit entries match these filters" : "No audit entries yet"} icon={ScrollText}
          action={active ? <button type="button" className="btn btn-secondary" onClick={() => setFilters(EMPTY)}>Clear filters</button> : null}>
          Sign-ins, uploads, predictions, model changes and drift events are recorded as they happen.</Empty>}
      </Panel>
    </>
  );
}
