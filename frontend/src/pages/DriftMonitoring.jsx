import { useState } from "react";
import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import { MarkerLegend, SeriesLegend, StateShareBar, TimelineChart, C } from "../components/charts";
import { ActivityFeed, DetectorList, DriftLink } from "../components/insights";
import { Badge, ConfirmDialog, DefinitionList, Empty, ErrorNote, Loading, Measure, Measures, Notice, PageHeader, Panel, SeverityBadge,
  SimulationBanner, StateTrack, StreamSwitch, Table, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useLiveRefresh, useRealtime } from "../context/RealtimeContext";
import { Drift, Overview } from "../lib/endpoints";
import { dateTime, num, pct, statusMeta, timeAgo } from "../lib/format";
import { useAction, useApi, useStreamParam } from "../lib/hooks";
import { useMeta } from "../lib/meta";

const DRIFT_EVENTS = ["WARNING_DETECTED", "STATUS_CHANGED", "DRIFT_DETECTED", "ADAPTATION_STARTED", "ADAPTATION_COMPLETED",
  "ADAPTATION_FAILED", "MODEL_VERSION_CREATED", "DETECTOR_CHANGED"];

/** Admin-only: change the primary detector. Only detectors the running server supports are offered. */
function DetectorSwitch({ stream, current, available, onChanged }) {
  const meta = useMeta();
  const [choice, setChoice] = useState(current);
  const [confirming, setConfirming] = useState(false);
  const action = useAction(() => Drift.setDetector(stream, choice));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[160px] flex-1 text-sm">
          <span className="field-label">Primary detector</span>
          <select className="input" value={choice} onChange={(e) => { setChoice(e.target.value); action.reset(); }}>
            {available.map((d) => <option key={d} value={d}>{d === "PageHinkley" ? "Page-Hinkley" : d}</option>)}
          </select>
        </label>
        <button type="button" className="btn btn-secondary" disabled={choice === current || action.busy} onClick={() => setConfirming(true)}>Switch detector</button>
      </div>
      {meta.detector_info?.[choice] && <p className="text-xs text-muted">{meta.detector_info[choice]}</p>}
      {available.length === 1 && <p className="text-xs text-muted">Only {available[0]} can run on this server. ADWIN and Page-Hinkley appear here once the River library is installed.</p>}
      <ErrorNote error={action.error} />
      {action.result && <Notice tone="stable">Switched to {action.result.detector}. Its state was rebuilt from the stored error history; the switch is in the audit log.</Notice>}
      <ConfirmDialog open={confirming} title={`Switch the ${stream} detector to ${choice}?`} busy={action.busy}
        confirmLabel={`Switch to ${choice}`} onCancel={() => setConfirming(false)}
        onConfirm={async () => { const r = await action.run(); setConfirming(false); if (r) onChanged(); }}>
        <p>{choice} becomes the detector that decides when the {stream} model adapts. {current} stops making that decision.</p>
        <p className="text-muted">The new detector replays the stored error history to rebuild its state, so its status may differ from {current}'s. No model is retrained by the switch itself.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function DriftMonitoring() {
  const { isAdmin } = useAuth();
  const [stream, setStream] = useStreamParam(true);
  const { events, snapshot } = useRealtime();
  const stats = useApi(() => Drift.statistics(stream), [stream]);
  const list = useApi(() => Drift.events(stream), [stream]);
  const recent = useApi(() => Overview.recentEvents(150, stream), [stream]);
  useLiveRefresh(() => { stats.reload({ silent: true }); list.reload({ silent: true }); }, stream);

  const d = stats.data;
  const s = d?.status;
  const live = snapshot?.[stream];
  const adapting = Boolean(live?.adapting ?? s?.adapting);
  const status = live?.status || s?.status;
  const q = stream === "simulation" ? "?stream=simulation" : "";

  return (
    <>
      <PageHeader title="Drift monitoring"
        lede="The detector reads the active model's prediction errors one labeled outcome at a time. A sustained rise means the relationship between purchases and categories has changed: concept drift."
        actions={<><Link to={`/app/drift-analysis${q}`} className="btn btn-secondary">Data vs concept drift</Link><StreamSwitch stream={stream} onChange={setStream} /></>} />
      {stream === "simulation" && <SimulationBanner />}
      <ErrorNote error={stats.error} onRetry={() => stats.reload()} className="mb-6" />
      {stats.loading && !d ? <Loading label="Loading the detector state and error stream…" rows={5} /> : d && (
        <div className="space-y-6">
          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Panel>
              <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
              <div>
                <p className="text-sm text-muted">Detector state</p>
                <div className="mt-2"><StateTrack status={status} adapting={adapting} adaptingTo={live?.adapting_to || s.adapting_to} size="lg" /></div>
                <p className="mt-4 text-md text-fg">{adapting ? `Drift is confirmed. A new model is being trained on data from after the change; ${s.model_version} serves predictions until it is ready.` : s.status_text}</p>
                <p className="mt-1 text-sm text-muted">{statusMeta(adapting ? "ADAPTING" : status).meaning}</p>
                {status === "WARNING" && s.warning_start !== null && s.warning_start !== undefined && (
                  <p className="mt-2 text-sm text-warning-ink">In the warning zone since outcome #{s.warning_start + 1}. A warning on its own never retrains the model.</p>
                )}
              </div>
              <DefinitionList items={[
                ["Primary detector", s.detector],
                ["Implementation", s.detector_backend],
                ["Model being watched", <VersionTag key="v" version={s.model_version} active />],
                ["Outcomes since the detector reset", num(s.values_since_reset)],
                ["Calibration errors", `${num(s.calibration_size)} out-of-fold errors of ${s.model_version}`],
                ["Scheduled refreshes", s.pending_refresh?.length ? `At outcomes ${s.pending_refresh.map((x) => `#${x + 1}`).join(", ")}` : "None pending"],
              ]} />
            </div>
              <p className="mt-5 border-t border-seam pt-3 text-sm text-muted">{s.detector_description}</p>
            </Panel>
            <Panel title="Detectors" description={d.detectors.note}>
              <DetectorList primary={d.detectors.primary} status={status} adapting={adapting} shadows={d.detectors.shadow_status}
                available={d.detectors.available} backend={d.detectors.backend} />
              <div className="mt-4 border-t border-seam pt-4">
                {isAdmin ? <DetectorSwitch key={`${stream}-${s.detector}`} stream={stream} current={s.detector} available={s.available_detectors}
                  onChanged={() => stats.reload({ silent: true })} />
                  : <p className="text-sm text-muted">Only administrators can change the primary detector.</p>}
              </div>
            </Panel>
          </div>

          <Measures>
            <Measure label="Confirmed drifts" value={num(d.summary.drift_events)} tone={d.summary.drift_events ? "drift" : undefined} sub="Triggered adaptation" />
            <Measure label="Warnings" value={num(d.summary.warnings)} tone={d.summary.warnings ? "warning" : undefined} sub="Entries into the warning zone" />
            <Measure label="Mean detection delay" value={d.summary.mean_detection_delay ?? "N/A"} sub="Outcomes from change point to alarm" />
            <Measure label="Mean retraining window" value={d.summary.mean_window_size ?? "N/A"} sub="Post-change outcomes per adaptation" />
            <Measure label="Outcomes monitored" value={num(d.summary.records_monitored)} sub="Labeled outcomes in the error stream" />
          </Measures>

          <Panel title="The error stream" description="Rolling error rate of whichever model was active, with every warning, confirmed drift and refresh marked."
            footer={<div className="max-w-xl"><p className="mb-2 text-xs text-muted">Labeled outcomes by the detector state they produced</p><StateShareBar counts={d.status_counts} /></div>}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><SeriesLegend items={[[C.ink, "Rolling error rate (last 50)"]]} /><MarkerLegend /></div>
            <TimelineChart series={d.series} markers={d.markers} metric="error_rate" height={320} />
          </Panel>

          <Panel title="Confirmed drift events" description="Each one led to an adaptation attempt. Open one to see performance before, during and after." flush>
              <ErrorNote error={list.error} onRetry={() => list.reload()} className="m-4" />
              {list.data?.length ? (
                <Table caption="Confirmed drift events">
                  <thead><tr><th className="th">Event</th><th className="th">Detected</th><th className="th">Change point → alarm</th>
                    <th className="th">Accuracy before → during → after</th><th className="th">Model</th><th className="th">Result</th></tr></thead>
                  <tbody>
                    {list.data.map((e) => (
                      <tr key={e.id}>
                        <td className="td"><DriftLink eventKey={e.event_key} stream={stream}>{e.event_key}</DriftLink>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">{e.detector}<SeverityBadge severity={e.severity} /></div></td>
                        <td className="td whitespace-nowrap text-muted" title={dateTime(e.detected_at)}>{timeAgo(e.detected_at)}</td>
                        <td className="td whitespace-nowrap tabular">#{(e.change_point_step ?? 0) + 1} → #{e.stream_step + 1}
                          <div className="text-xs text-muted">{e.detection_delay ?? "—"} outcomes later · error {pct(e.error_rate, 0)}</div></td>
                        <td className="td whitespace-nowrap tabular">{pct(e.accuracy_stable, 0)} → <span className="text-drift-ink">{pct(e.accuracy_degraded, 0)}</span> → {e.accuracy_after === null ? <span className="text-muted">measuring</span> : <span className="text-adapted-ink">{pct(e.accuracy_after, 0)}</span>}</td>
                        <td className="td whitespace-nowrap"><VersionTag version={e.previous_model_version} /> <span className="text-faint">→</span> {e.new_model_version ? <VersionTag version={e.new_model_version} /> : <span className="text-muted">kept</span>}</td>
                        <td className="td">{e.action === "Model Updated" ? <Badge tone="adapted" icon>Adapted</Badge> : <Badge tone="drift" icon>{e.action}</Badge>}
                          {e.window_size ? <div className="mt-1 text-xs text-muted">Trained on {e.window_size} outcomes</div> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : list.loading ? <Loading label="Loading drift events…" rows={2} className="px-5" /> : (
                <Empty title="No confirmed drift on this stream" icon={Activity}
                  action={stream === "simulation" ? <Link to="/app/simulation" className="btn btn-primary">Open the simulation</Link> : null}>
                  {stream === "simulation" ? "Change the fashion trend in the simulation to watch the detector react."
                    : `The detector has read ${num(d.summary.records_monitored)} labeled outcomes without a significant, sustained rise in errors.`}
                </Empty>
              )}
          </Panel>

          <Panel title="Detector activity" description="Warnings, drift, adaptations and detector changes on this stream" flush>
                <ActivityFeed live={events} initial={recent.data || []} stream={stream} only={DRIFT_EVENTS} limit={8}
                  empty="No warnings, drift or adaptations recently. They appear here the moment they happen." />
          </Panel>
        </div>
      )}
    </>
  );
}
