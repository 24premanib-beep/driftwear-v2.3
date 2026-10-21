import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, FlaskConical, History, RadioTower, Sparkle, Tags } from "lucide-react";
import { MarkerLegend, SeriesLegend, TimelineChart, C } from "../components/charts";
import { ActivityFeed, DriftImpactSummary, DriftLink, HealthPanel, StageSequence } from "../components/insights";
import { ErrorNote, Loading, Measure, Measures, Panel, SeverityBadge, SimulationBanner, StateTrack, StreamChip, StreamSwitch, Tabs,
  ToneIcon, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh, useRealtime } from "../context/RealtimeContext";
import { Overview } from "../lib/endpoints";
import { KIND_LABELS, num, pct, timeAgo } from "../lib/format";
import { useApi, useStreamParam } from "../lib/hooks";

const SIGNIFICANT = ["WARNING_DETECTED", "DRIFT_DETECTED", "ADAPTATION_STARTED", "ADAPTATION_COMPLETED", "ADAPTATION_FAILED",
  "MODEL_VERSION_CREATED", "MODEL_ACTIVATED", "DETECTOR_CHANGED", "DATA_UPLOADED", "RECORDS_PROCESSED", "TREND_CHANGED", "SIMULATION_RESET", "PIPELINE_ERROR"];

/** The rolling window is the last 50 labeled outcomes, or all of them while there are fewer. */
function recentSub(n) {
  if (!n) return "No labeled outcomes yet";
  return n >= 50 ? "Last 50 labeled outcomes" : `All ${num(n)} labeled outcomes so far`;
}

/** The answer to the central question, from the detector state the backend reports. */
function verdict(k, status, adapting, lastDrift) {
  const model = k.model_version;
  if (adapting) {
    return { title: "Yes. The model is adapting.", tone: "adapted",
      text: `Concept drift was confirmed, so ${status?.adapting_to || "a new version"} is being trained on data from after the change. ${model} keeps serving predictions until it is ready.` };
  }
  if (k.drift_status === "DRIFT") return { title: "Yes. Concept drift is confirmed.", tone: "drift", text: k.status_text };
  if (k.drift_status === "WARNING") {
    return { title: "Possibly. Errors are rising.", tone: "warning",
      text: `The detector is in its warning zone for ${model}: errors are above their normal level but the rise is not yet significant. Nothing changes until drift is confirmed.` };
  }
  if (!k.records_processed) {
    return { title: "Not measured yet.", tone: "neutral",
      text: "No prediction on this stream has its actual category yet. Drift is judged only on labeled outcomes, so the detector has nothing to read." };
  }
  if (lastDrift) {
    return { title: "No change right now.", tone: "stable",
      text: `Errors are at their normal level for ${model}. The last drift was confirmed ${timeAgo(lastDrift.detected_at)} and the model adapted from ${lastDrift.previous_model_version} to ${lastDrift.new_model_version || "(kept)"}.` };
  }
  return { title: "No significant change.", tone: "stable",
    text: `Prediction errors are at their normal level for ${model} across ${num(k.records_processed)} labeled outcomes.` };
}

/** What the system did on its own: confirmed drifts and the model versions it created, newest first. */
function DecisionLog({ markers, stream, isStaff, lastDrift }) {
  const items = [
    ...(markers?.drifts || []).map((d) => ({ kind: "drift", step: d.step, ts: d.timestamp, d })),
    ...(markers?.adaptations || []).map((a) => ({ kind: "version", step: a.step, ts: a.timestamp, a })),
  ].sort((x, y) => y.step - x.step || (x.kind === "version" ? -1 : 1)).slice(0, 7);
  if (!items.length) {
    return <p className="px-5 py-6 text-sm text-muted">No drift and no adaptation on this stream yet. The original model v1.0 has served every prediction.</p>;
  }
  const q = stream === "simulation" ? "?stream=simulation" : "";
  return (
    <ol className="divide-y divide-seam">
      {items.map((it) => (
        <li key={`${it.kind}-${it.step}-${it.a?.version || it.d?.event_key}`} className="flex gap-3 px-5 py-3">
          <ToneIcon tone={it.kind === "drift" ? "drift" : "adapted"} className="mt-0.5 h-4 w-4" />
          <div className="min-w-0 flex-1 text-sm">
            {it.kind === "drift" ? (
              <>
                <p className="font-medium text-fg">{it.d.event_key}: drift confirmed by {it.d.detector}
                  {lastDrift?.event_key === it.d.event_key && <span className="ml-2 align-middle"><SeverityBadge severity={lastDrift.severity} /></span>}</p>
                <p className="text-muted">Change estimated at outcome #{it.d.change_point_step + 1}; {it.d.to_version ? <>retrained as <VersionTag version={it.d.to_version} /></> : `${it.d.from_version} kept (adaptation failed)`}</p>
                {isStaff && <p className="mt-0.5"><DriftLink eventKey={it.d.event_key} stream={stream}>See before, during and after</DriftLink></p>}
              </>
            ) : (
              <>
                <p className="font-medium text-fg"><VersionTag version={it.a.version} /> <span className="ml-1">{KIND_LABELS[it.a.kind] || it.a.kind}</span></p>
                <p className="text-muted">{it.a.kind === "refresh" ? "Retrained with more data from the new pattern." : it.a.kind === "drift" ? "Trained on the post-change window and activated." : "Retrained on request by an administrator."}</p>
                {isStaff && <p className="mt-0.5"><Link to={`/app/models${q}`} className="link">Open in the registry</Link></p>}
              </>
            )}
            <p className="mt-0.5 text-xs text-faint">Outcome #{it.step + 1}{it.ts ? ` · ${timeAgo(it.ts)}` : ""}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function NextSteps({ isStaff, isAdmin, stream, pending }) {
  const steps = [
    { to: "/app/predict", icon: Sparkle, title: "Make a prediction", text: "Describe a purchase and see why the model chose a category." },
    { to: "/app/live", icon: RadioTower, title: "Follow a live event", text: "Send an event, then its actual category, and watch it reach the detector." },
    isStaff && { to: "/app/simulation", icon: FlaskConical, title: "Run the drift demonstration", text: "Change the fashion trend in the simulation and watch the model adapt." },
    isStaff && { to: `/app/models${stream === "simulation" ? "?stream=simulation" : ""}`, icon: Tags, title: "Compare model versions", text: "Lineage, validation versus live metrics, and rollback." },
    !isStaff && { to: "/app/history", icon: History, title: "Review your predictions", text: "Record the actual category for predictions that are still waiting for one." },
    !isStaff && { to: "/app/how-it-works", icon: ArrowUpRight, title: "How DriftWear works", text: "Predictions, errors, drift and adaptation in plain language." },
  ].filter(Boolean);
  return (
    <div>
      {isAdmin && pending > 0 && stream === "live" && (
        <p className="mb-3 text-sm text-fg">{num(pending)} validated uploaded records are waiting for the live stream. <Link to="/app/data" className="link">Process them in Data management</Link></p>
      )}
      <div className="hairlines"><ul className="hairlines-inner sm:grid-cols-2">
        {steps.map(({ to, icon: Icon, title, text }, i) => (
          <li key={to} className={steps.length % 2 && i === steps.length - 1 ? "sm:col-span-2" : undefined}>
            <Link to={to} className="group flex h-full gap-3 px-4 py-3.5 hover:bg-navy-50/60">
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-plum" aria-hidden="true" />
              <span><span className="block text-sm font-semibold text-fg group-hover:underline">{title}</span><span className="block text-sm text-muted">{text}</span></span>
            </Link>
          </li>
        ))}
      </ul></div>
    </div>
  );
}

export default function Dashboard() {
  const { isStaff, isAdmin, user } = useAuth();
  const [stream, setStream] = useStreamParam(isStaff);
  const [metric, setMetric] = useState("accuracy");
  const { events, snapshot } = useRealtime();
  const { data, error, loading, reload } = useApi(() => Overview.dashboard(stream), [stream]);
  useLiveRefresh(() => reload({ silent: true }), stream);

  const k = data?.kpis;
  const live = snapshot?.[stream];
  const adapting = Boolean(live?.adapting ?? data?.detectors?.adapting);
  const status = live?.status || k?.drift_status;
  const v = data && verdict({ ...k, drift_status: status }, data.status, adapting, data.last_drift);
  const lastImpact = data?.impact?.length ? data.impact[data.impact.length - 1] : null;

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        {isStaff ? <span className="text-sm text-muted">Showing the {stream === "simulation" ? "simulation" : "live"} stream</span>
          : <span className="flex items-center gap-3"><StreamChip stream={stream} /><span className="text-sm text-muted">Welcome back, {user?.name?.split(" ")[0] || ""}</span></span>}
        {isStaff && <StreamSwitch stream={stream} onChange={setStream} />}
      </div>
      {stream === "simulation" && <SimulationBanner />}
      <ErrorNote error={error} onRetry={() => reload()} className="mb-6" />
      {loading && !data ? <Loading label="Loading the model status, performance series and drift history…" rows={5} /> : data && (
        <div className="space-y-8">
          <section className="grid items-start gap-8 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]" aria-labelledby="verdict">
            <div>
              <p className="max-w-xl text-md text-muted">Has the relationship between what customers buy and the category they buy next changed?</p>
              <h1 id="verdict" className="display-tight mt-1 text-3xl text-navy md:text-4xl">{v.title}</h1>
              <p className="mt-3 max-w-prose text-md leading-relaxed text-fg/85">{v.text}</p>
              <div className="mt-5"><StateTrack status={status} adapting={adapting} adaptingTo={live?.adapting_to || data.status?.adapting_to} size="lg" /></div>
              <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3 text-sm">
                <div><dt className="text-muted">Active model</dt><dd className="mt-1"><VersionTag version={live?.model_version || k.model_version} active size="lg" /></dd></div>
                <div><dt className="text-muted">Detector</dt><dd className="figure mt-1 text-lg text-fg">{k.detector}</dd></div>
                <div><dt className="text-muted">Outcomes scored</dt><dd className="figure mt-1 text-lg text-fg">{num(live?.records_processed ?? k.records_processed)}</dd></div>
              </dl>
              <Measures className="mt-8">
                <Measure label="Recent accuracy" value={pct(k.accuracy_recent)} sub={recentSub(live?.records_processed ?? k.records_processed)} />
                <Measure label="Overall accuracy" value={pct(k.accuracy_overall)} sub={k.baseline_accuracy_overall !== null && k.baseline_accuracy_overall !== undefined ? `Frozen v1.0 on the same records: ${pct(k.baseline_accuracy_overall)}` : "No outcomes yet"} />
                <Measure label={isStaff ? "Predictions" : "Your predictions"} value={num(k.predictions)} sub={`${num(data.counts.awaiting_outcome)} awaiting their actual category`} to={stream === "live" ? "/app/history" : undefined} />
                <Measure label="Confirmed drifts" value={num(k.drift_events)} tone={k.drift_events ? "drift" : undefined} sub={k.drift_events ? `Last ${timeAgo(data.last_drift?.detected_at)}` : "None on this stream"} />
              </Measures>
            </div>
            <Panel title="Model health" description="How much to trust the active model right now"
              actions={isStaff && <Link to={`/app/system${stream === "simulation" ? "?stream=simulation" : ""}`} className="link text-sm">System monitoring</Link>}>
              <HealthPanel health={data.health} />
            </Panel>
          </section>


          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Panel title="Performance over time" description="Measured only on predictions whose actual category has arrived."
              actions={<Tabs label="Metric" size="sm" value={metric} onChange={setMetric}
                tabs={[{ value: "accuracy", label: "Accuracy" }, { value: "error_rate", label: "Error rate" }]} />}
              footer={metric === "accuracy"
                ? "Stone line: the original v1.0 model frozen at the start, scored on the same records. The gap is what adaptation is worth."
                : "The error stream is what the drift detector reads: 0 for a correct prediction, 1 for a wrong one, shown here as a rolling rate."}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                {metric === "accuracy"
                  ? <SeriesLegend items={[[C.ink, "Active model"], [C.stone, "Frozen v1.0", true]]} />
                  : <SeriesLegend items={[[C.ink, "Rolling error rate"]]} />}
                <MarkerLegend warnings={metric === "error_rate"} />
              </div>
              <TimelineChart series={data.series} markers={data.markers} metric={metric} height={300} />
            </Panel>
            <Panel title="What the system did" description="Decisions the pipeline took on its own" flush>
              <DecisionLog markers={data.markers} stream={stream} isStaff={isStaff} lastDrift={data.last_drift} />
            </Panel>
          </div>

          {lastImpact && (
            <Panel title={`${lastImpact.event_key}: did the adaptation work?`}
              description="Accuracy before the change, while the old model failed, and after the new model took over. Labeled outcomes only."
              actions={isStaff && <DriftLink eventKey={lastImpact.event_key} stream={stream}>Full drift performance</DriftLink>}>
              <div className="space-y-5">
                <DriftImpactSummary impact={lastImpact} />
                <StageSequence stages={data.cycle} label="Most recent drift cycle" />
              </div>
            </Panel>
          )}

          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <section>
              <h2 className="mb-3 text-md font-semibold text-fg">Next steps</h2>
              <NextSteps isStaff={isStaff} isAdmin={isAdmin} stream={stream} pending={data.pending_uploaded_records} />
            </section>
            <Panel title="Recent activity" flush>
              <ActivityFeed live={events} initial={data.recent_events} stream={stream} limit={6} only={SIGNIFICANT}
                empty="No warnings, drift, adaptations or uploads yet. Routine predictions are listed on the Live data page." />
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
