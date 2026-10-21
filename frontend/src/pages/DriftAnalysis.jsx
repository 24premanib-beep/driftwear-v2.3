import { useState } from "react";
import { Link } from "react-router-dom";
import { MarkerLegend, PairedBars, PsiRuler, SeriesLegend, TimelineChart, C } from "../components/charts";
import { DetectorList, DriftLink } from "../components/insights";
import { Badge, Empty, ErrorNote, Loading, Notice, PageHeader, Panel, SeverityBadge, SimulationBanner, StateBadge, StreamSwitch, Table,
  ToneIcon, VersionTag, tone } from "../components/ui";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Drift } from "../lib/endpoints";
import { dataDriftMeta, num, pct, timeAgo } from "../lib/format";
import { useApi, useStreamParam } from "../lib/hooks";

const READINGS = [
  { data: false, concept: false, text: "Business as usual. Customers look the same and the model still predicts them well.", action: "Nothing to do." },
  { data: true, concept: false, text: "Customers look different (for example, more festive-season purchases) but the model still predicts them well.", action: "Watch. Do not retrain on input shifts alone." },
  { data: false, concept: true, text: "Customers look the same but now buy different things. Only the error stream can see this case.", action: "DriftWear adapts on the post-change window." },
  { data: true, concept: true, text: "Both changed. The error stream decides.", action: "DriftWear adapts on the post-change window." },
];

function DataDriftBadge({ status }) {
  const m = dataDriftMeta(status);
  const t = tone(m.tone);
  return <span className={`chip ${t.soft} ${t.border} ${t.text}`}><ToneIcon tone={m.tone} className="h-3.5 w-3.5" />{m.label}</span>;
}

function Formula({ kind, symbol, title, sentence, rows, emphasis }) {
  return (
    <div className={`rounded-lg border bg-surface p-5 ${emphasis ? "border-navy/40" : "border-seam"}`}>
      <p className="text-sm text-muted">{kind}</p>
      <p className="display mt-1 text-2xl text-navy">{title}</p>
      <p className="mt-1 font-mono text-md text-fg" aria-label={symbol.label}>{symbol.text}</p>
      <p className="mt-2 text-sm text-fg">{sentence}</p>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-t border-seam pt-3 text-sm">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="text-fg">{v}</dd></div>)}
      </dl>
    </div>
  );
}

export default function DriftAnalysis() {
  const [stream, setStream] = useStreamParam(true);
  const [windowSize, setWindowSize] = useState(200);
  const [reference, setReference] = useState("baseline");
  const [selected, setSelected] = useState(null);
  const data = useApi(() => Drift.data(stream, windowSize, reference), [stream, windowSize, reference]);
  const stats = useApi(() => Drift.statistics(stream), [stream]);
  useLiveRefresh(() => { data.reload({ silent: true }); stats.reload({ silent: true }); }, stream, { delay: 2500 });

  const d = data.data;
  const s = stats.data;
  const feature = d?.features?.find((f) => f.feature === selected) || d?.features?.[0];
  const drifts = [...(s?.impact || [])].reverse();
  const dataShift = d && d.status !== "INSUFFICIENT_DATA" ? ["WARNING", "DRIFT"].includes(d.status) : null;
  const conceptNow = s ? s.status.status === "DRIFT" || s.status.adapting : null;
  const current = dataShift === null || conceptNow === null ? null : READINGS.find((r) => r.data === dataShift && r.concept === conceptNow);

  return (
    <>
      <PageHeader title="Data drift vs concept drift"
        lede="Two different questions about change. Data drift asks whether the inputs look different; concept drift asks whether the same inputs now lead to different purchases. DriftWear retrains only on the second."
        actions={<StreamSwitch stream={stream} onChange={(v) => { setSelected(null); setStream(v); }} />} />
      {stream === "simulation" && <SimulationBanner />}

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Formula kind="Diagnostic only" title="Data drift" symbol={{ text: "P(X) changes", label: "P of X changes" }}
          sentence="The input data changed: the mix of prices, seasons, preferences or previous categories is different from the reference."
          rows={[["Measured by", "PSI per feature, plus a KS test for numbers, against a reference window"], ["Needs actual outcomes", "No"],
            ["Triggers retraining", <strong key="n" className="font-semibold">No. Inputs can shift while predictions stay correct.</strong>]]} />
        <Formula kind="Drives adaptation" title="Concept drift" emphasis symbol={{ text: "P(y | X) changes", label: "P of y given X changes" }}
          sentence="The relationship between the input and the target changed: customers who look the same now buy a different category."
          rows={[["Measured by", "DDM, ADWIN or Page-Hinkley on the prediction-error stream"], ["Needs actual outcomes", "Yes, every error needs the real category"],
            ["Triggers retraining", <strong key="y" className="font-semibold">Yes, when the primary detector confirms drift.</strong>]]} />
      </div>

      {current && (
        <Notice tone={conceptNow ? "drift" : dataShift ? "warning" : "stable"} className="mb-6"
          title={`Right now: inputs ${dataShift ? "have shifted" : "are stable"}, and the error stream ${conceptNow ? "shows concept drift" : s.status.status === "WARNING" ? "is in its warning zone" : "is stable"}.`}>
          {current.text} {current.action}
        </Notice>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-2">
        <Panel title="Did the inputs change?" description={d ? `${d.reference.label} (${num(d.reference.n)} records) against ${d.current.label?.toLowerCase() || "recent inputs"} (${num(d.current.n)})` : "Input distributions, reference against recent inputs"}
          actions={d && d.status !== "INSUFFICIENT_DATA" && <DataDriftBadge status={d.status} />}>
          <div className="mb-5 flex flex-wrap items-end gap-3 text-sm">
            <label className="block"><span className="mb-1 block text-xs text-muted">Recent inputs</span>
              <select className="input input-sm w-auto" value={windowSize} onChange={(e) => setWindowSize(Number(e.target.value))}>
                {[100, 200, 500, 1000].map((n) => <option key={n} value={n}>Last {n}</option>)}
              </select>
            </label>
            <label className="block"><span className="mb-1 block text-xs text-muted">Compared with</span>
              <select className="input input-sm w-auto" value={reference} onChange={(e) => setReference(e.target.value)}>
                <option value="baseline">Data v1.0 was trained on</option>
                <option value="active">The active model's training window</option>
              </select>
            </label>
          </div>
          <ErrorNote error={data.error} onRetry={() => data.reload()} className="mb-4" />
          {data.loading && !d ? <Loading label="Comparing feature distributions…" rows={5} /> : d && (
            d.status === "INSUFFICIENT_DATA" ? <Empty title="Not enough inputs to compare yet">{d.message}</Empty> : (
              <div className="space-y-5">
                <p className="text-sm text-fg">{d.message} <span className="text-muted">Mean PSI {d.drift_score?.toFixed(2)}, highest {d.max_psi?.toFixed(2)}; {d.affected_features.length} of {d.features.length} features shifted.</span></p>
                <Table caption="Population stability per feature">
                  <thead><tr><th className="th">Feature</th><th className="th w-[42%]">PSI</th><th className="th">Biggest change</th></tr></thead>
                  <tbody>
                    {d.features.map((f) => {
                      const on = feature?.feature === f.feature;
                      const m = dataDriftMeta(f.status);
                      return (
                        <tr key={f.feature} onClick={() => setSelected(f.feature)} tabIndex={0} aria-selected={on}
                          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelected(f.feature))}
                          className={`row-link ${on ? "bg-plum-50/70" : ""}`}>
                          <td className="td"><span className="font-medium">{f.label}</span>{f.calendar && <span className="block text-xs text-muted">Moves with the calendar</span>}</td>
                          <td className="td">
                            <div className="flex items-center gap-2">
                              <ToneIcon tone={m.tone} className="h-3.5 w-3.5" />
                              <span className="w-11 shrink-0 tabular">{f.psi.toFixed(2)}</span>
                              <PsiRuler value={f.psi} warning={d.thresholds.warning} drift={d.thresholds.drift} />
                            </div>
                            <span className={`mt-0.5 block pl-[22px] text-xs ${tone(m.tone).text}`}>{m.label}</span>
                          </td>
                          <td className="td text-muted">{f.kind === "numeric" ? `Mean ${num(Math.round(f.reference_mean * 10) / 10)} → ${num(Math.round(f.current_mean * 10) / 10)}`
                            : `${f.top_shift.bucket}: ${pct(f.top_shift.reference, 0)} → ${pct(f.top_shift.current, 0)}`}
                            {f.ks_pvalue !== null && f.ks_pvalue !== undefined && <span className="block text-xs">KS p {f.ks_pvalue < 0.001 ? "< 0.001" : `= ${f.ks_pvalue.toFixed(3)}`}</span>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
                <p className="text-xs text-muted">PSI below {d.thresholds.warning} is stable, {d.thresholds.warning}–{d.thresholds.drift} a moderate shift, above {d.thresholds.drift} a significant shift (the two ticks on each bar).
                  Bars are capped at 0.5. Month and season move with the calendar by design, so their shifts are expected. {d.method}</p>
                {feature && (
                  <section aria-labelledby="dist-title">
                    <h3 id="dist-title" className="mb-1 text-sm font-semibold text-fg">{feature.label}: share of records per {feature.kind === "numeric" ? "range" : "value"}</h3>
                    <PairedBars rows={feature.distribution} x="bucket" a={{ key: "reference", name: "Reference", color: C.stone }} b={{ key: "current", name: "Recent inputs", color: C.ink }}
                      angle={feature.distribution.length > 6} height={240} />
                  </section>
                )}
              </div>
            )
          )}
        </Panel>

        <Panel title="Did the input → category relationship change?" description="Read from the prediction-error stream. This is what triggers model adaptation."
          actions={s && <StateBadge status={s.status.status} adapting={s.status.adapting} />}>
          <ErrorNote error={stats.error} onRetry={() => stats.reload()} className="mb-4" />
          {stats.loading && !s ? <Loading label="Loading the error stream…" rows={5} /> : s && (
            <div className="space-y-6">
              <div>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><SeriesLegend items={[[C.ink, "Rolling error rate"]]} /><MarkerLegend refreshes={false} /></div>
                <TimelineChart series={s.series} markers={s.markers} metric="error_rate" height={230} />
              </div>
              <section>
                <h3 className="text-sm font-semibold text-fg">Detectors</h3>
                <DetectorList primary={s.detectors.primary} status={s.status.status} adapting={s.status.adapting} shadows={s.detectors.shadow_status}
                  available={s.detectors.available} backend={s.detectors.backend} />
              </section>
              <section>
                <h3 className="mb-1 text-sm font-semibold text-fg">Confirmed concept drift</h3>
                {drifts.length ? (
                  <ul className="divide-y divide-seam">
                    {drifts.slice(0, 6).map((e) => (
                      <li key={e.event_key} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                        <span className="flex flex-wrap items-center gap-2">
                          <ToneIcon tone="drift" className="h-4 w-4" />
                          <DriftLink eventKey={e.event_key} stream={stream}>{e.event_key}</DriftLink>
                          <span className="text-muted">{e.detector} at outcome #{e.step + 1}, {timeAgo(e.detected_at)}</span>
                          <SeverityBadge severity={e.severity} />
                        </span>
                        <span className="flex items-center gap-1.5 text-xs text-muted">
                          <VersionTag version={e.from_version} /> → {e.to_version ? <VersionTag version={e.to_version} /> : "kept"}
                          <span className="ml-1 tabular">accuracy {pct(e.before.accuracy, 0)} → {pct(e.during.accuracy, 0)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-muted">No concept drift confirmed on this stream. The detector has read {num(s.summary.records_monitored)} labeled outcomes.</p>}
              </section>
              <Link to={`/app/drift${stream === "simulation" ? "?stream=simulation" : ""}`} className="link text-sm">Open drift monitoring</Link>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Reading the two together" className="mt-6" flush>
        <Table caption="How to read data drift and concept drift together">
          <thead><tr><th className="th">Inputs shifted (data drift)</th><th className="th">Errors rose (concept drift)</th><th className="th">What it means</th><th className="th">What DriftWear does</th></tr></thead>
          <tbody>
            {READINGS.map((r) => {
              const now = current === r;
              return (
                <tr key={`${r.data}${r.concept}`} className={now ? "bg-plum-50/70" : ""} aria-current={now ? "true" : undefined}>
                  <td className="td">{r.data ? "Yes" : "No"}</td>
                  <td className="td">{r.concept ? "Yes" : "No"}</td>
                  <td className="td text-muted">{r.text}{now && <Badge tone="plum" className="ml-2">Now</Badge>}</td>
                  <td className="td">{r.action}</td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Panel>
    </>
  );
}
