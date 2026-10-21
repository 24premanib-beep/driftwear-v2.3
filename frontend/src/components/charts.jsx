/**
 * Charts. Recharts for time series and grouped comparisons; plain HTML bars where a label-per-row reads better.
 * Colour roles: ink = the measured series, stone = reference / baseline, state colours only for detector states and
 * drift phases (always with a text label or legend). Missing values are left as gaps, never drawn as zero.
 */
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis } from "recharts";
import { phaseRegions } from "../lib/comparison";
import { KIND_LABELS, pct, pts, statusMeta } from "../lib/format";

export const C = {
  ink: "#172036", stone: "#A39E94", grid: "#E6E2DA", axis: "#5F5C56", faint: "#7E7A73", surface: "#FBFAF8",
  stable: "#1A8F6E", warning: "#C88A12", drift: "#B8261F", adapted: "#2A4FC2", plum: "#7A3366",
  stableInk: "#146B52", warningInk: "#85590A", driftInk: "#A32019", adaptedInk: "#2443A8",
};
const AXIS = { tick: { fontSize: 12, fill: C.axis }, tickLine: false, axisLine: { stroke: "#C9C3B8" } };
const pctTick = (v) => `${Math.round(v * 100)}%`;
const FONT = { fontFamily: "Archivo, system-ui, sans-serif" };

export function ChartEmpty({ height = 240, children = "Not enough labeled outcomes yet." }) {
  return (
    <div className="flex items-center justify-center rounded-md border border-dashed border-seam-strong bg-canvas/50 px-6 text-center text-sm text-muted" style={{ height }}>
      {children}
    </div>
  );
}

function TooltipBox({ title, rows, foot }) {
  return (
    <div className="min-w-[180px] rounded-md border border-seam bg-surface px-3 py-2 text-xs shadow-pop" style={FONT}>
      {title && <div className="mb-1 font-semibold text-fg">{title}</div>}
      {rows.map(([label, value, color, dash]) => (
        <div key={label} className="flex items-center justify-between gap-4 py-px">
          <span className="inline-flex items-center gap-1.5 text-muted">
            {color && <span className="inline-block w-3 border-t-2" style={{ borderColor: color, borderStyle: dash ? "dashed" : "solid" }} />}{label}
          </span>
          <span className="font-medium tabular text-fg">{value}</span>
        </div>
      ))}
      {foot && <div className="mt-1 border-t border-seam pt-1 text-muted">{foot}</div>}
    </div>
  );
}

function StepTooltip({ active, payload, label, lines }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <TooltipBox title={`Outcome #${Number(label) + 1}`}
      rows={lines.map((l) => [l.name, row[l.key] === null || row[l.key] === undefined ? "N/A" : pct(row[l.key]), l.color, l.dash])}
      foot={row.model_version ? `Model ${row.model_version} · detector ${statusMeta(row.status).label}` : null} />
  );
}

/**
 * Keep a label only when it is far enough (a share of the x-span) from the previous labeled marker, so clustered
 * markers stay readable. Every line is still drawn; the drift table lists them all.
 */
function spaced(items, span, share) {
  let last = -Infinity;
  return [...items].sort((a, b) => a.step - b.step).map((it) => {
    const show = !span || it.step - last >= span * share;
    if (show) last = it.step;
    return [it, show];
  });
}

/** Warning, drift and adaptation markers (vertical lines) with short labels. */
function markerLines(markers, { warnings = true, adaptations = true, span = 0 } = {}) {
  if (!markers) return [];
  const out = [];
  if (warnings) {
    (markers.warnings || []).forEach((w, i) => out.push(
      <ReferenceLine key={`w${w.step}-${i}`} x={w.step} stroke={C.warning} strokeDasharray="2 3" strokeWidth={1.5} ifOverflow="extendDomain" />));
  }
  spaced(markers.drifts || [], span, 0.12).forEach(([d, show]) => out.push(
    <ReferenceLine key={`d${d.step}`} x={d.step} stroke={C.drift} strokeWidth={2} ifOverflow="extendDomain"
      label={show ? { value: `Drift${d.to_version ? ` → ${d.to_version}` : ", model kept"}`, position: "insideTopLeft", fill: C.driftInk, fontSize: 11, fontWeight: 600, ...FONT } : undefined} />));
  if (adaptations) {
    spaced((markers.adaptations || []).filter((a) => a.kind !== "drift"), span, 0.06).forEach(([a, show]) => out.push(
      <ReferenceLine key={`a${a.step}-${a.version}`} x={a.step} stroke={C.adapted} strokeDasharray="4 3" ifOverflow="extendDomain"
        label={show ? { value: a.version, position: "insideBottomRight", fill: C.adaptedInk, fontSize: 10.5, ...FONT } : undefined} />));
  }
  return out;
}

export function MarkerLegend({ warnings = true, refreshes = true }) {
  const item = (color, label, style) => (
    <span className="inline-flex items-center gap-1.5">
      <svg width="16" height="10" aria-hidden="true"><line x1="0" y1="5" x2="16" y2="5" stroke={color} strokeWidth="2" strokeDasharray={style} /></svg>{label}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {warnings && item(C.warning, "Warning", "2 3")}{item(C.drift, "Drift confirmed")}{refreshes && item(C.adapted, "Refresh or retrain", "4 3")}
    </div>
  );
}

/**
 * Rolling accuracy or error rate over labeled outcomes, with the drift markers. For accuracy the frozen v1.0
 * baseline is drawn in stone so the value of adaptation is visible.
 */
export function TimelineChart({ series, markers, metric = "accuracy", height = 300, showBaseline = true }) {
  if (!series?.length) return <ChartEmpty height={height}>No labeled outcomes on this stream yet. The chart starts with the first actual category.</ChartEmpty>;
  const lines = metric === "error_rate"
    ? [{ key: "error_rate", name: "Error rate (rolling 50)", color: C.ink }]
    : [{ key: "accuracy", name: "Active model (rolling 50)", color: C.ink },
      ...(showBaseline ? [{ key: "baseline_accuracy", name: "Frozen v1.0 on the same records", color: C.stone, dash: true }] : [])];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series} margin={{ top: 18, right: 12, bottom: 18, left: 0 }} style={FONT}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="step" type="number" domain={["dataMin", "dataMax"]} {...AXIS} tickFormatter={(v) => v + 1}
          label={{ value: "Labeled outcomes in arrival order", position: "insideBottom", offset: -10, fill: C.faint, fontSize: 11 }} />
        <YAxis domain={[0, 1]} tickFormatter={pctTick} {...AXIS} width={44} />
        <Tooltip content={<StepTooltip lines={lines} />} cursor={{ stroke: C.stone, strokeDasharray: "3 3" }} />
        {markerLines(markers, { warnings: metric === "error_rate", span: series[series.length - 1].step - series[0].step })}
        {lines.map((l) => (
          <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={l.dash ? 1.5 : 2}
            strokeDasharray={l.dash ? "5 4" : undefined} dot={false} isAnimationActive={false} connectNulls={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function SeriesLegend({ items }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {items.map(([color, label, dash]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <svg width="16" height="10" aria-hidden="true"><line x1="0" y1="5" x2="16" y2="5" stroke={color} strokeWidth="2" strokeDasharray={dash ? "4 3" : undefined} /></svg>{label}
        </span>
      ))}
    </div>
  );
}

/** One drift on one chart: rolling accuracy and error rate, the three phases shaded, and the key moments marked. */
export function DriftStoryChart({ series, event, height = 340 }) {
  if (!series?.length || !event) return <ChartEmpty height={height} />;
  const fill = { before: C.stable, during: C.drift, after: C.adapted };
  const marks = [
    event.trend_change ? { x: event.trend_change.step, color: C.ink, label: "Trend changed", dash: "4 3", pos: "insideTopRight" }
      : { x: event.change_point_step, color: C.ink, label: "Change point (estimated)", dash: "4 3", pos: "insideTopRight" },
    event.warning ? { x: event.warning.step, color: C.warning, label: "Warning", dash: "2 3", pos: "insideBottomLeft" } : null,
    { x: event.step, color: C.drift, label: `Drift confirmed${event.to_version ? ` → ${event.to_version}` : ""}`, width: 2, pos: "insideTopLeft" },
  ].filter(Boolean);
  const lines = [{ key: "accuracy", name: "Accuracy (rolling 50)", color: C.ink }, { key: "error_rate", name: "Error rate (rolling 50)", color: C.stone, dash: true }];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series} margin={{ top: 24, right: 12, bottom: 18, left: 0 }} style={FONT}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="step" type="number" domain={["dataMin", "dataMax"]} {...AXIS} tickFormatter={(v) => v + 1}
          label={{ value: "Labeled outcomes in arrival order", position: "insideBottom", offset: -10, fill: C.faint, fontSize: 11 }} />
        <YAxis domain={[0, 1]} tickFormatter={pctTick} {...AXIS} width={44} />
        <Tooltip content={<StepTooltip lines={lines} />} cursor={{ stroke: C.stone, strokeDasharray: "3 3" }} />
        {phaseRegions(event).map((r) => (
          <ReferenceArea key={r.phase} x1={r.from} x2={r.to} fill={fill[r.phase]} fillOpacity={0.08} ifOverflow="extendDomain" />
        ))}
        {marks.map((m) => (
          <ReferenceLine key={`${m.label}-${m.x}`} x={m.x} stroke={m.color} strokeDasharray={m.dash} strokeWidth={m.width || 1.5} ifOverflow="extendDomain"
            label={{ value: m.label, position: m.pos, fill: m.color === C.warning ? C.warningInk : m.color === C.drift ? C.driftInk : m.color, fontSize: 11, fontWeight: 600, ...FONT }} />
        ))}
        {lines.map((l) => (
          <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={l.dash ? 1.75 : 2}
            strokeDasharray={l.dash ? "5 3" : undefined} dot={false} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function BarTooltip({ active, payload, label, fmt = pct, noun }) {
  if (!active || !payload?.length) return null;
  return <TooltipBox title={label} rows={payload.map((p) => [p.name, p.value === null || p.value === undefined ? "N/A" : fmt(p.value), p.color])}
    foot={noun ? noun(payload[0].payload) : null} />;
}

/** Before / during / after drift, one group per metric. A phase without outcomes has no bar (not a zero bar). */
export function PhaseComparisonChart({ rows, height = 300 }) {
  if (!rows?.length || rows.every((r) => r.before === null && r.during === null && r.after === null)) {
    return <ChartEmpty height={height}>No drift event to compare yet.</ChartEmpty>;
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }} barCategoryGap="22%" barGap={2} style={FONT}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="metric" {...AXIS} interval={0} />
        <YAxis domain={[0, 1]} tickFormatter={pctTick} {...AXIS} width={44} />
        <Tooltip content={<BarTooltip />} cursor={{ fill: "rgba(23,32,54,.04)" }} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.axis }} iconType="square" iconSize={10} />
        <Bar dataKey="before" name="Before drift" fill={C.stable} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="during" name="During drift" fill={C.drift} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="after" name="After adaptation" fill={C.adapted} radius={[3, 3, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Two series side by side per category (reference vs current, actual vs predicted, adaptive vs static…). */
export function PairedBars({ rows, x, a, b, height = 240, fmt = pct, domain, angle = false }) {
  if (!rows?.length) return <ChartEmpty height={height}>Nothing to compare yet.</ChartEmpty>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 8, bottom: angle ? 28 : 4, left: 0 }} barGap={2} barCategoryGap="24%" style={FONT}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey={x} {...AXIS} interval={0} angle={angle ? -28 : 0} textAnchor={angle ? "end" : "middle"} height={angle ? 52 : 30} />
        <YAxis tickFormatter={fmt === pct ? pctTick : undefined} domain={domain} allowDecimals={fmt !== pct ? false : undefined} {...AXIS} width={44} />
        <Tooltip content={<BarTooltip fmt={fmt} />} cursor={{ fill: "rgba(23,32,54,.04)" }} />
        {b && <Legend wrapperStyle={{ fontSize: 12, color: C.axis }} iconType="square" iconSize={10} />}
        <Bar dataKey={a.key} name={a.name} fill={a.color || C.stone} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        {b && <Bar dataKey={b.key} name={b.name} fill={b.color || C.ink} radius={[3, 3, 0, 0]} isAnimationActive={false} />}
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ HTML bar lists */

/** Class probabilities for one prediction (backend: predict_proba of the active Random Forest). */
export function ProbabilityBars({ probabilities, predicted, categories }) {
  const rows = (categories || Object.keys(probabilities || {})).map((c) => ({ c, p: probabilities?.[c] ?? null }))
    .sort((x, y) => (y.p ?? -1) - (x.p ?? -1));
  return (
    <ul className="space-y-1.5" aria-label="Probability for each category">
      {rows.map(({ c, p }) => (
        <li key={c} className="grid grid-cols-[96px_1fr_48px] items-center gap-3 text-sm">
          <span className={c === predicted ? "font-semibold text-navy" : "text-muted"}>{c}</span>
          <span className="h-2 overflow-hidden rounded-sm bg-canvas" aria-hidden="true">
            <span className={`block h-full rounded-sm ${c === predicted ? "bg-navy" : "bg-stone/70"}`} style={{ width: `${Math.round((p || 0) * 100)}%` }} />
          </span>
          <span className={`text-right tabular ${c === predicted ? "font-semibold text-navy" : "text-muted"}`}>{p === null ? "N/A" : pct(p, 0)}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Decision-path contributions (ml/explain.py), as diverging bars around zero: right pushes the predicted
 * category's probability up, left pushes it down. Values are percentage points of probability.
 */
export function ContributionBars({ contributions, limit = 8 }) {
  const items = (contributions || []).slice(0, limit);
  if (!items.length) return null;
  const max = Math.max(...items.map((c) => Math.abs(c.contribution)), 0.0001);
  return (
    <ul className="space-y-1.5" aria-label="Contribution of each input">
      {items.map((c) => {
        const w = `${(Math.abs(c.contribution) / max) * 100}%`;
        const up = c.contribution >= 0;
        return (
          <li key={c.feature} className="grid grid-cols-[minmax(110px,170px)_1fr_64px] items-center gap-3 text-sm">
            <span className="min-w-0 truncate" title={`${c.label}: ${c.value}`}>
              <span className="text-fg">{c.label}</span> <span className="text-muted">{String(c.value)}</span>
            </span>
            <span className="grid grid-cols-2" aria-hidden="true">
              <span className="flex justify-end border-r border-seam-strong py-0.5">{!up && <span className="block h-2.5 rounded-l-sm bg-stone" style={{ width: w }} />}</span>
              <span className="flex py-0.5">{up && <span className="block h-2.5 rounded-r-sm bg-navy" style={{ width: w }} />}</span>
            </span>
            <span className={`text-right text-xs tabular ${up ? "font-medium text-navy" : "text-muted"}`}>{pts(c.contribution)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Feature importance as labelled bars (mean decrease in impurity from the Random Forest). */
export function ImportanceBars({ items, color = "bg-navy", limit = 10 }) {
  const rows = (items || []).slice(0, limit);
  if (!rows.length) return <ChartEmpty height={120}>No model loaded.</ChartEmpty>;
  const max = Math.max(...rows.map((r) => r.importance), 0.0001);
  return (
    <ul className="space-y-1.5">
      {rows.map((f) => (
        <li key={f.feature} className="grid grid-cols-[minmax(120px,180px)_1fr_48px] items-center gap-3 text-sm">
          <span className="truncate text-fg" title={f.label || f.feature}>{f.label || f.feature}</span>
          <span className="h-2 rounded-sm bg-canvas" aria-hidden="true"><span className={`block h-full rounded-sm ${color}`} style={{ width: `${(f.importance / max) * 100}%` }} /></span>
          <span className="text-right text-xs tabular text-muted">{pct(f.importance, 1)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Which model version served which part of the stream. */
export function VersionStrip({ versions, totalSteps, onSelect, selected }) {
  const ordered = [...(versions || [])].sort((a, b) => a.created_step - b.created_step);
  const end = Math.max(totalSteps || 0, ...ordered.map((v) => v.created_step + 1), 1);
  if (!ordered.length) return <ChartEmpty height={64}>No model versions yet.</ChartEmpty>;
  const fill = { initial: "bg-navy-600", drift: "bg-drift", refresh: "bg-adapted", manual: "bg-plum" };
  return (
    <div>
      <div className="flex h-9 w-full overflow-hidden rounded-md" role="list" aria-label="Model versions along the stream">
        {ordered.map((v, i) => {
          const start = Math.max(0, v.created_step + 1);
          const stop = i + 1 < ordered.length ? Math.max(0, ordered[i + 1].created_step + 1) : end;
          const width = Math.max(((stop - start) / end) * 100, 1.2);
          const label = `${v.version}: ${KIND_LABELS[v.kind] || v.kind}, outcomes ${start + 1}–${stop}${v.is_active ? " (active)" : ""}`;
          const Tag = onSelect ? "button" : "div";
          return (
            <Tag key={v.version} role="listitem" title={label} aria-label={label} style={{ width: `${width}%` }} type={onSelect ? "button" : undefined}
              onClick={onSelect ? () => onSelect(v.version) : undefined}
              className={`flex items-center justify-center border-r-2 border-surface text-[11px] font-semibold text-white last:border-r-0 ${fill[v.kind] || "bg-faint"} ${v.is_active ? "underline decoration-2 underline-offset-2" : ""} ${selected === v.version ? "ring-2 ring-inset ring-plum-300" : ""} ${onSelect ? "hover:opacity-90" : ""}`}>
              {width > 5 ? v.version : ""}
            </Tag>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {[["bg-navy-600", "Initial"], ["bg-drift", "After drift"], ["bg-adapted", "Scheduled refresh"], ["bg-plum", "Manual retrain"]].map(([c, l]) => (
          <span key={l} className="inline-flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-sm ${c}`} aria-hidden="true" />{l}</span>
        ))}
        <span>Underlined: active now</span>
      </div>
    </div>
  );
}

/** Confusion matrix (rows = actual, columns = predicted). Diagonal = correct, in ink; errors in drift red. */
export function ConfusionMatrix({ labels, matrix }) {
  const max = Math.max(1, ...(matrix || []).flat());
  if (!matrix?.length || matrix.flat().every((v) => !v)) return <ChartEmpty height={200} />;
  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <caption className="sr-only">Confusion matrix: rows are the actual category, columns the predicted category</caption>
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-xs font-normal text-muted">Actual ↓ Predicted →</th>
            {labels.map((l) => <th key={l} scope="col" className="px-1 py-1 text-xs font-medium text-muted">{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <th scope="row" className="whitespace-nowrap px-2 py-1 text-left text-xs font-medium text-muted">{labels[i]}</th>
              {row.map((v, j) => {
                const a = v / max;
                const diag = i === j;
                return (
                  <td key={labels[j]} className="p-0.5">
                    <div className="flex h-10 min-w-[58px] items-center justify-center rounded-sm text-xs font-medium tabular"
                      title={`${labels[i]} predicted as ${labels[j]}: ${v}`}
                      style={{ background: v ? (diag ? `rgba(23,32,54,${0.1 + a * 0.8})` : `rgba(184,38,31,${0.08 + a * 0.6})`) : "#F4F2EE",
                        color: a > 0.5 ? "#fff" : C.ink }}>
                      {v || ""}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** PSI per feature on a ruler with the 0.10 / 0.25 thresholds marked. PSI is open-ended, so long bars are capped. */
export function PsiRuler({ value, warning = 0.1, drift = 0.25, cap = 0.5 }) {
  const w = Math.min(value / cap, 1) * 100;
  const color = value >= drift ? "bg-drift" : value >= warning ? "bg-warning" : "bg-stable";
  return (
    <div className="relative h-2 w-full min-w-[120px] rounded-sm bg-canvas" aria-hidden="true">
      <div className={`h-full rounded-sm ${color}`} style={{ width: `${w}%` }} />
      <div className="absolute inset-y-[-3px] w-px bg-fg/40" style={{ left: `${(warning / cap) * 100}%` }} />
      <div className="absolute inset-y-[-3px] w-px bg-fg/70" style={{ left: `${(drift / cap) * 100}%` }} />
      {value > cap && <span className="absolute -right-1 -top-[3px] text-[10px] leading-none text-drift-ink">›</span>}
    </div>
  );
}

/** Share of scored outcomes by detector state, as one stacked bar with labels. */
export function StateShareBar({ counts }) {
  const keys = ["STABLE", "WARNING", "DRIFT"];
  const total = keys.reduce((s, k) => s + (counts?.[k] || 0), 0);
  if (!total) return <ChartEmpty height={64}>No scored outcomes yet.</ChartEmpty>;
  const fill = { STABLE: "bg-stable", WARNING: "bg-warning", DRIFT: "bg-drift" };
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-sm" aria-hidden="true">
        {keys.map((k) => counts?.[k] ? <div key={k} className={`${fill[k]} border-r-2 border-surface last:border-r-0`} style={{ width: `${(counts[k] / total) * 100}%` }} /> : null)}
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
        {keys.map((k) => (
          <div key={k}>
            <dt className="text-xs text-muted">{statusMeta(k).label}</dt>
            <dd className="font-medium tabular text-fg">{(counts?.[k] || 0).toLocaleString()} <span className="text-xs font-normal text-muted">({(counts?.[k] || 0) && (counts[k] / total) < 0.01 ? "<1%" : pct((counts?.[k] || 0) / total, 0)})</span></dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
