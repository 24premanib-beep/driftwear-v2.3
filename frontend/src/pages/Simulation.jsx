import { useState } from "react";
import { Link } from "react-router-dom";
import { Pause, Play, RotateCcw, Shuffle, SkipForward } from "lucide-react";
import { MarkerLegend, SeriesLegend, TimelineChart, C } from "../components/charts";
import { ActivityFeed, StageIcon } from "../components/insights";
import { ConfirmDialog, ErrorNote, Loading, Measure, Measures, Notice, PageHeader, Panel, SimulationBanner, Spinner, StateTrack, Tabs,
  VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh, useRealtime, useRealtimeEvents } from "../context/RealtimeContext";
import { Models, Overview, Simulation as Sim } from "../lib/endpoints";
import { num, pct } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";

const SPEEDS = [[1, "Slow: 1 record a tick"], [5, "Normal: 5 records a tick"], [15, "Fast: 15 records a tick"]];

/**
 * The guided demonstration. Every step's state is derived from what the backend reports (records processed, trend
 * changes, warnings, drift events, versions, outcomes after adaptation, rollbacks); nothing is ticked off locally.
 */
function guide({ state, dash, activations }) {
  const k = dash?.kpis || {};
  const markers = dash?.markers || {};
  const change = state?.trend_changes?.[0];
  const changeStep = change?.step ?? null;
  const baseline = changeStep ?? k.records_processed ?? 0;
  const drift = markers.drifts?.[0];
  const adaptation = (markers.adaptations || []).find((a) => a.kind === "drift");
  const warnedAfter = (markers.warnings || []).some((w) => changeStep !== null && w.step >= changeStep);
  const impact = dash?.impact?.[0];
  const measured = Boolean(impact?.after?.n);
  const rollback = (activations?.items || []).find((a) => a.action === "rollback");
  const afterRollback = rollback ? (k.records_processed || 0) - (rollback.at_step || 0) : 0;
  return [
    // once the trend has changed this phase is over, however long it ran
    { key: "baseline", title: "Run the original trend", done: baseline >= 100 || changeStep !== null,
      text: changeStep !== null
        ? `${num(baseline)} outcomes ran under the first trend before it changed${baseline < 100 ? "; a longer baseline (100 or more) makes the later drop easier to see" : ""}.`
        : `Process at least two batches of 50 under the first trend and watch accuracy settle. ${num(baseline)} outcomes so far.`, action: "step50" },
    { key: "trend", title: "Change the fashion trend", done: Boolean(change),
      text: change ? `${change.from_trend} → ${change.to_trend} at outcome #${change.step + 1}.` : "Customers start buying differently, although their purchase details look much the same.", action: "trend" },
    { key: "errors", title: "Stream and watch errors rise", done: warnedAfter || Boolean(drift),
      text: "Start streaming with “pause on drift” on. The error rate climbs; the detector enters its warning zone.", action: "start" },
    { key: "drift", title: "Drift is confirmed", done: Boolean(drift),
      text: drift ? `${drift.detector} confirmed drift at outcome #${drift.step + 1}, ${drift.step - drift.change_point_step} outcomes after the estimated change.` : "The detector confirms the rise is significant. A notification appears.", action: "start" },
    { key: "version", title: "A new model version is created", done: Boolean(adaptation),
      text: adaptation ? `${adaptation.version} was trained on the post-change window and activated.` : "DriftWear retrains on data from after the change point and activates the new version." },
    { key: "measure", title: "Measure the new model", done: measured && impact?.after_complete,
      text: measured ? `${num(impact.after.n)} outcomes after adaptation; accuracy ${pct(impact.after.accuracy)}.` : "Process one or two more batches so the adapted model collects real outcomes.", action: "step50" },
    { key: "inspect", title: "Inspect before, during and after", done: false, optional: true, link: "/app/drift-performance?stream=simulation",
      text: "Accuracy, precision, recall, F1 and error rate in each phase, on one timeline." },
    { key: "compare", title: "Compare versions in the registry", done: false, optional: true, link: "/app/models?stream=simulation",
      text: "Validation and live metrics side by side, with the lineage of every version." },
    { key: "rollback", title: "Roll back (administrators)", done: Boolean(rollback), link: "/app/models?stream=simulation",
      text: rollback ? `Rolled back ${rollback.from_version} → ${rollback.to_version}.` : "Restore an earlier version with a recorded reason; the server verifies its checksum first." },
    { key: "restored", title: "Predict with the restored version", done: Boolean(rollback) && afterRollback > 0,
      text: rollback ? `${num(Math.max(afterRollback, 0))} outcomes scored by ${rollback.to_version} since the rollback.` : "After a rollback, the next records are predicted by the restored model.", action: rollback ? "step10" : null },
  ];
}

function Guide({ steps, run, busy, disabled }) {
  const current = steps.findIndex((s) => !s.done && !s.optional);
  const labels = { step50: "Next 50", step10: "Next 10", trend: "Change trend", start: "Start streaming" };
  return (
    <ol className="divide-y divide-seam" aria-label="Guided demonstration">
      {steps.map((s, i) => {
        const now = i === current;
        return (
          <li key={s.key} className={`flex gap-3 px-4 py-3 ${now ? "bg-plum-50" : ""}`} aria-current={now ? "step" : undefined}>
            <span className="mt-0.5 w-5 shrink-0 text-right text-xs tabular text-faint">{i + 1}</span>
            <StageIcon status={s.done ? "done" : now ? "pending" : "none"} className="mt-0.5 h-4 w-4" />
            <div className="min-w-0 flex-1">
              <p className={`text-sm font-medium ${s.done || now ? "text-fg" : "text-muted"}`}>{s.title}{s.optional && <span className="font-normal text-faint"> (look)</span>}</p>
              <p className="mt-0.5 text-xs text-muted">{s.text}</p>
              {(now && s.action) || s.link ? (
                <div className="mt-2 flex gap-2">
                  {now && s.action && <button type="button" className="btn btn-primary btn-sm" disabled={busy || disabled} onClick={() => run(s.action)}>{labels[s.action]}</button>}
                  {s.link && <Link to={s.link} className="btn btn-secondary btn-sm">Open</Link>}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function Simulation() {
  const { isAdmin } = useAuth();
  const { events, snapshot } = useRealtime();
  const state = useApi(() => Sim.state(), []);
  const dash = useApi(() => Overview.dashboard("simulation"), []);
  const activations = useApi(() => Models.activations("simulation"), []);
  const [speed, setSpeed] = useState(5);
  const [pauseOnDrift, setPauseOnDrift] = useState(true);
  const [regenerate, setRegenerate] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [metric, setMetric] = useState("error_rate");
  const act = useAction((fn) => fn());

  useRealtimeEvents((ev) => { if (ev.event === "SIMULATION_STATE") state.setData(ev.data); }, "simulation");
  useLiveRefresh(() => { dash.reload({ silent: true }); state.reload({ silent: true }); activations.reload({ silent: true }); }, "simulation", { delay: 1000 });

  const s = state.data;
  const k = dash.data?.kpis;
  const live = snapshot?.simulation;
  const adapting = Boolean(live?.adapting);
  const after = async (r) => { if (r) { state.reload({ silent: true }); dash.reload({ silent: true }); } return r; };
  const commands = {
    step1: () => Sim.step(1, true), step10: () => Sim.step(10, true), step50: () => Sim.step(50, pauseOnDrift),
    trend: () => Sim.changeTrend(), start: () => Sim.start(speed, pauseOnDrift), pause: () => Sim.pause(),
  };
  const run = async (name) => after(await act.run(commands[name]));
  const steps = guide({ state: s, dash: dash.data, activations: activations.data });
  const progress = s ? Math.min(100, Math.round((s.processed / Math.max(1, s.stream_size)) * 100)) : 0;
  const skipped = (s?.trend_changes || []).reduce((sum, t) => sum + (t.skipped_records || 0), 0);
  const impact = dash.data?.impact?.[0];

  return (
    <>
      <PageHeader title="Simulation mode"
        lede="A controlled demonstration of concept drift. A synthetic purchase dataset with three fashion-trend periods is replayed as a stream, so you can change the trend and watch DriftWear detect, adapt and recover." />
      <SimulationBanner>Synthetic data on its own stream, with its own models. Nothing here is customer activity, and none of it is counted in live figures.</SimulationBanner>
      <ErrorNote error={state.error} onRetry={() => state.reload()} className="mb-6" />
      {state.loading && !s ? <Loading label="Loading the simulation state…" rows={4} /> : s && (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-6">
            <Panel>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-muted">Current fashion trend</p>
                  <p className="display mt-0.5 text-2xl text-navy">{s.current_trend}</p>
                  <p className="text-sm text-muted">Period {s.current_period} of the synthetic dataset</p>
                </div>
                <div className="space-y-2 text-right">
                  <StateTrack status={live?.status || s.status} adapting={adapting} adaptingTo={live?.adapting_to} label="Simulation detector state" />
                  <p className="text-sm text-muted">Active model <VersionTag version={live?.model_version || s.model_version} active /></p>
                </div>
              </div>

              <div className="mt-6">
                <div className="flex justify-between text-sm text-muted">
                  <span>Position in the dataset: {num(s.processed)} of {num(s.stream_size)} records{skipped ? ` (${num(skipped)} skipped by trend changes)` : ""}</span>
                  <span className="font-medium text-fg">{s.running ? "Streaming" : s.finished ? "Finished" : "Paused"}</span>
                </div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-sm bg-canvas" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Simulation progress">
                  <div className="h-full bg-navy transition-[width]" style={{ width: `${progress}%` }} />
                </div>
              </div>
              {s.last_message && <p className="mt-3 text-sm text-fg" role="status">{s.last_message}</p>}

              <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-seam pt-5">
                {s.running ? (
                  <button type="button" className="btn btn-secondary" onClick={() => run("pause")} disabled={act.busy}><Pause className="h-4 w-4" aria-hidden="true" />Pause</button>
                ) : (
                  <button type="button" className="btn btn-primary" disabled={act.busy || s.finished} onClick={() => run("start")}><Play className="h-4 w-4" aria-hidden="true" />Start streaming</button>
                )}
                {[["step1", "Next record"], ["step10", "Next 10"], ["step50", "Next 50"]].map(([cmd, label]) => (
                  <button key={cmd} type="button" className="btn btn-secondary" disabled={act.busy || s.running || s.finished} onClick={() => run(cmd)}>
                    <SkipForward className="h-4 w-4" aria-hidden="true" />{label}
                  </button>
                ))}
                <button type="button" className="btn btn-secondary" disabled={act.busy || s.finished} onClick={() => run("trend")}>
                  <Shuffle className="h-4 w-4" aria-hidden="true" />Change fashion trend
                </button>
                {act.busy && <span className="inline-flex items-center gap-2 text-sm text-muted"><Spinner />Working…</span>}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
                <label className="flex items-center gap-2"><span className="text-muted">Speed</span>
                  <select className="input input-sm w-auto" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} disabled={s.running}>
                    {SPEEDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="h-4 w-4 accent-[#172036]" checked={pauseOnDrift} onChange={(e) => setPauseOnDrift(e.target.checked)} />
                  Pause when drift is confirmed
                </label>
                {isAdmin && (
                  <button type="button" className="btn btn-quiet btn-sm ml-auto" onClick={() => setResetOpen(true)} disabled={act.busy}>
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />Reset simulation…
                  </button>
                )}
              </div>
              <ErrorNote error={act.error} className="mt-4" />
            </Panel>

            <Measures>
              <Measure label="Simulated predictions" value={num(k?.predictions)} />
              <Measure label="Recent error rate" value={pct(k?.error_rate_recent)} tone={k?.error_rate_recent > 0.5 ? "drift" : undefined} sub="Last 50 outcomes" />
              <Measure label="Confirmed drifts" value={num(k?.drift_events)} tone={k?.drift_events ? "drift" : undefined} />
              <Measure label="Model versions" value={num(k?.model_versions)} sub={adapting ? `Adapting to ${live?.adapting_to || "a new version"}` : "Adaptation idle"} />
            </Measures>

            <Panel title="What the detector sees" actions={<Tabs size="sm" label="Metric" value={metric} onChange={setMetric}
              tabs={[{ value: "error_rate", label: "Error rate" }, { value: "accuracy", label: "Accuracy" }]} />}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                {metric === "accuracy" ? <SeriesLegend items={[[C.ink, "Active model"], [C.stone, "Frozen v1.0", true]]} /> : <SeriesLegend items={[[C.ink, "Rolling error rate"]]} />}
                <MarkerLegend warnings={metric === "error_rate"} />
              </div>
              <TimelineChart series={dash.data?.series} markers={dash.data?.markers} metric={metric} height={280} />
            </Panel>

            {impact && (
              <Notice tone={impact.recovered ? "stable" : "neutral"} title="What this run demonstrated">
                Accuracy was {pct(impact.before.accuracy)} before the trend change. While {impact.from_version} kept predicting the old pattern it fell to {pct(impact.during.accuracy)};
                {" "}{impact.detector} confirmed drift {impact.step - impact.change_point_step} outcomes after the estimated change, and {impact.to_version || "no new model"}
                {impact.after?.n ? `, trained on the post-change window, reached ${pct(impact.after.accuracy)} on the next ${num(impact.after.n)} outcomes.` : " is still collecting outcomes."}
                {" "}<Link to="/app/drift-performance?stream=simulation" className="link">See every metric</Link>
              </Notice>
            )}
          </div>

          <div className="min-w-0 space-y-6">
            <Panel title="Guided demonstration" description="Each step completes from what the server reports." flush>
              <Guide steps={steps} run={run} busy={act.busy} disabled={s.running || s.finished} />
            </Panel>
            <Panel title="Simulation events" flush>
              <ActivityFeed live={events} initial={dash.data?.recent_events || []} stream="simulation" limit={10}
                only={["WARNING_DETECTED", "DRIFT_DETECTED", "ADAPTATION_STARTED", "ADAPTATION_COMPLETED", "ADAPTATION_FAILED", "MODEL_VERSION_CREATED", "MODEL_ACTIVATED", "TREND_CHANGED", "SIMULATION_RESET"]}
                empty="Trend changes, warnings, drift and new versions appear here as they happen." />
            </Panel>
          </div>
        </div>
      )}
      <ConfirmDialog open={resetOpen} danger title="Reset the simulation?" busy={act.busy} confirmLabel="Reset simulation"
        onCancel={() => setResetOpen(false)} onConfirm={async () => { const r = await run2(); setResetOpen(false); return r; }}>
        <p>Deletes the simulation's predictions, drift events and model versions, then retrains v1.0. Live data, live models and the audit log are not touched.</p>
        <label className="flex items-center gap-2">
          <input type="checkbox" className="h-4 w-4 accent-[#172036]" checked={regenerate} onChange={(e) => setRegenerate(e.target.checked)} />
          Generate a new synthetic dataset (new random seed)
        </label>
      </ConfirmDialog>
    </>
  );

  async function run2() {
    const r = await act.run(() => Sim.reset(regenerate));
    if (r) { state.reload({ silent: true }); dash.reload({ silent: true }); activations.reload({ silent: true }); }
    return r;
  }
}
