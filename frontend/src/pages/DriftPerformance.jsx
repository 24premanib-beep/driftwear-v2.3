import { Link } from "react-router-dom";
import { ChartNoAxesCombined } from "lucide-react";
import { Info } from "lucide-react";
import { C, DriftStoryChart, PhaseComparisonChart, SeriesLegend } from "../components/charts";
import { recoveryVerdict, StageSequence } from "../components/insights";
import { Badge, DefinitionList, Empty, ErrorNote, Loading, Notice, PageHeader, Panel, SeverityBadge, SimulationBanner, StreamSwitch, Table,
  VersionTag, tone } from "../components/ui";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Performance } from "../lib/endpoints";
import { comparisonBars, deltaInfo, focusSeries, METRICS, PHASES, phaseVersion } from "../lib/comparison";
import { dateTime, num, pct, timeAgo } from "../lib/format";
import { useApi, useQueryParam, useStreamParam } from "../lib/hooks";

const DELTA_KEY = { during: "during_vs_before", after: "after_vs_during" };
const DELTA_NOTE = { during: "vs before", after: "vs during" };
const DELTA_TONE = { stable: "text-stable-ink", drift: "text-drift-ink", neutral: "text-muted" };

function PhaseColumn({ ev, phase }) {
  const p = PHASES.find((x) => x.key === phase);
  const seg = ev[phase];
  const deltas = ev.deltas?.[DELTA_KEY[phase]];
  const t = tone(p.tone);
  return (
    <section className="p-5" aria-label={p.label}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-md font-semibold text-fg"><span className={`h-3 w-3 rounded-sm ${t.solid}`} aria-hidden="true" />{p.label}</h3>
        <VersionTag version={phaseVersion(ev, phase)} />
      </div>
      <p className="mt-1 text-xs text-muted">
        {seg.n ? `${num(seg.n)} labeled outcomes · #${seg.from_step + 1}–#${seg.to_step + 1}` : "No labeled outcomes in this phase yet"}
        {seg.from_ts ? <span className="block">{dateTime(seg.from_ts)} – {dateTime(seg.to_ts)}</span> : null}
      </p>
      <dl className="mt-4 space-y-2">
        {METRICS.map((m) => {
          const d = deltas && seg.n ? deltaInfo(deltas[m.key], m.lowerIsBetter) : null;
          return (
            <div key={m.key} className="flex items-baseline justify-between gap-3">
              <dt className="text-sm text-muted">{m.label}</dt>
              <dd className="text-right">
                <span className="figure text-lg text-fg">{seg.n ? pct(seg[m.key]) : "N/A"}</span>
                {d && d.text !== "—" && <span className={`ml-2 text-xs tabular ${DELTA_TONE[d.tone]}`}>{d.text} <span className="text-faint">{DELTA_NOTE[phase]}</span></span>}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

export default function DriftPerformance() {
  const [stream, setStream] = useStreamParam(true);
  const [selected, setSelected] = useQueryParam("event", "");
  const cmp = useApi(() => Performance.comparison(stream), [stream]);
  useLiveRefresh(() => cmp.reload({ silent: true }), stream, { delay: 2000 });
  const data = cmp.data;
  const events = data?.events || [];
  const ev = events.find((e) => e.event_key === selected) || events[events.length - 1] || null;
  const v = recoveryVerdict(ev);
  const q = stream === "simulation" ? "?stream=simulation" : "";

  return (
    <>
      <PageHeader title="Drift performance"
        lede="What concept drift did to the model and whether adaptation recovered it: before the change, while the old model failed, and after the new one took over. Labeled outcomes only; a phase without outcomes shows N/A, never an estimate."
        actions={<StreamSwitch stream={stream} onChange={(s) => { setSelected(""); setStream(s); }} />} />
      {stream === "simulation" && <SimulationBanner />}
      <ErrorNote error={cmp.error} onRetry={() => cmp.reload()} className="mb-6" />
      {cmp.loading && !data ? <Loading label="Measuring performance around each drift event…" rows={6} /> : data && (!ev ? (
        <Panel>
          <Empty title="No concept drift on this stream yet" icon={ChartNoAxesCombined}
            action={stream === "simulation" ? <Link to="/app/simulation" className="btn btn-primary">Open the simulation</Link>
              : <Link to="/app/drift-performance?stream=simulation" className="btn btn-secondary">View the simulation stream</Link>}>
            {num(data.outcomes)} labeled outcomes so far. The comparison appears after the detector confirms a drift and the model adapts.
            {stream === "simulation" ? " Stream some records, then change the fashion trend." : " Live data drifts only when real customer behaviour changes; the simulation shows it on demand."}
          </Empty>
        </Panel>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="display text-2xl text-navy">{ev.event_key}</h2>
                <SeverityBadge severity={ev.severity} />
              </div>
              <p className="mt-1 text-sm text-muted">Confirmed by {ev.detector} at outcome #{ev.step + 1}{ev.detected_at ? `, ${dateTime(ev.detected_at)} (${timeAgo(ev.detected_at)})` : ""}.
                {" "}<VersionTag version={ev.from_version} /> → {ev.to_version ? <VersionTag version={ev.to_version} /> : "no new version"}</p>
            </div>
            {events.length > 1 && (
              <label className="block text-sm"><span className="mb-1 block text-xs text-muted">Drift event</span>
                <select className="input input-sm w-auto" value={ev.event_key} onChange={(e) => setSelected(e.target.value)}>
                  {[...events].reverse().map((e) => <option key={e.event_key} value={e.event_key}>{e.event_key} · outcome #{e.step + 1}</option>)}
                </select>
              </label>
            )}
          </div>

          <Notice tone={v.tone} title={v.title}>
            {v.text} <span className="text-muted">Recovery rule: {ev.recovery_rule}.</span>
          </Notice>

          <section aria-labelledby="story-title">
            <h2 id="story-title" className="mb-3 text-md font-semibold text-fg">What happened</h2>
            <StageSequence stages={ev.story} label="Drift story" />
          </section>

          <div className="hairlines"><div className="hairlines-inner lg:grid-cols-3">
            {PHASES.map((p) => <PhaseColumn key={p.key} ev={ev} phase={p.key} />)}
          </div></div>

          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Panel title="Performance timeline" description="Rolling accuracy and error rate around this drift. Shading marks the three measured phases.">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <SeriesLegend items={[[C.ink, "Accuracy"], [C.stone, "Error rate", true]]} />
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">{PHASES.map((p) => <span key={p.key} className="inline-flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-sm opacity-40 ${tone(p.tone).solid}`} aria-hidden="true" />{p.label}</span>)}</div>
              </div>
              <DriftStoryChart series={focusSeries(data.series, ev)} event={ev} />
            </Panel>
            <Panel title="Before, during and after" description="Each bar is measured on that phase's own outcomes. Missing phases have no bar.">
              <PhaseComparisonChart rows={comparisonBars(ev)} />
            </Panel>
          </div>

          <Panel title="Drift details">
            <DefinitionList columns={3} items={[
              ["Detected", ev.detected_at ? `${dateTime(ev.detected_at)} at outcome #${ev.step + 1}` : `Outcome #${ev.step + 1}`],
              ["Detector", ev.detector],
              ["Change point (estimated)", `Outcome #${ev.change_point_step + 1}, ${num(ev.step - ev.change_point_step)} outcomes before the alarm`],
              ["First warning", ev.warning ? `Outcome #${ev.warning.step + 1}${ev.warning.timestamp ? `, ${timeAgo(ev.warning.timestamp)}` : ""}` : "None before this drift"],
              ["Trend change", ev.trend_change ? `${ev.trend_change.from_trend} → ${ev.trend_change.to_trend} at outcome #${ev.trend_change.step + 1}` : "Not labelled in the data"],
              ["Model before drift", <VersionTag key="f" version={ev.from_version} />],
              ["Model after adaptation", ev.to_version ? <VersionTag key="t" version={ev.to_version} /> : `None (${ev.action}); ${ev.from_version} kept`],
              ["Adapted model trained", ev.adaptation ? `${dateTime(ev.adaptation.created_at)} on ${num(ev.adaptation.records_used)} records (#${ev.adaptation.window_start + 1}–#${ev.adaptation.window_end + 1})` : "—",
                ev.adaptation ? `Validation accuracy ${pct(ev.adaptation.validation_accuracy)} (out-of-fold)` : null],
              ["Outcomes handled before adaptation", `${num(ev.predictions.before_adaptation)} by ${ev.from_version}`],
              ["Outcomes handled after adaptation", ev.predictions.after_range ? `${num(ev.predictions.after_adaptation)} (#${ev.predictions.after_range[0] + 1}–#${ev.predictions.after_range[1] + 1})` : "None yet"],
              ["All predictions served", Object.entries(ev.predictions.served_by_version || {}).map(([k, n]) => `${k}: ${num(n)}`).join(" · ") || "—"],
              ["Trend source", ev.trend_change?.source || "Change point estimated from the error stream"],
            ]} />
            <div className="mt-4 flex flex-wrap gap-4 border-t border-seam pt-3 text-sm">
              <Link to={`/app/models${q}${q ? "&" : "?"}version=${ev.to_version || ev.from_version}`} className="link">Open {ev.to_version || ev.from_version} in the registry</Link>
              <Link to={`/app/drift${q}`} className="link">Drift monitoring</Link>
            </div>
          </Panel>

          {events.length > 1 && (
            <Panel title="All drift events" description="Accuracy in each phase, error rate in brackets" flush
              footer={`All events pooled: before ${pct(data.pooled.before.accuracy)} · during ${pct(data.pooled.during.accuracy)} · after ${pct(data.pooled.after.accuracy)} accuracy.`}>
              <Table caption="All drift events">
                <thead><tr><th className="th">Event</th><th className="th">Detected</th><th className="th">Versions</th>
                  <th className="th">Before</th><th className="th">During</th><th className="th">After</th><th className="th">Recovery</th></tr></thead>
                <tbody>
                  {[...events].reverse().map((e) => {
                    const r = recoveryVerdict(e);
                    return (
                      <tr key={e.event_key} className={`row-link ${e.event_key === ev.event_key ? "bg-plum-50/70" : ""}`} onClick={() => setSelected(e.event_key)}>
                        <td className="td"><button type="button" className="link" onClick={() => setSelected(e.event_key)}>{e.event_key}</button></td>
                        <td className="td whitespace-nowrap text-muted">{timeAgo(e.detected_at)}</td>
                        <td className="td whitespace-nowrap"><VersionTag version={e.from_version} /> → {e.to_version ? <VersionTag version={e.to_version} /> : "kept"}</td>
                        {["before", "during", "after"].map((k) => <td key={k} className="td whitespace-nowrap tabular">{e[k].n ? `${pct(e[k].accuracy)} (${pct(e[k].error_rate)})` : "N/A"}</td>)}
                        <td className="td"><Badge tone={r.tone} icon>{r.title}</Badge></td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            </Panel>
          )}
          <p className="flex items-start gap-2 text-xs text-muted"><Info className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {data.definitions.before}. {data.definitions.during}. {data.definitions.after}. Precision, recall and F1 are macro averages over the six categories.</p>
        </div>
      ))}
    </>
  );
}
