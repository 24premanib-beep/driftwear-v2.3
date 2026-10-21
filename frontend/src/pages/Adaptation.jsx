import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RefreshCcw } from "lucide-react";
import { ConfusionMatrix, ImportanceBars, PairedBars, SeriesLegend, TimelineChart, VersionStrip, MarkerLegend, C } from "../components/charts";
import { DriftLink, recoveryVerdict, StageIcon } from "../components/insights";
import { Badge, ConfirmDialog, Empty, ErrorNote, Loading, Measure, Measures, Notice, PageHeader, Panel, SimulationBanner,
  Spinner, StreamSwitch, Table, Tabs, ToneIcon, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh, useRealtime } from "../context/RealtimeContext";
import { Drift, Models, Performance } from "../lib/endpoints";
import { dateTime, KIND_LABELS, num, pct, timeAgo } from "../lib/format";
import { useAction, useApi, useQueryParam, useStreamParam } from "../lib/hooks";
import { compareVersions } from "../lib/lineage";

const KIND_TONE = { initial: "neutral", drift: "drift", refresh: "adapted", manual: "plum" };

/**
 * Drift confirmed → change point → post-change window → retrain → new version → activated → monitored, filled with
 * the stored facts of the most recent drift adaptation. A stage without data is shown as not reached.
 */
function AdaptationFlow({ version, impact, adapting, adaptingTo }) {
  const v = version;
  const verdict = impact ? recoveryVerdict(impact) : null;
  const steps = [
    { label: "Drift confirmed", status: impact ? "done" : "none", value: impact ? `${impact.event_key} by ${impact.detector}` : "—", sub: impact ? `Outcome #${impact.step + 1}` : null },
    { label: "Change point estimated", status: impact ? "done" : "none", value: impact ? `Outcome #${impact.change_point_step + 1}` : "—", sub: impact ? `${impact.step - impact.change_point_step} outcomes before the alarm` : null },
    { label: "Post-change data selected", status: v ? "done" : adapting ? "pending" : "none", value: v?.window_start !== null && v?.window_start !== undefined ? `Outcomes #${v.window_start + 1}–#${v.window_end + 1}` : "—", sub: v ? `${num(v.training_records)} labeled records` : null },
    { label: "Model retrained", status: v ? "done" : adapting ? "pending" : "none", value: v ? `Validation accuracy ${pct(v.accuracy)}` : adapting ? "Training…" : "—", sub: v ? "Out-of-fold, on its own window" : null },
    { label: "New version created", status: v ? "done" : adapting ? "pending" : "none", value: v ? <VersionTag version={v.version} /> : adaptingTo ? <VersionTag version={adaptingTo} /> : "—", sub: v ? `${KIND_LABELS[v.kind]}, from ${v.parent_version}` : null },
    { label: "Version activated", status: v ? "done" : "none", value: v ? timeAgo(v.created_at) : "—", sub: v ? dateTime(v.created_at) : null },
    { label: "Performance monitored", status: !impact ? "none" : impact.after?.n ? (impact.recovered === false ? "failed" : "done") : "pending",
      value: verdict ? verdict.title : "—", sub: impact?.after?.n ? `${num(impact.after.n)} outcomes after adaptation` : impact ? "Waiting for outcomes" : null },
  ];
  return (
    <div className="hairlines"><ol className="hairlines-inner sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7" aria-label="Most recent drift adaptation">
      {steps.map((s, i) => (
        <li key={s.label} className={`px-4 py-3 ${s.status === "none" ? "bg-canvas/70" : ""}`}>
          <div className="flex items-center gap-2 text-xs text-muted"><span className="tabular text-faint">{i + 1}</span><StageIcon status={s.status} className="h-3.5 w-3.5" />{s.label}</div>
          <div className="mt-1.5 text-sm font-semibold text-fg">{s.value}</div>
          {s.sub && <div className="mt-0.5 text-xs text-muted">{s.sub}</div>}
        </li>
      ))}
    </ol></div>
  );
}

function RetrainNow({ stream, onDone }) {
  const [open, setOpen] = useState(false);
  const run = useAction(() => Models.retrainNow(stream));
  return (
    <div>
      <p className="text-sm text-muted">Trains a new minor version on the most recent labeled outcomes and makes it active. Use it after correcting data, or when you know the market changed before the detector does.</p>
      <button type="button" className="btn btn-secondary mt-3" onClick={() => { run.reset(); setOpen(true); }} disabled={run.busy}>
        <RefreshCcw className="h-4 w-4" aria-hidden="true" />Retrain now…
      </button>
      {run.result && <Notice tone="adapted" className="mt-3" title={`${run.result.version} is active`}>Trained on {num(run.result.records_used)} records; the server confirmed the new version.</Notice>}
      {run.error && !open && <ErrorNote error={run.error} className="mt-3" title="Retraining failed: the previous model is still active" />}
      <ConfirmDialog open={open} title={`Retrain the ${stream} model now?`} busy={run.busy} confirmLabel="Retrain and activate"
        onCancel={() => setOpen(false)} onConfirm={async () => { const r = await run.run(); setOpen(false); if (r) onDone(); }}>
        <p>A new minor version is trained on recent labeled outcomes of the {stream} stream and becomes active as soon as the server has saved it.</p>
        <ul className="list-disc space-y-1 pl-5 text-muted">
          <li>The current version stays in the registry and can be activated again.</li>
          <li>If training or saving fails, the current model stays active and the failure is audited.</li>
          <li>The drift detector restarts for the new version.</li>
        </ul>
      </ConfirmDialog>
    </div>
  );
}

function AdaptationTab({ stream, isAdmin }) {
  const { snapshot } = useRealtime();
  const navigate = useNavigate();
  const models = useApi(() => Models.list(stream), [stream]);
  const stats = useApi(() => Drift.statistics(stream), [stream]);
  const drifts = useApi(() => Drift.events(stream), [stream]);
  useLiveRefresh(() => { models.reload({ silent: true }); stats.reload({ silent: true }); drifts.reload({ silent: true }); }, stream, { delay: 1200 });
  const live = snapshot?.[stream];
  const items = models.data?.items || [];
  const adaptations = items.filter((v) => v.kind !== "initial").sort((a, b) => compareVersions(b.version, a.version));
  const impact = stats.data?.impact?.length ? stats.data.impact[stats.data.impact.length - 1] : null;
  const flowVersion = impact?.to_version ? items.find((v) => v.version === impact.to_version) : null;
  const failed = (drifts.data || []).filter((e) => e.action !== "Model Updated");
  const q = stream === "simulation" ? "?stream=simulation" : "";

  if (models.loading && !models.data) return <Loading label="Loading model versions and adaptations…" rows={5} />;
  return (
    <div className="space-y-6">
      <ErrorNote error={models.error || stats.error} onRetry={() => { models.reload(); stats.reload(); }} />
      {live?.adapting && (
        <Notice tone="adapted" icon={false} title={<span className="inline-flex items-center gap-2"><Spinner />Adapting now{live.adapting_to ? `: training ${live.adapting_to}` : ""}</span>}>
          Concept drift was confirmed. {live.model_version} keeps serving predictions until the server has saved and activated the new version.
        </Notice>
      )}
      <Panel title={impact ? `Latest drift adaptation: ${impact.event_key}` : "How a drift adaptation unfolds"}
        description={impact ? "Every stage comes from stored records of the drift event and the version it created." : "No drift has been confirmed on this stream yet, so no stage has run."}
        actions={impact && <DriftLink eventKey={impact.event_key} stream={stream}>Before, during and after</DriftLink>}>
        <AdaptationFlow version={flowVersion} impact={impact} adapting={live?.adapting} adaptingTo={live?.adapting_to} />
      </Panel>

      <Panel title="Which model served which part of the stream" description="Select a version to open it in the registry.">
        <VersionStrip versions={items} totalSteps={stats.data?.status?.records_processed}
          onSelect={(version) => navigate(`/app/models?${new URLSearchParams({ ...(stream === "simulation" ? { stream } : {}), version })}`)} />
      </Panel>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel title="Adaptation history" description="Newest first. Validation scores are out-of-fold on each version's own training window; live accuracy is measured afterwards on real outcomes." flush>
          {adaptations.length ? (
            <ol className="divide-y divide-seam">
              {adaptations.map((v) => (
                <li key={v.version} className="grid gap-x-6 gap-y-2 px-5 py-4 md:grid-cols-[150px_minmax(0,1fr)_auto]">
                  <div className="space-y-1.5">
                    <VersionTag version={v.version} active={v.is_active} size="lg" />
                    <div><Badge tone={KIND_TONE[v.kind]}>{KIND_LABELS[v.kind]}</Badge></div>
                  </div>
                  <div className="min-w-0 text-sm">
                    <p className="text-fg">{v.trigger}. Replaced <VersionTag version={v.parent_version} /> at outcome #{v.created_step + 1}.</p>
                    <p className="mt-1 text-muted">Trained on {num(v.training_records)} records{v.window_start !== null ? ` (outcomes #${v.window_start + 1}–#${v.window_end + 1})` : ""}{v.data_period ? `, ${v.data_period}` : ""}.</p>
                    <p className="mt-1 text-muted">Validation accuracy {pct(v.accuracy)}, F1 {pct(v.f1_score)} · {dateTime(v.created_at)}</p>
                  </div>
                  <dl className="grid grid-cols-2 gap-4 text-sm md:text-right">
                    <div><dt className="text-xs text-muted">Live accuracy</dt><dd className="figure text-lg text-fg">{v.live_metrics ? pct(v.live_metrics.accuracy) : "N/A"}</dd>
                      <dd className="text-xs text-muted">{v.live_metrics ? `${num(v.live_metrics.n)} outcomes` : "none yet"}</dd></div>
                    <div><dt className="text-xs text-muted">Before → after</dt><dd className="figure text-lg text-fg">{pct(v.accuracy_before, 0)} → {v.accuracy_after === null ? "…" : pct(v.accuracy_after, 0)}</dd>
                      <dd className="text-xs text-muted">{v.accuracy_after === null ? "measuring" : "rolling, live"}</dd></div>
                  </dl>
                </li>
              ))}
            </ol>
          ) : <Empty title="No adaptations yet" icon={RefreshCcw}>The model adapts automatically when drift is confirmed. {isAdmin ? "You can also retrain it manually." : ""}</Empty>}
          {failed.length > 0 && (
            <div className="border-t border-seam px-5 py-4">
              <h3 className="text-sm font-semibold text-fg">Adaptations that failed</h3>
              <ul className="mt-2 space-y-1.5 text-sm">
                {failed.map((e) => (
                  <li key={e.id} className="flex items-start gap-2"><ToneIcon tone="drift" className="mt-0.5 h-4 w-4" />
                    <span>{e.event_key} at outcome #{e.stream_step + 1}: {e.details?.adaptation_error || e.action}. <VersionTag version={e.previous_model_version} /> stayed active.</span></li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
        <div className="space-y-6">
          <Panel title="Retrain on request">
            {isAdmin ? <RetrainNow stream={stream} onDone={() => { models.reload({ silent: true }); stats.reload({ silent: true }); }} />
              : <p className="text-sm text-muted">Manual retraining is limited to administrators. The model still adapts on its own when drift is confirmed.</p>}
          </Panel>
          <Panel title="Scheduled refreshes">
            <p className="text-sm text-muted">After a drift adaptation, DriftWear retrains again once about 25, 75 and 150 more outcomes of the new pattern have arrived (minor versions such as v2.1, v2.2, v2.3).</p>
            <p className="mt-2 text-sm text-fg">{stats.data?.status?.pending_refresh?.length
              ? `Pending at outcomes ${stats.data.status.pending_refresh.map((x) => `#${x + 1}`).join(", ")}.`
              : "None pending right now."}</p>
            <Link to={`/app/models${q}`} className="link mt-3 inline-block text-sm">Compare versions in the registry</Link>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function PerformanceTab({ stream }) {
  const perf = useApi(() => Performance.summary(stream), [stream]);
  const dash = useApi(() => Drift.statistics(stream), [stream]);
  useLiveRefresh(() => { perf.reload({ silent: true }); dash.reload({ silent: true }); }, stream, { delay: 2500 });
  const p = perf.data;
  if (perf.loading && !p) return <Loading label="Loading performance on labeled outcomes…" rows={5} />;
  if (perf.error) return <ErrorNote error={perf.error} onRetry={() => perf.reload()} />;
  if (!p) return null;
  const a = p.summary?.adaptive;
  const b = p.summary?.baseline;
  if (!p.summary?.n) {
    return <Empty title="No labeled outcomes on this stream yet">Performance is measured only on predictions whose actual category has arrived.
      {stream === "simulation" ? " Process records in the simulation to start." : " Record outcomes on the Live data page."}</Empty>;
  }
  const versions = (p.by_version || []).map((v) => ({ ...v, label: v.version }));
  return (
    <div className="space-y-6">
      <Measures>
        <Measure label="Accuracy" value={pct(a.accuracy)} sub={`Frozen v1.0: ${pct(b.accuracy)}`} />
        <Measure label="Precision (macro)" value={pct(a.precision)} sub={`Frozen v1.0: ${pct(b.precision)}`} />
        <Measure label="Recall (macro)" value={pct(a.recall)} sub={`Frozen v1.0: ${pct(b.recall)}`} />
        <Measure label="F1 (macro)" value={pct(a.f1)} sub={`Frozen v1.0: ${pct(b.f1)}`} />
        <Measure label="Labeled outcomes" value={num(p.summary.n)} sub="Every metric here uses only these" />
      </Measures>
      <Panel title="Accuracy over time: adaptive against frozen" description="The adaptive line switches model at every adaptation; the stone line is v1.0 scored on the same records.">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><SeriesLegend items={[[C.ink, "Active model"], [C.stone, "Frozen v1.0", true]]} /><MarkerLegend warnings={false} /></div>
        <TimelineChart series={p.series} markers={dash.data?.markers} metric="accuracy" height={300} />
      </Panel>
      <div className="grid items-start gap-6 xl:grid-cols-2">
        <Panel title="Live accuracy per model version" description="Each version is judged on the outcomes it served, next to frozen v1.0 on the same outcomes.">
          <PairedBars rows={versions} x="label" a={{ key: "baseline_accuracy", name: "Frozen v1.0", color: C.stone }} b={{ key: "accuracy", name: "This version", color: C.ink }} domain={[0, 1]} />
          <Table className="mt-4" caption="Live metrics per version">
            <thead><tr><th className="th">Version</th><th className="th">Outcomes</th><th className="th">Served</th><th className="th">Accuracy</th><th className="th">F1</th></tr></thead>
            <tbody>{versions.map((v) => (
              <tr key={v.version}><td className="td"><VersionTag version={v.version} /></td><td className="td tabular">{num(v.n)}</td>
                <td className="td tabular text-muted">#{v.first_step + 1}–#{v.last_step + 1}</td><td className="td tabular">{pct(v.accuracy)}</td><td className="td tabular">{pct(v.f1)}</td></tr>))}
            </tbody>
          </Table>
        </Panel>
        {stream === "simulation" ? (
          <Panel title="Adaptive against frozen, per fashion trend" description="Trend periods are known only for simulated data.">
            <PairedBars rows={(p.by_period || []).map((r) => ({ ...r, label: r.trend ? `${r.period}. ${r.trend}` : `Period ${r.period}` }))} x="label"
              a={{ key: "static_accuracy", name: "Frozen v1.0", color: C.stone }} b={{ key: "adaptive_accuracy", name: "Adaptive", color: C.ink }} domain={[0, 1]} />
          </Panel>
        ) : (
          <Panel title="What customers bought against what was predicted" description="Share of each category in the last 200 labeled outcomes.">
            <PairedBars rows={p.category_mix} x="category" a={{ key: "actual", name: "Bought", color: C.stone }} b={{ key: "predicted", name: "Predicted", color: C.ink }} />
          </Panel>
        )}
      </div>
      <div className={`grid items-start gap-6 ${stream === "simulation" ? "xl:grid-cols-2" : ""}`}>
        <Panel title="Confusion matrix" description="Rows: what was bought. Columns: what was predicted. The diagonal is correct.">
          <ConfusionMatrix labels={p.confusion_matrix.labels} matrix={p.confusion_matrix.matrix} />
        </Panel>
        {stream === "simulation" && (
          <Panel title="What customers bought against what was predicted" description="Share of each category in the last 200 labeled outcomes.">
            <PairedBars rows={p.category_mix} x="category" a={{ key: "actual", name: "Bought", color: C.stone }} b={{ key: "predicted", name: "Predicted", color: C.ink }} />
          </Panel>
        )}
      </div>
      <Panel title="What each model relies on" description="Feature importance (mean decrease in impurity) of the active model and of frozen v1.0. A change in what the model relies on is one sign the pattern it learned has changed.">
        <div className="grid gap-8 md:grid-cols-2">
          <div><h3 className="mb-2 text-sm font-medium text-fg">Active model</h3><ImportanceBars items={p.feature_importance?.current} /></div>
          <div><h3 className="mb-2 text-sm font-medium text-fg">Frozen v1.0</h3><ImportanceBars items={p.feature_importance?.baseline} color="bg-stone" /></div>
        </div>
      </Panel>
    </div>
  );
}

export default function Adaptation() {
  const { isAdmin } = useAuth();
  const [stream, setStream] = useStreamParam(true);
  const [tab, setTab] = useQueryParam("tab", "adaptation");
  return (
    <>
      <PageHeader title="Adaptation & performance"
        lede="How the model changed itself and whether it paid off. Each adaptation retrains on data from after the change point, so the model learns the new pattern instead of averaging old and new."
        actions={<StreamSwitch stream={stream} onChange={setStream} />}>
        <div className="mt-5"><Tabs label="View" value={tab} onChange={setTab} tabs={[{ value: "adaptation", label: "Adaptation" }, { value: "performance", label: "Performance" }]} /></div>
      </PageHeader>
      {stream === "simulation" && <SimulationBanner />}
      {tab === "performance" ? <PerformanceTab stream={stream} /> : <AdaptationTab stream={stream} isAdmin={isAdmin} />}
    </>
  );
}
