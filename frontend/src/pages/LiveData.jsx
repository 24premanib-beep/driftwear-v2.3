import { useState } from "react";
import { Braces, Layers, RadioTower, Send, SlidersHorizontal } from "lucide-react";
import { ExplanationPanel, PipelineStages, StageIcon } from "../components/insights";
import { EventErrors } from "../components/validation";
import { Badge, Disclosure, Empty, ErrorNote, Field, Ident, Loading, Measure, Measures, Notice, PageHeader, Pagination, Panel, Spinner,
  Table, Tabs, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Events, Predictions } from "../lib/endpoints";
import { dateTime, num, pct, timeAgo } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { buildEventPayload, curlExample, journey, newEventId, SAMPLE_EVENT } from "../lib/liveData";
import { useMeta } from "../lib/meta";
import { issueLine } from "../lib/validation";

const LIVE_EVENTS = new Set(["PREDICTION_CREATED", "PREDICTION_RESULT", "MODEL_VERSION_CREATED", "MODEL_ACTIVATED", "DRIFT_DETECTED"]);

/** A 409 from POST /api/events: the event id was already ingested. Nothing was predicted or counted twice. */
function Duplicate({ error, onShow, onNewId }) {
  const id = error?.details?.prediction_id;
  return (
    <Notice tone="warning" title="Already received: this event ID was ingested before"
      action={<div className="flex flex-col gap-1.5 sm:flex-row">
        {id && <button type="button" className="btn btn-secondary btn-sm" onClick={() => onShow(id)}>Show prediction #{id}</button>}
        {onNewId && <button type="button" className="btn btn-secondary btn-sm" onClick={onNewId}>Use a new event ID</button>}
      </div>}>
      {error.message} The event was not predicted or counted again (409 Conflict).
    </Notice>
  );
}

function SendResult({ error, onShow, onNewId }) {
  if (!error) return null;
  if (error.status === 409) return <div className="mt-4"><Duplicate error={error} onShow={onShow} onNewId={onNewId} /></div>;
  if (error.status === 422 && Array.isArray(error.details)) return <div className="mt-4"><EventErrors error={error} /></div>;
  return <ErrorNote error={error} className="mt-4" title={error.status === 429 ? "Too many events" : undefined} />;
}

function EventForm({ meta, onSent, onShow }) {
  const [form, setForm] = useState(() => ({ event_id: newEventId(), ...SAMPLE_EVENT }));
  const send = useAction(() => Events.send(buildEventPayload(form)));
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const r = await send.run();
    if (r) { onSent(r); setForm((f) => ({ ...f, event_id: newEventId() })); }
  };
  const select = (k, options, empty) => (
    <select id={`ev-${k}`} className="input" value={form[k]} onChange={set(k)}>
      {empty && <option value="">{empty}</option>}
      {options.map((o) => <option key={o}>{o}</option>)}
    </select>
  );
  const input = (k, type = "text", extra = {}) => <input id={`ev-${k}`} className="input" type={type} value={form[k]} onChange={set(k)} {...extra} />;
  return (
    <form onSubmit={submit} noValidate>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Event ID" htmlFor="ev-event_id" hint="Unique per event. Sending the same ID again is refused, so retries never double-count." className="sm:col-span-2">
          <div className="flex gap-2">{input("event_id", "text", { className: "input font-mono text-sm" })}
            <button type="button" className="btn btn-secondary" onClick={() => setForm({ ...form, event_id: newEventId() })}>New ID</button></div>
        </Field>
        <Field label="Customer ID" optional htmlFor="ev-customer_id">{input("customer_id")}</Field>
        <Field label="Style preference" htmlFor="ev-customer_preference">{select("customer_preference", meta.preferences)}</Field>
        <Field label="Previous category" htmlFor="ev-previous_category">{select("previous_category", meta.categories)}</Field>
        <Field label="Orders so far" htmlFor="ev-purchase_frequency">{input("purchase_frequency", "number")}</Field>
        <Field label="Days since last order" htmlFor="ev-recency">{input("recency", "number")}</Field>
        <Field label="Price (₹)" htmlFor="ev-price">{input("price", "number")}</Field>
        <Field label="Discount (%)" htmlFor="ev-discount">{input("discount", "number")}</Field>
        <Field label="Purchase date" optional htmlFor="ev-purchase_date" hint="Defaults to the time it is received">{input("purchase_date", "datetime-local")}</Field>
        <Field label="Season" optional htmlFor="ev-season" hint="Derived from the date when empty">{select("season", meta.seasons, "Derive from the date")}</Field>
        <Field label="Actual category" optional htmlFor="ev-actual_category" hint="Usually unknown at purchase time; send it later" className="sm:col-span-2">
          {select("actual_category", meta.categories, "Not known yet")}
        </Field>
      </div>
      <p className="mt-4 text-xs text-muted">Values are sent exactly as typed. The server validates them; nothing is corrected here.</p>
      <button type="submit" className="btn btn-primary mt-3" disabled={send.busy}>
        {send.busy ? <Spinner /> : <Send className="h-4 w-4" aria-hidden="true" />}{send.busy ? "Sending…" : "Send event"}
      </button>
      <SendResult error={send.error} onShow={onShow} onNewId={() => { setForm({ ...form, event_id: newEventId() }); send.reset(); }} />
    </form>
  );
}

function JsonForm({ onSent, onShow }) {
  const [text, setText] = useState(() => JSON.stringify({ event_id: newEventId(), ...buildEventPayload(SAMPLE_EVENT) }, null, 2));
  const [parseError, setParseError] = useState(null);
  const send = useAction((body) => Events.send(body));
  const newId = () => {
    try { setText(JSON.stringify({ ...JSON.parse(text || "{}"), event_id: newEventId() }, null, 2)); setParseError(null); send.reset(); } catch (e) { setParseError(`Not valid JSON: ${e.message}`); }
  };
  const submit = async () => {
    let body;
    try { body = JSON.parse(text); setParseError(null); } catch (e) { setParseError(`Not valid JSON: ${e.message}`); return; }
    const r = await send.run(body);
    if (r) onSent(r);
  };
  return (
    <div>
      <p className="mb-3 text-sm text-muted">Exactly what an external system sends. Try <code className="text-fg">"price": -500</code> or an unknown field to see validation reject it.</p>
      <label className="field-label" htmlFor="event-json">Event body (JSON)</label>
      <textarea id="event-json" className="input h-72 font-mono text-[12.5px] leading-relaxed" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      {parseError && <p className="mt-2 text-sm text-drift-ink" role="alert">{parseError}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="btn btn-primary" onClick={submit} disabled={send.busy}>{send.busy ? <Spinner /> : <Send className="h-4 w-4" aria-hidden="true" />}Send event</button>
        <button type="button" className="btn btn-secondary" onClick={newId}>New event ID</button>
      </div>
      <SendResult error={send.error} onShow={onShow} onNewId={newId} />
    </div>
  );
}

const BATCH_TONE = { accepted: "stable", rejected: "drift", duplicate: "warning", failed: "drift", not_processed: "neutral" };
const BATCH_LABEL = { accepted: "Accepted", rejected: "Rejected", duplicate: "Duplicate", failed: "Failed", not_processed: "Not processed" };

function BatchForm({ onDone, onShow }) {
  const [text, setText] = useState(() => JSON.stringify([
    { event_id: newEventId(), ...buildEventPayload(SAMPLE_EVENT) },
    { event_id: newEventId(), ...buildEventPayload({ ...SAMPLE_EVENT, previous_category: "Footwear", price: 2899, actual_category: "Footwear" }) },
    { event_id: newEventId(), ...buildEventPayload({ ...SAMPLE_EVENT, price: -500, season: "XYZ" }) },
  ], null, 2));
  const [parseError, setParseError] = useState(null);
  const send = useAction((events) => Events.sendBatch(events));
  const r = send.result || (send.error?.details?.results ? send.error.details : null);
  const submit = async () => {
    let events;
    try { events = JSON.parse(text); setParseError(null); } catch (e) { setParseError(`Not valid JSON: ${e.message}`); return; }
    if (!Array.isArray(events)) { setParseError("A batch is a JSON array of events: [ {...}, {...} ]."); return; }
    if (await send.run(events)) onDone();
  };
  return (
    <div>
      <p className="mb-3 text-sm text-muted">A JSON array of events, each validated on its own. The example includes one invalid event on purpose.</p>
      <label className="field-label" htmlFor="batch-json">Events (JSON array)</label>
      <textarea id="batch-json" className="input h-64 font-mono text-[12.5px] leading-relaxed" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      {parseError && <p className="mt-2 text-sm text-drift-ink" role="alert">{parseError}</p>}
      <button type="button" className="btn btn-primary mt-3" onClick={submit} disabled={send.busy}>{send.busy ? <Spinner /> : <Layers className="h-4 w-4" aria-hidden="true" />}Send batch</button>
      {send.error && !r && <ErrorNote error={send.error} className="mt-4" />}
      {r && (
        <div className="mt-4 space-y-3">
          <p className="text-sm font-medium text-fg" role="status">{r.message}</p>
          <Table className="rounded-md border border-seam" caption="Result for each event in the batch">
            <thead><tr><th className="th">#</th><th className="th">Event</th><th className="th">Result</th><th className="th">Details</th></tr></thead>
            <tbody>
              {r.results.map((x) => (
                <tr key={x.index}>
                  <td className="td tabular text-muted">{x.index + 1}</td>
                  <td className="td"><code className="text-xs">{x.event_id || "—"}</code></td>
                  <td className="td"><Badge tone={BATCH_TONE[x.status]} icon>{BATCH_LABEL[x.status] || x.status}</Badge></td>
                  <td className="td text-sm">
                    {x.status === "accepted" ? <>
                      <button type="button" className="link" onClick={() => onShow(x.prediction_id)}>#{x.prediction_id}</button> {x.predicted_category} ({pct(x.confidence, 0)}) by {x.model_version}
                      {x.outcome ? ` · actual ${x.outcome.actual_category}, ${x.outcome.is_correct ? "correct" : "wrong"}` : " · awaiting outcome"}</>
                      : x.errors ? <span className="text-drift-ink">{x.errors.map(issueLine).join("; ")}</span> : x.message}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
    </div>
  );
}

/** The seven stages of one event; the outcome can be recorded at the stage that is waiting for it. */
function Journey({ subject, categories, onChanged }) {
  const [actual, setActual] = useState("");
  const { result, row } = subject;
  const p = result?.prediction || row;
  const ref = (result?.event_id || row?.event_id) ? { event_id: result?.event_id || row?.event_id } : { prediction_id: p.id };
  const outcome = useAction(() => Events.outcome(ref, actual));
  const out = outcome.result?.outcome;
  const steps = journey({ result, row, outcome: out });
  const waiting = !out && !result?.outcome && !row?.actual_category;
  return (
    <div className="space-y-5">
      <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-[8.5px] before:top-2 before:w-px before:bg-seam-strong" aria-label="Pipeline stages for this event">
        {steps.map((s) => (
          <li key={s.key} className="relative flex gap-3">
            <span className="relative z-10 mt-0.5 rounded-full bg-surface"><StageIcon status={s.status} /></span>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted">{s.label}<span className="sr-only"> ({s.status})</span></p>
              <p className={`text-sm font-medium ${s.status === "failed" ? "text-drift-ink" : s.status === "pending" ? "text-muted" : "text-fg"}`}>
                {s.key === "received" && s.value !== "No event id" ? <Ident value={s.value} /> : s.value}
                {s.version && <span className="ml-2"><VersionTag version={s.version} /></span>}
              </p>
              {(s.detail || s.time) && <p className="text-xs text-muted">{[s.detail, s.time && dateTime(s.time)].filter(Boolean).join(" · ")}</p>}
              {s.key === "outcome" && waiting && (
                <div className="mt-2 flex flex-wrap items-end gap-2 rounded-md border border-dashed border-seam-strong bg-canvas/50 p-3">
                  <Field label="The actual category arrived" htmlFor="late-actual" className="min-w-[180px] flex-1">
                    <select id="late-actual" className="input input-sm" value={actual} onChange={(e) => setActual(e.target.value)}>
                      <option value="">Choose what was bought</option>{categories.map((c) => <option key={c}>{c}</option>)}
                    </select>
                  </Field>
                  <button type="button" className="btn btn-primary btn-sm py-2" disabled={!actual || outcome.busy} onClick={async () => { if (await outcome.run()) onChanged(); }}>
                    {outcome.busy && <Spinner />}Send outcome
                  </button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
      <ErrorNote error={outcome.error} />
      {outcome.result && <Notice tone={out.new_model_version ? "adapted" : out.is_correct ? "stable" : "warning"}>{outcome.result.message}</Notice>}
      {(result?.pipeline || outcome.result?.pipeline) && (
        <Disclosure summary="Server trace for this event">
          <PipelineStages stages={outcome.result?.pipeline
            ? [...result?.pipeline?.filter((s) => !["outcome", "error", "drift_check", "adaptation"].includes(s.stage)) || [], ...outcome.result.pipeline]
            : result.pipeline} />
        </Disclosure>
      )}
      {(result?.explanation || p.explanation) && (
        <Disclosure summary="Why this prediction?"><ExplanationPanel explanation={result?.explanation || p.explanation} /></Disclosure>
      )}
    </div>
  );
}

function rowStatus(p) {
  if (!p.actual_category) return <Badge icon>Awaiting outcome</Badge>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {p.is_correct ? <Badge tone="correct" icon>Correct</Badge> : <Badge tone="wrong" icon>Wrong</Badge>}
      {p.rescored && <Badge tone="adapted" title={`Scored for drift by ${p.scored_version}`}>Re-scored</Badge>}
    </span>
  );
}

function RecentEvents({ refreshKey, selected, onSelect }) {
  const [page, setPage] = useState(1);
  const list = useApi(() => Predictions.list({ source: "event", page, page_size: 10 }), [page, refreshKey]);
  if (list.loading && !list.data) return <Loading label="Loading live events…" rows={4} className="px-5" />;
  if (list.error) return <ErrorNote error={list.error} onRetry={() => list.reload()} className="m-4" />;
  if (!list.data?.items?.length) {
    return <Empty title="No live events yet" icon={RadioTower}>Send one above, or connect an external system to <code>POST /api/events</code>. Each event appears here with its prediction and, later, its outcome.</Empty>;
  }
  return (
    <>
      <Table caption="Recent live events">
        <thead><tr><th className="th">Received</th><th className="th">Event ID</th><th className="th">Prediction</th><th className="th">Model</th>
          <th className="th">Actual</th><th className="th">Status</th><th className="th"><span className="sr-only">Open</span></th></tr></thead>
        <tbody>
          {list.data.items.map((p) => (
            <tr key={p.id} className={`row-link ${selected === p.id ? "bg-plum-50/70" : ""}`} onClick={() => onSelect({ row: p })}>
              <td className="td whitespace-nowrap text-muted" title={dateTime(p.created_at)}>{timeAgo(p.created_at)}</td>
              <td className="td" onClick={(e) => e.stopPropagation()}><Ident value={p.event_id} /></td>
              <td className="td whitespace-nowrap"><span className="tabular text-muted">#{p.id}</span> <span className="font-medium">{p.predicted_category}</span> <span className="text-xs text-muted">{pct(p.confidence, 0)}</span></td>
              <td className="td"><VersionTag version={p.model_version} /></td>
              <td className="td">{p.actual_category || <span className="text-faint">—</span>}</td>
              <td className="td">{rowStatus(p)}</td>
              <td className="td text-right"><button type="button" className="link text-sm" onClick={(e) => { e.stopPropagation(); onSelect({ row: p }); }}>
                {p.actual_category ? "View" : "Record outcome"}</button></td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onChange={setPage} noun="live events" />
    </>
  );
}

function Rejections({ refreshKey }) {
  const list = useApi(() => Events.rejections({ page_size: 8 }), [refreshKey]);
  if (list.loading && !list.data) return <Loading label="Loading rejected events…" rows={2} className="px-5" />;
  if (list.error) return <ErrorNote error={list.error} onRetry={() => list.reload()} className="m-4" />;
  if (!list.data?.items?.length) return <p className="px-5 py-5 text-sm text-muted">No live event has been rejected. Every event so far passed validation.</p>;
  return (
    <Table caption="Rejected live events">
      <thead><tr><th className="th">When</th><th className="th">Event ID</th><th className="th">Sent by</th><th className="th">Why it was rejected</th></tr></thead>
      <tbody>
        {list.data.items.map((r) => (
          <tr key={r.id}>
            <td className="td whitespace-nowrap text-muted" title={dateTime(r.created_at)}>{timeAgo(r.created_at)}</td>
            <td className="td whitespace-nowrap"><code className="text-xs">{r.event_id || "—"}</code>{r.batch_index !== null && r.batch_index !== undefined && <span className="block text-xs text-muted">Batch item {r.batch_index + 1}</span>}</td>
            <td className="td text-muted">{r.user_name || "—"}</td>
            <td className="td text-sm text-drift-ink">{r.errors.map(issueLine).join(" · ")}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

const TABS = [{ value: "form", label: "Form", icon: SlidersHorizontal }, { value: "json", label: "JSON", icon: Braces }, { value: "batch", label: "Batch", icon: Layers }];

export default function LiveData() {
  const meta = useMeta();
  const { isStaff } = useAuth();
  const [tab, setTab] = useState("form");
  const [subject, setSubject] = useState(null);       // {result} after sending, or {row} from the table
  const [refreshKey, setRefreshKey] = useState(0);
  const [lookupError, setLookupError] = useState(null);
  const summary = useApi(() => Events.summary(), [refreshKey]);
  const bump = () => setRefreshKey((k) => k + 1);
  useLiveRefresh(bump, "live", { events: LIVE_EVENTS, delay: 900 });
  const s = summary.data;
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const example = curlExample(origin, { event_id: "evt-2026-10-09-000123", ...buildEventPayload(SAMPLE_EVENT) });
  const show = async (id) => {
    setLookupError(null);
    try { setSubject({ row: await Predictions.get(id) }); } catch (e) { setLookupError(e); }
  };
  const subjectId = subject?.result?.prediction?.id ?? subject?.row?.id;

  return (
    <>
      <PageHeader title="Live data"
        lede="Purchase events from any external system, or typed here. Each one is validated before the model sees it, predicted, and stored with the model version. The actual category can arrive later; only then does the drift detector learn from it. Simulation data never enters this stream." />
      <ErrorNote error={summary.error} onRetry={() => summary.reload()} className="mb-6" />
      <div className="space-y-6">
        <Measures>
          <Measure label={isStaff ? "Events received" : "Your events"} value={s ? num(s.received) : "—"} sub={s?.last_event_at ? `Last ${timeAgo(s.last_event_at)}` : "None yet"} />
          <Measure label="Awaiting outcome" value={s ? num(s.awaiting_outcome) : "—"} sub="Predicted, not yet scored" />
          <Measure label="Outcomes received" value={s ? num(s.labeled) : "—"} sub={s?.labeled ? `${num(s.correct)} correct · ${num(s.wrong)} wrong` : "No outcomes yet"} />
          <Measure label="Live accuracy" value={s?.accuracy !== null && s?.accuracy !== undefined ? pct(s.accuracy) : "N/A"} sub="Labeled live events only" />
          <Measure label="Rejected" value={s ? num(s.rejected) : "—"} tone={s?.rejected ? "warning" : undefined} sub="Failed validation, never predicted" />
        </Measures>

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <Panel title="Send a live event" description="The same endpoints an external application calls"
            actions={<Tabs tabs={TABS} value={tab} onChange={setTab} label="How to send" size="sm" />}>
            {tab === "form" && <EventForm meta={meta} onSent={(r) => { setSubject({ result: r }); bump(); }} onShow={show} />}
            {tab === "json" && <JsonForm onSent={(r) => { setSubject({ result: r }); bump(); }} onShow={show} />}
            {tab === "batch" && <BatchForm onDone={bump} onShow={show} />}
          </Panel>
          <Panel title="Event journey" description={subject ? `Prediction #${subjectId}, as reported by the server` : "From receipt to the drift detector"} aria-live="polite">
            <ErrorNote error={lookupError} className="mb-4" />
            {subject ? <Journey key={`${subjectId}-${subject.row?.outcome_at || ""}`} subject={subject} categories={meta.categories} onChanged={bump} />
              : <Empty title="Send an event or pick one below">
                You will follow it through the seven stages: received, validated, predicted, recorded with its model version, outcome received,
                error calculated and drift detector updated. Stages that are waiting for the actual category stay marked as waiting.
              </Empty>}
          </Panel>
        </div>

        <Panel title={isStaff ? "Recent live events" : "Your recent live events"} description="Select a row to follow it, or record its actual category when it arrives." flush>
          <RecentEvents refreshKey={refreshKey} selected={subjectId} onSelect={setSubject} />
        </Panel>

        <div className="grid items-start gap-6 xl:grid-cols-2">
          {isStaff && (
            <Panel title="Recently rejected events" description="Stored with every validation error; they never reached the model" flush>
              <Rejections refreshKey={refreshKey} />
            </Panel>
          )}
          <Panel title="Connect an external application" description="Authenticate with a bearer token, then post events as they happen">
            <div className="relative">
              <pre className="overflow-x-auto rounded-md bg-navy p-4 text-xs leading-relaxed text-navy-100">{example}</pre>
              <span className="absolute right-2 top-2 rounded bg-white/90"><CopyButtonInline value={example} /></span>
            </div>
            <ul className="mt-4 space-y-1.5 text-sm text-muted">
              <li><code className="text-fg">POST /api/events</code> one event; <code className="text-fg">POST /api/events/batch</code> up to 100</li>
              <li><code className="text-fg">POST /api/events/outcome</code> (or <code className="text-fg">/outcomes</code>) when the actual category is known, by <code>event_id</code> or <code>prediction_id</code></li>
              <li>Invalid events get 422 with every problem listed; a repeated <code>event_id</code> gets 409 with the original prediction.</li>
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}

function CopyButtonInline({ value }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn btn-quiet btn-sm" onClick={() => navigator.clipboard?.writeText(value).then(() => { setDone(true); setTimeout(() => setDone(false), 1800); }).catch(() => {})}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}
