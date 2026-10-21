/**
 * Domain building blocks shared across pages: model health, detectors, the drift cycle, explanations, event
 * pipeline traces and activity feeds. Every value comes from the API; nothing is estimated in the browser.
 */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { CircleCheck, CircleDashed, CircleX, Clock, MinusCircle } from "lucide-react";
import { ContributionBars } from "./charts";
import { Badge, HealthBadge, StateBadge, ToneIcon, VersionTag, tone } from "./ui";
import { componentMeta, EVENT_LABELS, eventTone, healthMeta, num, pct, pts, timeAgo } from "../lib/format";

/* ------------------------------------------------------------------ model health */
/**
 * The backend's health score (app/services/model_health.py) with its five weighted parts. Bar length shows each
 * part's weight (40 / 20 / 20 / 10 / 10 points); the filled share is what the model earned.
 */
export function HealthPanel({ health, showText = true }) {
  if (!health || health.score === null || health.score === undefined) {
    return <p className="text-sm text-muted">Model health is not available yet: the model has no validation or live results.</p>;
  }
  const m = healthMeta(health.band);
  const x = health.metrics || {};
  const forced = (x.drift_status === "DRIFT" || x.adaptation === "running") && health.band === "DEGRADED";
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-baseline gap-2">
            <span className={`figure text-3xl ${tone(m.tone).text}`}>{Math.round(health.score)}</span>
            <span className="text-sm text-muted">/ 100</span>
          </div>
          <div className="mt-1"><HealthBadge band={health.band} /></div>
        </div>
        <p className="text-xs text-muted">Healthy ≥ 80 · At risk 60–79 · Degraded &lt; 60</p>
      </div>
      {showText && health.text && <p className="mt-3 text-sm text-fg">{health.text}</p>}
      {forced && <p className="mt-2 text-sm text-drift-ink">Confirmed drift or a running adaptation always reports Degraded, whatever the points add up to.</p>}
      <ul className="mt-4 space-y-2.5" aria-label="How the score is built">
        {(health.components || []).map((c) => (
          <li key={c.name}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="text-fg">{c.name}</span>
              <span className="tabular text-muted"><span className="font-medium text-fg">{Number(c.points).toFixed(c.points % 1 ? 1 : 0)}</span> / {c.max_points}</span>
            </div>
            <div className="mt-1 h-1.5 rounded-sm bg-canvas" style={{ width: `${(c.max_points / 40) * 100}%` }} aria-hidden="true">
              <div className="h-full rounded-sm bg-navy" style={{ width: `${(c.points / c.max_points) * 100}%` }} />
            </div>
            {c.note && <p className="mt-0.5 text-xs text-muted">{c.note}</p>}
          </li>
        ))}
      </ul>
      {health.basis === "validation" && (
        <p className="mt-4 rounded-md bg-warning-soft/70 px-3 py-2 text-xs text-fg">
          Based on validation, not live results: {x.model_version} has fewer than 10 live outcomes ({num(x.outcomes_measured ?? 0)} so far),
          so accuracy and F1 are its out-of-fold scores on the training window.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ detectors */
const DETECTORS = [["DDM", "Drift Detection Method"], ["ADWIN", "Adaptive windowing"], ["PageHinkley", "Page-Hinkley test"]];

/**
 * Primary detector (triggers adaptation) and shadow detectors (comparison only). A detector the server cannot run
 * (ADWIN and Page-Hinkley need River) is listed as unavailable, never as working.
 */
export function DetectorList({ primary, status, adapting, shadows = {}, available = [], backend }) {
  return (
    <ul className="divide-y divide-seam">
      {DETECTORS.map(([name, full]) => {
        const isPrimary = primary === name;
        const shadow = shadows?.[name];
        const usable = available.includes(name);
        return (
          <li key={name} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2.5">
            <div className="min-w-0">
              <div className="text-sm font-medium text-fg">{name === "PageHinkley" ? "Page-Hinkley" : name}
                {isPrimary && <Badge tone="navy" className="ml-2">Primary</Badge>}
                {!isPrimary && shadow && <Badge className="ml-2">Shadow</Badge>}
              </div>
              <div className="text-xs text-muted">{full}{isPrimary ? " · decides when to adapt" : shadow ? " · comparison only" : ""}{isPrimary && backend ? ` · ${backend}` : ""}</div>
            </div>
            {isPrimary ? <StateBadge status={status} adapting={adapting} size="sm" />
              : shadow ? <StateBadge status={shadow} size="sm" />
                : <span className="text-xs text-muted">{usable ? "Available, not running" : "Unavailable: River is not installed on the server"}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------------ cycle / story */
const STAGE_ICON = {
  done: [CircleCheck, "text-stable-ink"],
  pending: [Clock, "text-warning-ink"],
  failed: [CircleX, "text-drift-ink"],
  skipped: [MinusCircle, "text-faint"],
  none: [CircleDashed, "text-faint"],
};
const STAGE_WORD = { done: "Done", pending: "Waiting", failed: "Failed", skipped: "Skipped", none: "Not yet" };

export function StageIcon({ status, className = "h-[18px] w-[18px]" }) {
  const [Icon, color] = STAGE_ICON[status] || STAGE_ICON.none;
  return <Icon className={`${className} shrink-0 ${color}`} aria-hidden="true" />;
}

/**
 * A sequence of stages from the backend (dashboard `cycle`, drift `story`): Normal → Trend change → Errors rise →
 * Drift → Adaptation → Recovery. Stages are drawn as a connected sequence; unfinished ones are dashed.
 */
export function StageSequence({ stages, label }) {
  if (!stages?.length) return null;
  return (
    <div className="hairlines"><ol className="hairlines-inner sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label={label}>
      {stages.map((s, i) => (
        <li key={s.key} className={`relative px-4 py-3 ${s.status === "done" ? "" : "bg-canvas/70"}`}>
          <div className="flex items-center gap-2">
            <span className="tabular text-xs text-faint">{i + 1}</span>
            <StageIcon status={s.status} className="h-4 w-4" />
            <span className="text-sm font-semibold text-fg">{s.label}</span>
          </div>
          <p className="mt-1 text-xs leading-snug text-muted">{s.detail}</p>
          <p className="mt-1 text-xs text-faint">
            <span className="sr-only">Status: {STAGE_WORD[s.status] || s.status}. </span>
            {s.step !== null && s.step !== undefined ? `Outcome #${s.step + 1}` : STAGE_WORD[s.status] || ""}
            {s.timestamp ? ` · ${timeAgo(s.timestamp)}` : ""}
          </p>
        </li>
      ))}
    </ol></div>
  );
}

/* ------------------------------------------------------------------ recovery */
/**
 * Plain-language verdict for one drift event, from the backend's own `recovered` flag and deltas. When the rule says
 * "recovered" but accuracy is still below the pre-drift level, that is said too.
 */
export function recoveryVerdict(ev) {
  if (!ev) return null;
  if (!ev.to_version) return { tone: "drift", title: "Adaptation failed", text: `Retraining did not produce a new model, so ${ev.from_version} stayed active.` };
  const after = ev.after?.n || 0;
  if (ev.recovered === true) {
    const gap = ev.deltas?.after_vs_before?.accuracy;
    const below = gap !== null && gap !== undefined && gap < -0.05;
    return {
      tone: "stable", title: "Recovered",
      text: below
        ? `${ev.to_version} improved on the during-drift accuracy by ${pts(ev.deltas?.after_vs_during?.accuracy)}, which meets the recovery rule. It is still ${pts(Math.abs(gap)).replace("+", "")} below the pre-drift level.`
        : `${ev.to_version} brought accuracy back to ${pct(ev.after.accuracy)} on ${num(after)} outcomes after adaptation.`,
    };
  }
  if (ev.recovered === false) return { tone: "drift", title: "Not recovered", text: `${num(after)} outcomes after adaptation do not meet the recovery rule yet.` };
  return { tone: "warning", title: "Measuring recovery", text: after ? `${num(after)} outcomes after adaptation so far; the verdict needs a full window.` : "No labeled outcomes after the adaptation yet. Recovery is measured once actual categories arrive." };
}

/** Before → during → after accuracy for one drift, compact (dashboard, adaptation page). */
export function DriftImpactSummary({ impact, link }) {
  if (!impact) return null;
  const v = recoveryVerdict(impact);
  const cell = (seg) => (seg?.n ? pct(seg.accuracy) : "N/A");
  const phases = [["Before drift", impact.before, "stable", impact.from_version], ["During drift", impact.during, "drift", impact.from_version],
    ["After adaptation", impact.after, "adapted", impact.to_version || impact.from_version]];
  return (
    <div>
      <div className="hairlines rounded-md"><div className="hairlines-inner grid-cols-3">
        {phases.map(([label, seg, t, version]) => (
          <div key={label} className="px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-xs text-muted"><span className={`h-2 w-2 rounded-sm ${tone(t).solid}`} aria-hidden="true" />{label}</div>
            <div className="figure mt-1 text-lg text-fg">{cell(seg)}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted"><VersionTag version={version} />{seg?.n ? `${num(seg.n)} outcomes` : "no outcomes"}</div>
          </div>
        ))}
      </div></div>
      <div className="mt-3 flex items-start gap-2 text-sm">
        <ToneIcon tone={v.tone} className="mt-0.5 h-4 w-4" />
        <p><span className="font-medium text-fg">{v.title}.</span> <span className="text-muted">{v.text}</span></p>
      </div>
      {link && <div className="mt-2">{link}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ explanation */
/** "Why this prediction?" from ml/explain.py: base value + contributions = the confidence shown. */
export function ExplanationPanel({ explanation }) {
  if (!explanation?.contributions?.length) {
    return <p className="text-sm text-muted">No explanation was stored for this prediction.</p>;
  }
  const sum = explanation.contributions.reduce((s, c) => s + c.contribution, 0);
  const top = explanation.contributions.find((c) => c.direction === "supports");
  return (
    <div className="space-y-3">
      <p className="text-sm text-fg">
        {top ? <>The strongest push towards <strong className="font-semibold">{explanation.predicted}</strong> came from {top.label.toLowerCase()} ({String(top.value)}). </> : null}
        The bars show how each input moved the probability of {explanation.predicted}.
      </p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-canvas px-3 py-2 text-sm tabular" aria-label="How the contributions add up">
        <span><span className="text-muted">Starting point (training average)</span> <strong className="font-semibold">{pct(explanation.base_value)}</strong></span>
        <span className="text-faint">+</span>
        <span><span className="text-muted">inputs</span> <strong className="font-semibold">{pts(sum)}</strong></span>
        <span className="text-faint">=</span>
        <span><span className="text-muted">confidence</span> <strong className="font-semibold text-navy">{pct(explanation.probability)}</strong></span>
      </div>
      <ContributionBars contributions={explanation.contributions} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-navy" aria-hidden="true" />Raised the probability</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-stone" aria-hidden="true" />Lowered it</span>
      </div>
      <p className="text-xs leading-relaxed text-muted">
        How this is computed: every tree in the Random Forest follows a path of decisions; each split moves the probability of {explanation.predicted} up
        or down, and the move is credited to the input that split used. Credits are averaged over the forest and folded back into the eight purchase
        fields. They describe how the model reasons, not why the customer behaves this way.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ pipeline trace */
const STAGE_LABEL = { validated: "Input validated", stored: "Prediction ID and model version recorded", features: "Features derived", prediction: "Prediction generated",
  outcome: "Actual outcome", error: "Prediction error calculated", drift_check: "Drift detector updated", adaptation: "Model adaptation", notified: "Real-time update sent" };

/** Stages one event went through, as reported by the backend (POST /api/events → pipeline[]). */
export function PipelineStages({ stages }) {
  if (!stages?.length) return null;
  return (
    <ol className="space-y-2">
      {stages.map((s) => (
        <li key={s.stage} className="flex items-start gap-2.5 text-sm">
          <span className="mt-px"><StageIcon status={s.status} className="h-4 w-4" /></span>
          <span className="min-w-0"><span className="font-medium text-fg">{STAGE_LABEL[s.stage] || s.stage}</span>
            <span className="sr-only"> ({STAGE_WORD[s.status] || s.status})</span><span className="block text-xs text-muted">{s.detail}</span></span>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ activity */
const QUIET = new Set(["PREDICTION_CREATED", "PERFORMANCE_UPDATED", "SIMULATION_STATE"]);

/** Recent backend events, newest first: `initial` from the API, `live` from the WebSocket. */
export function ActivityFeed({ live = [], initial = [], stream, limit = 10, only, empty = "Nothing has happened on this stream yet." }) {
  const items = useMemo(() => {
    const seen = new Set();
    return [...live, ...initial]
      .filter((e) => (!stream || e.stream === stream) && (only ? only.includes(e.event) : !QUIET.has(e.event)))
      .filter((e) => {
        const key = `${e.event}|${e.timestamp}|${e.data?.prediction_id ?? ""}|${e.data?.step ?? ""}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)))
      .slice(0, limit);
  }, [live, initial, stream, limit, only]);
  if (!items.length) return <p className="px-5 py-6 text-sm text-muted">{empty}</p>;
  return (
    <ol className="divide-y divide-seam">
      {items.map((e, i) => (
        <li key={`${e.timestamp}-${e.event}-${i}`} className="flex gap-3 px-5 py-2.5">
          <ToneIcon tone={eventTone(e.event)} className="mt-0.5 h-4 w-4" />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-fg">{EVENT_LABELS[e.event] || e.event}</span>
              <time className="shrink-0 text-xs text-muted" dateTime={e.timestamp} title={e.timestamp}>{timeAgo(e.timestamp)}</time>
            </div>
            <p className="text-sm text-muted">{e.message}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ components */
export function ComponentStatus({ name, check, children }) {
  const m = componentMeta(check?.status);
  return (
    <div className="flex flex-col gap-1.5 px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-fg">{name}</span>
        <span className={`inline-flex items-center gap-1 text-xs font-medium ${tone(m.tone).text}`}><ToneIcon tone={m.tone} className="h-3.5 w-3.5" />{m.label}</span>
      </div>
      <p className="text-sm text-muted">{check?.message || "No status reported"}</p>
      {children && <div className="text-xs text-muted">{children}</div>}
    </div>
  );
}

/** A link to the drift-performance page for a given drift event. */
export function DriftLink({ eventKey, stream, children }) {
  const q = new URLSearchParams();
  if (stream === "simulation") q.set("stream", "simulation");
  if (eventKey) q.set("event", eventKey);
  return <Link to={`/app/drift-performance?${q}`} className="link">{children}</Link>;
}
