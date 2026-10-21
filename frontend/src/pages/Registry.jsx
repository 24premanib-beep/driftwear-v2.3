import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, GitCompareArrows, RotateCcw, Tags } from "lucide-react";
import { ImportanceBars, VersionStrip } from "../components/charts";
import { DriftLink } from "../components/insights";
import { Badge, ConfirmDialog, DefinitionList, Empty, ErrorNote, Field, Ident, Loading, Notice, PageHeader, Panel,
  SimulationBanner, StreamSwitch, Table, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Models } from "../lib/endpoints";
import { bytes, dateTime, KIND_LABELS, num, pct, pts, timeAgo } from "../lib/format";
import { useAction, useApi, useQueryParam, useStreamParam } from "../lib/hooks";
import { buildLineage, compareVersions, defaultComparison, isRollback } from "../lib/lineage";

const KIND_TONE = { initial: "neutral", drift: "drift", refresh: "adapted", manual: "plum" };
const HISTORY = { trained: ["Initial training", "neutral"], adapted: ["Adaptation", "adapted"], rollback: ["Rollback", "warning"], activate: ["Activation", "navy"] };
const MIN_REASON = 3;

/**
 * Confirmation for making a stored version active. Older than the active version = rollback (POST /api/models/rollback);
 * newer = activation. A reason is required for rollbacks. The dialog closes only when the server confirms.
 */
function ActivationDialog({ stream, target, active, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const rollback = isRollback(target.version, active);
  const run = useAction(() => (rollback ? Models.rollback(stream, target.version, reason.trim())
    : Models.activate(stream, target.version, reason.trim() || null)));
  const reasonOk = !rollback || reason.trim().length >= MIN_REASON;
  return (
    <ConfirmDialog open danger={rollback} busy={run.busy} confirmDisabled={!reasonOk}
      title={rollback ? `Roll back the ${stream} model to ${target.version}?` : `Activate ${target.version} on the ${stream} stream?`}
      confirmLabel={run.busy ? "Verifying and activating…" : rollback ? `Roll back to ${target.version}` : `Activate ${target.version}`}
      onCancel={onClose} onConfirm={async () => { const r = await run.run(); if (r) onDone(r); }}>
      <div className="flex items-center gap-3 rounded-md bg-canvas px-4 py-3">
        <div><div className="text-xs text-muted">Active now</div><VersionTag version={active} active size="lg" /></div>
        <span className="text-faint" aria-hidden="true">→</span>
        <div><div className="text-xs text-muted">{rollback ? "Restore" : "Activate"}</div><VersionTag version={target.version} size="lg" /></div>
        <div className="ml-auto text-right text-xs text-muted">{KIND_LABELS[target.kind]}<br />created {timeAgo(target.created_at)}</div>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-fg/85">
        <li>Every new prediction on the {stream} stream will be made by {target.version}.</li>
        <li>The stored file is verified against its SHA-256 checksum before it is loaded. If it does not match, nothing changes.</li>
        <li>The drift detector restarts for {target.version}{rollback ? `, and scheduled refreshes of ${active} are cancelled` : ""}.</li>
        <li>{active} and every other version stay in the registry. Nothing is deleted.</li>
        <li>Your name, the time and the reason are recorded in the activation history and the audit log; connected users are notified.</li>
      </ul>
      <div className="hairlines rounded-md"><dl className="hairlines-inner grid-cols-3 text-center">
        <div className="px-2 py-2"><dt className="text-xs text-muted">Validation accuracy</dt><dd className="font-semibold tabular">{pct(target.accuracy)}</dd></div>
        <div className="px-2 py-2"><dt className="text-xs text-muted">Validation F1</dt><dd className="font-semibold tabular">{pct(target.f1_score)}</dd></div>
        <div className="px-2 py-2"><dt className="text-xs text-muted">Live accuracy</dt><dd className="font-semibold tabular">{target.live_metrics ? `${pct(target.live_metrics.accuracy)} (${num(target.live_metrics.n)})` : "N/A"}</dd></div>
      </dl></div>
      <p className="text-xs text-muted">Live accuracy was measured while {target.version} was active, on the customers of that period; it does not predict how it will do on today's customers.</p>
      <Field label={rollback ? "Reason for the rollback" : "Reason"} optional={!rollback} htmlFor="activation-reason"
        error={rollback && reason && !reasonOk ? `Write at least ${MIN_REASON} characters.` : undefined}
        hint={rollback ? "Required. Stored with the rollback in the history and the audit log." : "Stored in the activation history."}>
        <textarea id="activation-reason" className="input h-20" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder={`e.g. ${active} misclassifies Outerwear since the festive sale`} />
      </Field>
      <ErrorNote error={run.error} title={run.error?.status === 503 ? "The model file could not be loaded; nothing was changed" : run.error?.status === 409 ? "Not possible for this version" : undefined} />
    </ConfirmDialog>
  );
}

function RollbackPanel({ items, active, onAsk }) {
  const older = items.filter((v) => isRollback(v.version, active)).sort((a, b) => compareVersions(b.version, a.version));
  const parent = items.find((v) => v.version === active)?.parent_version;
  const fallback = older.some((v) => v.version === parent) ? parent : older[0]?.version;
  const [target, setTarget] = useState("");
  const chosen = older.some((v) => v.version === target) ? target : fallback;
  if (!older.length) return <p className="text-sm text-muted">{active} is the oldest version on this stream, so there is nothing to roll back to.</p>;
  const t = items.find((v) => v.version === chosen);
  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
      <div><div className="mb-1 text-xs text-muted">Active now</div><VersionTag version={active} active size="lg" /></div>
      <span className="pb-1 text-xl text-faint" aria-hidden="true">→</span>
      <label className="block text-sm"><span className="mb-1 block text-xs text-muted">Restore an earlier version</span>
        <select className="input w-auto" value={chosen} onChange={(e) => setTarget(e.target.value)}>
          {older.map((v) => <option key={v.version} value={v.version}>{v.version} · {KIND_LABELS[v.kind]}{v.version === parent ? " · the version it replaced" : ""}</option>)}
        </select>
      </label>
      <button type="button" className="btn btn-danger" onClick={() => onAsk(t)}><RotateCcw className="h-4 w-4" aria-hidden="true" />Review rollback…</button>
      {t && <p className="basis-full text-xs text-muted">{t.version}: validation accuracy {pct(t.accuracy)}{t.live_metrics ? `, live ${pct(t.live_metrics.accuracy)} on ${num(t.live_metrics.n)} outcomes` : ", no live outcomes"}. Only older versions can be rolled back to; the server checks this too.</p>}
    </div>
  );
}

function ActivationHistory({ stream, refreshKey }) {
  const h = useApi(() => Models.activations(stream), [stream, refreshKey]);
  if (h.loading && !h.data) return <Loading label="Loading activation history…" rows={2} className="px-5" />;
  if (h.error) return <ErrorNote error={h.error} onRetry={() => h.reload()} className="m-4" />;
  const rows = h.data?.timeline || [];
  if (!rows.length) return <p className="px-5 py-5 text-sm text-muted">No activations recorded yet.</p>;
  return (
    <Table caption="Activation and rollback history">
      <thead><tr><th className="th">When</th><th className="th">Event</th><th className="th">Change</th><th className="th">By</th><th className="th">Reason or trigger</th><th className="th">At outcome</th></tr></thead>
      <tbody>
        {rows.map((r, i) => {
          const [label, t] = HISTORY[r.action] || [r.action, "neutral"];
          return (
            <tr key={`${r.timestamp}-${r.to_version}-${i}`}>
              <td className="td whitespace-nowrap text-muted" title={dateTime(r.timestamp)}>{timeAgo(r.timestamp)}</td>
              <td className="td"><Badge tone={t}>{label}{r.kind && r.action === "adapted" ? `: ${KIND_LABELS[r.kind]?.toLowerCase()}` : ""}</Badge></td>
              <td className="td whitespace-nowrap">{r.from_version ? <><VersionTag version={r.from_version} /> <span className="text-faint">→</span> </> : null}<VersionTag version={r.to_version} /></td>
              <td className="td">{r.actor}</td>
              <td className="td max-w-[320px] text-sm text-muted">{r.reason || "—"}</td>
              <td className="td tabular text-muted">{r.at_step === null || r.at_step === undefined || r.at_step < 0 ? "Before the stream" : `#${num(r.at_step + 1)}`}</td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function MetricBlock({ title, note, m, n }) {
  return (
    <div>
      <h4 className="text-sm font-medium text-fg">{title}</h4>
      <p className="text-xs text-muted">{note}</p>
      {m ? (
        <div className="hairlines mt-2 rounded-md"><dl className="hairlines-inner grid-cols-5 text-center">
          {[["Accuracy", m.accuracy], ["Precision", m.precision], ["Recall", m.recall], ["F1", m.f1 ?? m.f1_score], ["Error rate", m.error_rate ?? (m.accuracy !== null && m.accuracy !== undefined ? 1 - m.accuracy : null)]].map(([k, v]) => (
            <div key={k} className="px-1 py-2"><dt className="text-[11px] text-muted">{k}</dt><dd className="text-sm font-semibold tabular">{pct(v)}</dd></div>
          ))}
        </dl></div>
      ) : <p className="mt-2 rounded-md bg-canvas px-3 py-2 text-sm text-muted">No live outcomes yet: this version has not been scored on real purchases.</p>}
      {n !== undefined && m && <p className="mt-1 text-xs text-muted">{num(n)} outcomes</p>}
    </div>
  );
}

function VersionDetail({ stream, version, activeVersion, onAsk }) {
  const { isAdmin } = useAuth();
  const detail = useApi(() => Models.get(stream, version), [stream, version, activeVersion]);
  const v = detail.data;
  if (detail.loading && !v) return <Loading label={`Loading ${version}…`} rows={4} />;
  if (detail.error) return <ErrorNote error={detail.error} onRetry={() => detail.reload()} />;
  if (!v) return null;
  const rollback = isRollback(v.version, activeVersion);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <VersionTag version={v.version} active={v.is_active} size="lg" />
          <div className="flex flex-wrap gap-1.5"><Badge tone={KIND_TONE[v.kind]}>{KIND_LABELS[v.kind]}</Badge>{v.is_active ? <Badge tone="navy">Active</Badge> : <Badge>Inactive</Badge>}</div>
        </div>
        {isAdmin && !v.is_active && (
          <button type="button" className={rollback ? "btn btn-danger" : "btn btn-primary"} onClick={() => onAsk(v)}>
            {rollback && <RotateCcw className="h-4 w-4" aria-hidden="true" />}{rollback ? `Roll back to ${v.version}…` : `Activate ${v.version}…`}
          </button>
        )}
      </div>
      {v.drift_event && (
        <Notice tone="drift" title={`Created by ${v.drift_event.event_key}`}>
          {v.drift_event.detector} confirmed drift ({v.drift_event.severity} severity) at outcome #{v.drift_event.stream_step + 1}. Accuracy had fallen from {pct(v.drift_event.accuracy_stable)} to {pct(v.drift_event.accuracy_degraded)}{" "}
          before this version replaced {v.drift_event.previous_model_version}. <DriftLink eventKey={v.drift_event.event_key} stream={stream}>See the recovery</DriftLink>
        </Notice>
      )}
      <DefinitionList items={[
        ["Why it exists", v.trigger], ["Replaced", v.parent_version ? <VersionTag key="p" version={v.parent_version} /> : "Nothing (first model)"],
        ["Created", `${dateTime(v.created_at)}${v.created_step >= 0 ? ` at outcome #${v.created_step + 1}` : ", before the stream (historical data)"}`],
        ["Training window", `${num(v.training_records)} records${v.window_start !== null ? `, outcomes #${v.window_start + 1}–#${v.window_end + 1}` : ""}`],
        ["Data period", v.data_period], ["Detector at creation", v.detector],
      ]} />
      <MetricBlock title="Validation" note="Out-of-fold on its own training window. Small windows give low, noisy scores; this is not live performance." m={v} />
      <MetricBlock title="Live" note="Measured on real outcomes while this version was active." m={v.live_metrics} n={v.live_metrics?.n} />
      <DefinitionList items={[
        ["Algorithm", v.model_type], ["Training-set accuracy", pct(v.train_accuracy)],
        ["Model file", bytes(v.model_size)], ["Checksum (SHA-256)", <Ident key="c" value={v.checksum ? `${v.checksum.slice(0, 16)}…` : null} copy={false} />],
      ]} />
      <section>
        <h4 className="mb-2 text-sm font-medium text-fg">What this version relies on</h4>
        <ImportanceBars items={v.feature_importance} />
      </section>
    </div>
  );
}

function Lineage({ items, selected, onSelect }) {
  const nodes = buildLineage(items);
  return (
    <ol className="space-y-0.5" aria-label="Model lineage">
      {nodes.map((n) => (
        <li key={n.version} style={{ paddingLeft: `${Math.min(n.depth, 6) * 16}px` }}>
          <button type="button" onClick={() => onSelect(n.version)} aria-current={selected === n.version ? "true" : undefined}
            className={`flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-sm ${selected === n.version ? "bg-plum-50 ring-1 ring-inset ring-plum/25" : "hover:bg-navy-50/70"}`}>
            {n.depth > 0 && <span className="text-faint" aria-hidden="true">└</span>}
            <VersionTag version={n.version} active={n.is_active} />
            <span className="min-w-0 flex-1 truncate text-muted">{n.reason}</span>
            <span className="text-xs tabular text-muted" title="Validation accuracy (out-of-fold)">{pct(n.accuracy, 0)}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function CompareRow({ label, a, b, diff, lowerIsBetter = false, fmt = pct }) {
  const better = diff?.better;
  const mark = (side) => (better === side
    ? <ArrowUp className="ml-1 inline h-3.5 w-3.5 text-stable-ink" aria-label="better" />
    : better && better !== side ? <ArrowDown className="ml-1 inline h-3.5 w-3.5 text-drift-ink" aria-label="worse" /> : null);
  return (
    <tr>
      <td className="td text-muted">{label}</td>
      <td className={`td tabular ${better === "a" ? "font-semibold" : ""}`}>{fmt(a)}{mark("a")}</td>
      <td className={`td tabular ${better === "b" ? "font-semibold" : ""}`}>{fmt(b)}{mark("b")}</td>
      <td className="td tabular text-muted">{diff?.delta === null || diff?.delta === undefined ? "—" : `${pts(diff.delta)}${lowerIsBetter ? " (lower is better)" : ""}`}</td>
    </tr>
  );
}

function Compare({ stream, items, pair, setPair }) {
  const [a, b] = pair;
  const cmp = useApi(() => (a && b && a !== b ? Models.compare(stream, a, b) : Promise.resolve(null)), [stream, a, b]);
  const c = cmp.data;
  const options = [...items].sort((x, y) => compareVersions(x.version, y.version)).map((v) => v.version);
  const rows = (key) => [["accuracy", "Accuracy"], ["precision", "Precision"], ["recall", "Recall"], ["f1", "F1"], ["error_rate", "Error rate"]]
    .map(([m, label]) => <CompareRow key={`${key}-${m}`} label={label} a={c?.a?.[key]?.[m]} b={c?.b?.[key]?.[m]} diff={c?.diff?.[key]?.[m]} lowerIsBetter={m === "error_rate"} />);
  const head = (text) => <tr><td colSpan={4} className="border-b border-seam bg-canvas/60 px-3 pb-1.5 pt-3 text-xs font-medium text-navy">{text}</td></tr>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="block"><span className="mb-1 block text-xs text-muted">Model A</span>
          <select className="input input-sm w-auto" value={a || ""} onChange={(e) => setPair([e.target.value, b])}>{options.map((o) => <option key={o}>{o}</option>)}</select></label>
        <label className="block"><span className="mb-1 block text-xs text-muted">Model B</span>
          <select className="input input-sm w-auto" value={b || ""} onChange={(e) => setPair([a, e.target.value])}>{options.map((o) => <option key={o}>{o}</option>)}</select></label>
        <button type="button" className="btn btn-quiet btn-sm" onClick={() => setPair([b, a])}>Swap</button>
      </div>
      {a === b ? <p className="text-sm text-muted">Choose two different versions.</p> : (
        <>
          <ErrorNote error={cmp.error} onRetry={() => cmp.reload()} />
          {cmp.loading && !c ? <Loading label="Comparing versions…" rows={3} /> : c && (
            <>
              <Table caption={`${c.a.version} compared with ${c.b.version}`}>
                <thead><tr><th className="th" /><th className="th"><VersionTag version={c.a.version} active={c.a.is_active} /></th><th className="th"><VersionTag version={c.b.version} active={c.b.is_active} /></th><th className="th">B − A</th></tr></thead>
                <tbody>
                  {head("Validation: out-of-fold on each version's own training window")}
                  {rows("validation")}
                  {head(`Live: measured on the outcomes each version served (${c.a.live ? num(c.a.live.n) : 0} and ${c.b.live ? num(c.b.live.n) : 0})`)}
                  {rows("live")}
                  {head("Provenance")}
                  {[["Why it exists", (v) => v.trigger], ["Kind", (v) => KIND_LABELS[v.kind]], ["Replaced", (v) => v.parent_version || "—"],
                    ["Training records", (v) => num(v.training_records)], ["Data period", (v) => v.data_period], ["Created", (v) => dateTime(v.created_at)]].map(([label, fn]) => (
                    <tr key={label}><td className="td text-muted">{label}</td><td className="td">{fn(c.a)}</td><td className="td">{fn(c.b)}</td><td className="td" /></tr>
                  ))}
                </tbody>
              </Table>
              <p className="text-xs text-muted">{c.note} The arrow marks the better value for each metric.</p>
            </>
          )}
        </>
      )}
    </div>
  );
}

export default function Registry() {
  const { isAdmin } = useAuth();
  const [stream, setStream] = useStreamParam(true);
  const [selected, setSelected] = useQueryParam("version", "");
  const [compareParam, setCompareParam] = useQueryParam("compare", "");
  const [pending, setPending] = useState(null);
  const [done, setDone] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const models = useApi(() => Models.list(stream), [stream]);
  const refresh = () => { models.reload({ silent: true }); setRefreshKey((k) => k + 1); };
  useLiveRefresh(refresh, stream, { events: new Set(["MODEL_VERSION_CREATED", "MODEL_ACTIVATED", "SIMULATION_RESET", "PERFORMANCE_UPDATED"]) });
  const items = models.data?.items || [];
  const active = items.find((v) => v.is_active)?.version;
  const current = selected && items.some((v) => v.version === selected) ? selected : active;
  const fromParam = compareParam.split(",").filter((x) => items.some((v) => v.version === x));
  const pair = fromParam.length === 2 ? fromParam : defaultComparison(items, current);
  useEffect(() => { setDone(null); }, [stream]);
  const ask = (v) => setPending(items.find((x) => x.version === v.version) || v);

  return (
    <>
      <PageHeader title="Model registry"
        lede="Every version is kept: the checksummed model file, why it was created, how it performed and what it replaced. Compare any two versions; administrators can roll back."
        actions={<StreamSwitch stream={stream} onChange={(s) => { setSelected(""); setCompareParam(""); setStream(s); }} />} />
      {stream === "simulation" && <SimulationBanner />}
      <ErrorNote error={models.error} onRetry={() => models.reload()} className="mb-6" />
      {pending && active && (
        <ActivationDialog key={pending.version} stream={stream} target={pending} active={active} onClose={() => setPending(null)}
          onDone={(r) => { setPending(null); setDone(r); setSelected(r.active_version); refresh(); }} />
      )}
      {models.loading && !models.data ? <Loading label="Loading model versions…" rows={5} /> : items.length ? (
        <div className="space-y-6">
          {done && <Notice tone="adapted" title={done.rollback ? "Rollback confirmed by the server" : "Activation confirmed by the server"}>
            {done.message}{done.reason ? ` Reason recorded: “${done.reason}”.` : ""}</Notice>}
          {isAdmin && (
            <Panel title="Roll back the active model" description="Restore an earlier version if the current one performs badly. You will review the change before anything happens.">
              <RollbackPanel items={items} active={active} onAsk={ask} />
            </Panel>
          )}

          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <div className="space-y-6">
              <Panel title="Lineage" description="Each version under the one it replaced. Percentages are validation accuracy.">
                <Lineage items={items} selected={current} onSelect={setSelected} />
              </Panel>
              <Panel title="Along the stream" description="Which version served which outcomes">
                <VersionStrip versions={items} totalSteps={Math.max(...items.map((v) => v.created_step + 1), 1)} onSelect={setSelected} selected={current} />
              </Panel>
            </div>
            <Panel title="Version detail">
              {current ? <VersionDetail key={`${stream}-${current}`} stream={stream} version={current} activeVersion={active} onAsk={ask} />
                : <p className="text-sm text-muted">Select a version.</p>}
            </Panel>
          </div>

          <Panel title="Compare two versions" description="Validation and live metrics are shown separately and never mixed."
            actions={<GitCompareArrows className="h-4 w-4 text-faint" aria-hidden="true" />}>
            {items.length > 1 ? <Compare stream={stream} items={items} pair={pair} setPair={(p) => setCompareParam(p.join(","))} />
              : <Empty title="No additional model versions to compare">A comparison becomes available after the first adaptation or retrain.</Empty>}
          </Panel>

          <Panel title="Activation and rollback history" description="Which version became active when, who did it and why. Built from stored records only." flush>
            <ActivationHistory stream={stream} refreshKey={refreshKey} />
          </Panel>
        </div>
      ) : <Empty title="No model versions yet" icon={Tags}>The server trains v1.0 when it starts. If this stays empty, check the API logs.</Empty>}
    </>
  );
}
