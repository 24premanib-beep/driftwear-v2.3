import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { History as HistoryIcon, Search } from "lucide-react";
import { ProbabilityBars } from "../components/charts";
import { ExplanationPanel } from "../components/insights";
import { Badge, DefinitionList, Disclosure, Drawer, Empty, ErrorNote, Field, Ident, Loading, Notice, PageHeader, Pagination, Panel,
  SimulationBanner, Spinner, StateBadge, StreamSwitch, Table, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Predictions } from "../lib/endpoints";
import { dateTime, money, pct, SOURCE_LABELS, timeAgo } from "../lib/format";
import { useAction, useApi, useStreamParam } from "../lib/hooks";
import { useMeta } from "../lib/meta";
import { OutcomeSummary } from "./Predict";

const FILTER_KEYS = ["search", "predicted", "actual", "correct", "labeled", "model_version", "source", "date_from", "date_to"];

function resultBadge(it) {
  if (it.is_correct === null || it.is_correct === undefined) return <Badge icon>Awaiting outcome</Badge>;
  return it.is_correct ? <Badge tone="correct" icon>Correct</Badge> : <Badge tone="wrong" icon>Wrong</Badge>;
}

function RecordOutcome({ item, categories, onDone }) {
  const [actual, setActual] = useState("");
  const action = useAction(() => Predictions.recordOutcome(item.id, actual));
  if (action.result) return <OutcomeSummary outcome={action.result} predictedVersion={item.model_version} />;
  return (
    <div className="rounded-md border border-dashed border-seam-strong bg-canvas/50 p-4">
      <p className="text-sm font-medium text-fg">Waiting for the actual category</p>
      <p className="mt-0.5 text-sm text-muted">Its accuracy is unknown until you record what the customer bought.</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label="Actual category" htmlFor={`h-actual-${item.id}`} className="min-w-[180px] flex-1">
          <select id={`h-actual-${item.id}`} className="input" value={actual} onChange={(e) => setActual(e.target.value)}>
            <option value="">Choose what was bought</option>{categories.map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>
        <button type="button" className="btn btn-primary" disabled={!actual || action.busy} onClick={async () => { if (await action.run()) onDone(); }}>
          {action.busy && <Spinner />}Record outcome
        </button>
      </div>
      <ErrorNote error={action.error} className="mt-3" />
    </div>
  );
}

function Detail({ item, onClose, onChanged, canRecord }) {
  const meta = useMeta();
  const f = item.features || {};
  return (
    <Drawer open title={`${item.predicted_category}`} onClose={onClose}
      subtitle={<span className="flex flex-wrap items-center gap-2">Prediction <Ident value={item.id} prefix="#" /> by <VersionTag version={item.model_version} /> · {SOURCE_LABELS[item.source] || item.source}</span>}>
      <div className="space-y-6">
        {item.stream === "simulation" && <Notice tone="neutral" title="Simulation record">Synthetic data from the simulation stream, not a customer purchase.</Notice>}
        {item.actual_category ? (
          <Notice tone={item.is_correct ? "stable" : "warning"} title={item.is_correct ? `Correct: the customer bought ${item.actual_category}` : `Wrong: the customer bought ${item.actual_category}`}>
            Outcome #{item.step + 1} on the {item.stream} stream, recorded {dateTime(item.outcome_at)}. Detector after this outcome: {item.detector_status?.toLowerCase() || "—"}.
          </Notice>
        ) : canRecord ? <RecordOutcome item={item} categories={meta.categories} onDone={onChanged} />
          : <Notice tone="neutral" title="Awaiting the actual category">Accuracy is unknown until the outcome is recorded.</Notice>}
        {item.rescored && (
          <Notice tone="adapted" title={`Re-scored by ${item.scored_version} for drift monitoring`}>
            The model was replaced between this prediction and its outcome. For the error stream the purchase was scored again by the model active at outcome time,
            {" "}{item.scored_version}. The prediction stored here, by {item.model_version}, was not changed.
          </Notice>
        )}
        <section>
          <h3 className="mb-2 text-sm font-semibold text-fg">Probability for each category</h3>
          <ProbabilityBars probabilities={item.probabilities} predicted={item.predicted_category} categories={meta.categories} />
        </section>
        <Disclosure summary="Why this prediction?" defaultOpen={Boolean(item.explanation)}>
          <ExplanationPanel explanation={item.explanation} />
        </Disclosure>
        <Disclosure summary="Purchase and record details">
          <DefinitionList items={[
            ["Customer", f.Customer_ID || "Not given"], ["Purchase date", f.Purchase_Date],
            ["Previous category", f.Previous_Category], ["Preference", f.Customer_Preference],
            ["Orders so far", f.Purchase_Frequency], ["Days since last order", f.Recency],
            ["Month and season", `${f.Month} · ${f.Season}`], ["Price and discount", `${money(f.Price)} · ${f.Discount}% off`],
            f.Trend && ["Trend (simulation label)", f.Trend],
            ["Event ID", item.event_id ? <Ident key="e" value={item.event_id} /> : "None"],
            ["Detector when predicted", <StateBadge key="s" status={item.status_at_prediction} size="sm" />],
            ["Frozen v1.0 predicted", item.baseline_prediction],
            ["Predicted at", dateTime(item.created_at)], ["Outcome recorded", dateTime(item.outcome_at)],
          ]} />
        </Disclosure>
      </div>
    </Drawer>
  );
}

export default function History() {
  const { isStaff, user } = useAuth();
  const meta = useMeta();
  const [stream, setStream] = useStreamParam(isStaff);
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState(null);
  const filters = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) || ""]));
  const page = Number(params.get("page") || 1);
  const active = FILTER_KEYS.filter((k) => filters[k]).length;

  const { data, error, loading, reload } = useApi(() => Predictions.list({
    ...filters, stream, page, page_size: 25,
    date_from: filters.date_from ? `${filters.date_from}T00:00:00` : "", date_to: filters.date_to ? `${filters.date_to}T23:59:59` : "",
  }), [stream, page, ...FILTER_KEYS.map((k) => filters[k])]);
  useLiveRefresh(() => reload({ silent: true }), stream, { delay: 1500 });

  const update = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };
  const clear = () => {
    const next = new URLSearchParams();
    if (stream === "simulation") next.set("stream", "simulation");
    setParams(next, { replace: true });
  };
  const select = (key, label, options) => (
    <label className="block min-w-0">
      <span className="mb-1 block text-xs text-muted">{label}</span>
      <select className="input input-sm" value={filters[key]} onChange={(e) => update(key, e.target.value)}>
        <option value="">Any</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
  const cats = meta.categories.map((c) => [c, c]);
  const sources = stream === "simulation" ? [["simulation", "Simulation"]] : [["api", "Prediction form"], ["event", "Live event"], ["upload", "CSV upload"]];
  const canRecord = (it) => it.stream === "live" && (isStaff ? user?.role === "admin" || it.user_id === user?.id : it.user_id === user?.id);

  return (
    <>
      <PageHeader title="Prediction history"
        lede={isStaff ? "Every stored prediction with its model version, outcome and explanation. Open one to see why the model chose it and how it was scored."
          : "Your predictions, their outcomes and why the model chose them. Record an actual category here when you learn it."}
        actions={isStaff && <StreamSwitch stream={stream} onChange={(v) => { setSelected(null); setStream(v); }} />} />
      {stream === "simulation" && <SimulationBanner />}
      <Panel flush>
        <div className="grid grid-cols-2 gap-3 border-b border-seam p-4 md:grid-cols-4 xl:grid-cols-8">
          <label className="col-span-2 block min-w-0">
            <span className="mb-1 block text-xs text-muted">Search</span>
            <span className="relative block">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-faint" aria-hidden="true" />
              <input key={`s-${filters.search}`} className="input input-sm pl-8" placeholder="Customer, prediction or event ID"
                defaultValue={filters.search} onKeyDown={(e) => e.key === "Enter" && update("search", e.currentTarget.value.trim())}
                onBlur={(e) => update("search", e.target.value.trim())} />
            </span>
          </label>
          {select("labeled", "Outcome", [["true", "Has outcome"], ["false", "Awaiting outcome"]])}
          {select("correct", "Result", [["true", "Correct"], ["false", "Wrong"]])}
          {select("predicted", "Predicted", cats)}
          {select("actual", "Actual", cats)}
          {select("source", "Source", sources)}
          <label className="block min-w-0">
            <span className="mb-1 block text-xs text-muted">Model version</span>
            <input key={`m-${filters.model_version}`} className="input input-sm" placeholder="e.g. v2.0" defaultValue={filters.model_version}
              onKeyDown={(e) => e.key === "Enter" && update("model_version", e.currentTarget.value.trim())} onBlur={(e) => update("model_version", e.target.value.trim())} />
          </label>
          <label className="block min-w-0"><span className="mb-1 block text-xs text-muted">From</span>
            <input type="date" className="input input-sm" value={filters.date_from} onChange={(e) => update("date_from", e.target.value)} /></label>
          <label className="block min-w-0"><span className="mb-1 block text-xs text-muted">To</span>
            <input type="date" className="input input-sm" value={filters.date_to} onChange={(e) => update("date_to", e.target.value)} /></label>
          <div className="col-span-2 flex items-end md:col-span-2 xl:col-span-6">
            {active > 0 && <button type="button" className="btn btn-quiet btn-sm" onClick={clear}>Clear {active} filter{active > 1 ? "s" : ""}</button>}
          </div>
        </div>
        <ErrorNote error={error} onRetry={() => reload()} className="m-4" />
        {loading && !data ? <Loading label="Loading predictions…" rows={6} className="px-5" /> : data?.items?.length ? (
          <>
            <Table caption="Predictions">
              <thead>
                <tr>
                  <th className="th">#</th><th className="th">Made</th><th className="th">Customer</th><th className="th">Predicted</th>
                  <th className="th">Actual</th><th className="th">Result</th><th className="th">Model</th><th className="th">Source</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((it) => (
                  <tr key={it.id} className="row-link" onClick={() => setSelected(it)} tabIndex={0}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelected(it))}
                    aria-label={`Prediction ${it.id}: ${it.predicted_category}`}>
                    <td className="td tabular text-muted">{it.id}</td>
                    <td className="td whitespace-nowrap text-muted" title={dateTime(it.created_at)}>{timeAgo(it.created_at)}</td>
                    <td className="td">{it.customer_id || <span className="text-faint">—</span>}</td>
                    <td className="td whitespace-nowrap font-medium">{it.predicted_category} <span className="font-normal text-muted">{pct(it.confidence, 0)}</span></td>
                    <td className="td">{it.actual_category || <span className="text-faint">—</span>}</td>
                    <td className="td"><span className="inline-flex flex-wrap gap-1">{resultBadge(it)}{it.rescored && <Badge tone="adapted">Re-scored</Badge>}</span></td>
                    <td className="td"><VersionTag version={it.model_version} /></td>
                    <td className="td whitespace-nowrap text-muted">{SOURCE_LABELS[it.source] || it.source}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={data.page} pages={data.pages} total={data.total} onChange={(p) => update("page", String(p))} noun="predictions" />
          </>
        ) : (
          <Empty title={active ? "No predictions match these filters" : stream === "simulation" ? "No simulated predictions yet" : "No predictions yet"} icon={HistoryIcon}
            action={active ? <button type="button" className="btn btn-secondary" onClick={clear}>Clear filters</button>
              : <Link to={stream === "simulation" ? "/app/simulation" : "/app/predict"} className="btn btn-primary">{stream === "simulation" ? "Open the simulation" : "Make a prediction"}</Link>}>
            {active ? "Try fewer filters." : isStaff ? "Predictions appear here as soon as the form, live events, uploads or the simulation create them." : "Predictions you make on the form or send as live events appear here."}
          </Empty>
        )}
      </Panel>
      {selected && <Detail key={selected.id} item={selected} onClose={() => setSelected(null)} canRecord={canRecord(selected)}
        onChanged={async () => { const fresh = await Predictions.get(selected.id).catch(() => null); if (fresh) setSelected(fresh); reload({ silent: true }); }} />}
    </>
  );
}
