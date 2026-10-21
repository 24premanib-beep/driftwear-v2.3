import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { ComponentStatus, DetectorList, HealthPanel } from "../components/insights";
import { DefinitionList, ErrorNote, Loading, Measure, Measures, PageHeader, Panel, SimulationBanner, StateBadge, StreamSwitch, Table,
  ToneIcon, VersionTag, na, has, tone } from "../components/ui";
import { useLiveRefresh, useRealtime } from "../context/RealtimeContext";
import { System } from "../lib/endpoints";
import { componentMeta, dateTime, duration, num, pct, timeAgo } from "../lib/format";
import { useApi, useStreamParam } from "../lib/hooks";
import { useMeta } from "../lib/meta";

const POLL_MS = 10000;   // component health has no push channel: a database outage cannot announce itself
const ms = (v) => `${v < 10 ? v.toFixed(1) : Math.round(v)} ms`;
const PERF_ROWS = [["accuracy", "Accuracy"], ["precision", "Precision (macro)"], ["recall", "Recall (macro)"], ["f1", "F1 (macro)"], ["error_rate", "Error rate"]];

function Group({ title, scope, children }) {
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="text-md font-semibold text-fg">{title}</h2>
        {scope && <p className="text-xs text-muted">{scope}</p>}
      </div>
      {children}
    </section>
  );
}

function When({ value }) {
  return value ? <span title={dateTime(value)}>{timeAgo(value)}</span> : <span className="text-muted">Never</span>;
}

export default function SystemMonitoring() {
  const [stream, setStream] = useStreamParam(true);
  const { connection } = useRealtime();
  const meta = useMeta();
  const [auto, setAuto] = useState(true);
  const [updatedAt, setUpdatedAt] = useState(null);
  const mon = useApi(() => System.monitoring(stream), [stream]);
  useLiveRefresh(() => auto && mon.reload({ silent: true }), stream, { delay: 1500 });
  useEffect(() => {
    if (!auto) return undefined;
    const t = setInterval(() => mon.reload({ silent: true }), POLL_MS);
    return () => clearInterval(t);
  }, [auto, mon.reload]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (mon.data) setUpdatedAt(new Date().toISOString()); }, [mon.data]);

  const m = mon.data;
  const c = m?.components;
  const pm = m?.pipeline_metrics;
  const cm = m?.current_model;
  const ml = m?.ml;
  const dr = m?.drift;
  const data = m?.data;
  const perf = m?.performance;
  const res = m?.system_health?.resources;
  const apiStats = m?.system_health?.api;
  const overall = componentMeta(m?.overall);

  return (
    <>
      <PageHeader title="System monitoring"
        lede="Measured values only: from the database, the running pipeline and this API process. Anything that cannot be measured shows N/A."
        actions={<>
          <label className="flex items-center gap-2 text-sm text-muted"><input type="checkbox" className="h-4 w-4 accent-[#172036]" checked={auto} onChange={(e) => setAuto(e.target.checked)} />Auto-refresh</label>
          <button type="button" className="btn btn-secondary btn-sm py-2" onClick={() => mon.reload({ silent: true })}><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />Refresh</button>
          <StreamSwitch stream={stream} onChange={setStream} />
        </>} />
      {stream === "simulation" && <SimulationBanner>The machine-learning, drift and performance groups show the simulation stream. Application, data and infrastructure figures are shared, with live and simulation counted separately.</SimulationBanner>}
      <ErrorNote error={mon.error} onRetry={() => mon.reload()} className="mb-6" title="Monitoring data could not be loaded" />
      {mon.loading && !m ? <Loading label="Collecting component health, pipeline counters and resource usage…" rows={6} /> : m && (
        <div className="space-y-8">
          <div className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border px-5 py-3.5 ${tone(overall.tone).border} ${tone(overall.tone).soft}`} role="status">
            <span className={`flex items-center gap-2 text-md font-semibold ${tone(overall.tone).text}`}><ToneIcon tone={overall.tone} className="h-5 w-5" />System {overall.label.toLowerCase()}</span>
            <span className="text-sm text-muted">{auto ? `Refreshes on pipeline events and every ${POLL_MS / 1000} s` : "Auto-refresh paused"} · updated {updatedAt ? timeAgo(updatedAt) : "—"} · API up for {duration(c.api.uptime_seconds)}</span>
          </div>

          <Group title="Application" scope="Component checks, the same as /health, /health/db, /health/ml and /health/websocket">
            <div className="hairlines"><div className="hairlines-inner sm:grid-cols-2 xl:grid-cols-5">
              <ComponentStatus name="API" check={c.api}>Version {m.application?.api?.version || "—"} · {m.application?.api?.environment}</ComponentStatus>
              <ComponentStatus name="Database" check={c.database}>{has(c.database.latency_ms) ? `${c.database.latency_ms} ms · ` : ""}{c.database.dialect || ""} · schema {c.database.revision || "not versioned"}</ComponentStatus>
              <ComponentStatus name="Real-time updates" check={c.websocket}>{num(c.websocket.clients)} clients · {num(c.websocket.events_published)} events sent · this tab: {connection}</ComponentStatus>
              <ComponentStatus name="ML pipeline" check={c.ml_pipeline}>Queue: {num(c.ml_pipeline.queue?.pending ?? 0)} waiting, {num(c.ml_pipeline.queue?.completed ?? 0)} done{c.ml_pipeline.queue?.running ? `, running ${c.ml_pipeline.queue.running}` : ""}</ComponentStatus>
              <ComponentStatus name="Model storage" check={c.model_storage}>{c.model_storage.backend || "—"} · active files: {Object.entries(c.model_storage.active_models || {}).map(([s2, ok]) => `${s2} ${ok ? "present" : "missing"}`).join(", ") || "—"}</ComponentStatus>
            </div></div>
            {apiStats && (
              <Measures className="mt-3">
                <Measure label="API requests" value={num(apiStats.total_requests)} sub={`${num(apiStats.requests_last_minute)} in the last minute`} />
                <Measure label="Request latency" value={apiStats.latency?.n ? ms(apiStats.latency.avg_ms) : "N/A"} sub={apiStats.latency?.n ? `p95 ${ms(apiStats.latency.p95_ms)}, max ${ms(apiStats.latency.max_ms)}` : "No requests measured"} />
                <Measure label="Server errors (5xx)" value={na(apiStats.server_error_rate, (v) => pct(v))} tone={apiStats.by_status?.["5xx"] ? "drift" : undefined} sub={`${num(apiStats.by_status?.["5xx"])} requests`} />
                <Measure label="Client errors (4xx)" value={na(apiStats.client_error_rate, (v) => pct(v))} sub={`${num(apiStats.by_status?.["4xx"])} requests, e.g. validation`} />
              </Measures>
            )}
            {apiStats && <p className="mt-1.5 text-xs text-muted">{apiStats.note}</p>}
          </Group>

          {ml && (
            <Group title="Machine learning" scope={`Success rate and latency are per API process since ${dateTime(ml.counters_since)}; counts come from stored data`}>
              <Measures>
                <Measure label="Predictions" value={num(ml.total_predictions)} sub={`${num(ml.outcomes_received)} with an actual outcome`} />
                <Measure label="Inference latency" value={na(ml.avg_latency_ms, ms)} sub={has(ml.p95_latency_ms) ? `p95 ${ms(ml.p95_latency_ms)} · ${num(ml.latency_samples)} samples` : "No predictions in this process yet"} />
                <Measure label="Prediction success" value={na(ml.prediction_success_rate, (v) => pct(v))} sub={`${num(ml.predictions_failed)} failed`} />
                <Measure label="Prediction error rate" value={na(ml.prediction_error_rate, (v) => pct(v))} sub={`Last 50: ${na(ml.prediction_error_rate_recent, (v) => pct(v))}`} tone={ml.prediction_error_rate_recent > 0.5 ? "drift" : undefined} />
                <Measure label="Active model" value={<VersionTag version={ml.current_model_version} active size="lg" />} sub={`${num(ml.models_created)} versions, ${num(ml.adaptations)} adaptations`} />
              </Measures>
            </Group>
          )}

          <div className="grid items-start gap-6 xl:grid-cols-2">
            {dr && (
              <Group title="Concept drift" scope={dr.note}>
                <Panel>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <StateBadge status={dr.current_status} adapting={dr.adapting} size="lg" />
                    <span className="text-sm text-muted">Detector <strong className="font-medium text-fg">{dr.current_detector}</strong></span>
                  </div>
                  <div className="mt-5" />
                  <DefinitionList items={[
                    ["Confirmed drifts", num(dr.confirmed_drifts)], ["Warnings", `${num(dr.warnings)}${has(dr.last_warning_step) ? `, last at outcome #${num(dr.last_warning_step + 1)}` : ""}`],
                    ["Adapted after drift", num(dr.adapted)], ["Failed adaptations", num(dr.failed_adaptations)],
                    ["Last drift", dr.last_drift_at ? <When key="w" value={dr.last_drift_at} /> : "Never"], ["Warning zone since", has(dr.warning_start) ? `Outcome #${dr.warning_start + 1}` : "Not in warning"],
                  ]} />
                </Panel>
              </Group>
            )}
            {perf && (
              <Group title="Model performance" scope="Labeled outcomes of this stream">
                <Panel flush>
                  <Table caption="Model performance">
                    <thead><tr><th className="th">Metric</th><th className="th">Last {perf.recent_window} outcomes</th><th className="th">All outcomes</th></tr></thead>
                    <tbody>
                      {PERF_ROWS.map(([key, label]) => (
                        <tr key={key}><td className="td text-muted">{label}</td><td className="td font-medium tabular">{na(perf.recent[key], (v) => pct(v))}</td><td className="td tabular">{na(perf.overall[key], (v) => pct(v))}</td></tr>
                      ))}
                      <tr><td className="td text-muted">Outcomes</td><td className="td tabular">{num(perf.recent.n)}</td><td className="td tabular">{num(perf.overall.n)}</td></tr>
                    </tbody>
                  </Table>
                </Panel>
              </Group>
            )}
          </div>

          {data && (
            <Group title="Data" scope="Every way data enters the platform; live and simulation are counted separately">
              <Measures>
                <Measure label="Live predictions" value={num(data.live_predictions)} sub={`${num(data.live_events)} live events · ${num(data.prediction_form)} from the form`} />
                <Measure label="Live events rejected" value={num(data.rejected_events)} tone={data.rejected_events ? "warning" : undefined} sub={has(data.event_rejection_rate) ? `${pct(data.event_rejection_rate)} of live events` : "N/A"} />
                <Measure label="Uploaded records" value={num(data.uploaded_records)} sub={`${num(data.uploaded_records_pending)} waiting · ${num(data.uploaded_records_processed)} processed`} />
                <Measure label="Upload rows rejected" value={num(data.upload_rows_rejected)} tone={data.upload_rows_rejected ? "warning" : undefined} sub={`${num(data.uploads)} uploads · ${num(data.upload_rows_duplicate)} duplicates`} />
                <Measure label="Simulation records" value={num(data.simulation_events)} sub="Synthetic, never in live figures" />
              </Measures>
            </Group>
          )}

          <div className="grid items-start gap-6 xl:grid-cols-2">
            <Group title="System health" scope={res?.note}>
              <Panel>
                <DefinitionList items={[
                  ["API process CPU", has(res?.process_cpu_percent) ? `${res.process_cpu_percent}% of one core (over ${res.cpu_window_seconds} s)` : "N/A"],
                  ["CPU cores", na(res?.cpu_count)], ["Load average (1 min)", na(res?.load_average_1m)],
                  ["API process memory", na(res?.process_memory_mb, (v) => `${num(v)} MB`)],
                  ["Host memory used", has(res?.system_memory_used_percent) ? `${res.system_memory_used_percent}% of ${num(res.system_memory_total_mb)} MB` : "N/A",
                    "Inside a container this is the host's view; a container memory limit is not reflected."],
                  ["Database", `${m.system_health.database.connected ? "Connected" : "Not reachable"} · ${na(m.system_health.database.latency_ms, ms)}`],
                ]} />
              </Panel>
            </Group>
            <Group title="Pipeline" scope={m.runtime.metrics_note}>
              <Panel>
                <DefinitionList items={[
                  ["Outcomes fed to the detector", num(pm.records_processed)], ["Awaiting outcome", num(pm.awaiting_outcome)],
                  ["Predictions by source", Object.entries(pm.predictions_by_source).map(([k2, v]) => `${k2} ${num(v)}`).join(" · ") || "None yet"],
                  ["Failed jobs", `${num(pm.failed_jobs)} failed · ${num(pm.rejected_jobs)} rejected (4xx)`],
                  ["Last prediction", <When key="p" value={pm.last_prediction_at} />], ["Last drift check", <When key="c" value={pm.last_drift_check_at} />],
                  ["Last drift", <When key="d" value={pm.last_drift_at} />], ["Last adaptation", <When key="a" value={pm.last_adaptation_at} />],
                ]} />
              </Panel>
            </Group>
          </div>

          {apiStats?.endpoints?.length > 0 && (
            <Group title="Busiest API endpoints" scope="This API process since it started">
              <Panel flush>
                <Table caption="Busiest API endpoints">
                  <thead><tr><th className="th">Endpoint</th><th className="th">Requests</th><th className="th">5xx</th><th className="th">Average</th><th className="th">p95</th></tr></thead>
                  <tbody>
                    {apiStats.endpoints.map((e) => (
                      <tr key={e.endpoint}><td className="td font-mono text-xs">{e.endpoint}</td><td className="td tabular">{num(e.requests)}</td>
                        <td className="td tabular">{num(e.server_errors)}</td><td className="td tabular">{na(e.avg_ms, ms)}</td><td className="td tabular">{na(e.p95_ms, ms)}</td></tr>
                    ))}
                  </tbody>
                </Table>
              </Panel>
            </Group>
          )}

          <div className="grid items-start gap-6 xl:grid-cols-2">
            <Panel title="Current model" description={cm?.metric_note}>
              {cm ? (
                <DefinitionList items={[
                  ["Version", <VersionTag key="v" version={cm.version} active />], ["Algorithm", cm.algorithm],
                  ["Why it exists", cm.trigger], ["Detector", `${cm.detector} (${cm.detector_backend})`],
                  ["Validation accuracy", pct(cm.accuracy)], ["Validation F1", pct(cm.f1_score)],
                  ["Live accuracy", cm.live_metrics ? `${pct(cm.live_metrics.accuracy)} on ${num(cm.live_metrics.n)} outcomes` : "No outcomes yet"],
                  ["Training records", num(cm.training_records)], ["Last trained", dateTime(cm.last_trained_at)],
                  ["Last adapted", cm.last_adapted_at ? dateTime(cm.last_adapted_at) : "Never (initial model)"],
                ]} />
              ) : <p className="text-sm text-muted">No model information available.</p>}
              <div className="mt-5 border-t border-seam pt-4">
                <h3 className="text-sm font-semibold text-fg">Detectors</h3>
                <DetectorList primary={m.detector.primary} status={m.detector.status} adapting={m.detector.adapting} shadows={m.detector.shadows}
                  available={meta.detectors} backend={cm?.detector_backend} />
              </div>
            </Panel>
            <Panel title="Model health"><HealthPanel health={m.model_health} /></Panel>
          </div>
        </div>
      )}
    </>
  );
}
