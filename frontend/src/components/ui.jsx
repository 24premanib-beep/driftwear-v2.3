/**
 * DriftWear interface primitives. Pages are composed from these so spacing, type, states and feedback stay
 * consistent. State colours are reserved for detector / model states and always come with an icon and a label.
 */
import { Children, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Check, ChevronDown, ChevronLeft, ChevronRight, CircleCheck, CircleDashed, CircleX, Copy, FlaskConical,
  Info, LoaderCircle, OctagonAlert, RefreshCw, TriangleAlert, X } from "lucide-react";
import { healthMeta, statusMeta } from "../lib/format";

/* ------------------------------------------------------------------ tones */
export const TONES = {
  stable: { text: "text-stable-ink", soft: "bg-stable-soft", border: "border-stable/45", solid: "bg-stable", ring: "ring-stable/40", icon: CircleCheck },
  warning: { text: "text-warning-ink", soft: "bg-warning-soft", border: "border-warning/55", solid: "bg-warning", ring: "ring-warning/40", icon: TriangleAlert },
  drift: { text: "text-drift-ink", soft: "bg-drift-soft", border: "border-drift/45", solid: "bg-drift", ring: "ring-drift/40", icon: OctagonAlert },
  adapted: { text: "text-adapted-ink", soft: "bg-adapted-soft", border: "border-adapted/45", solid: "bg-adapted", ring: "ring-adapted/40", icon: RefreshCw },
  neutral: { text: "text-muted", soft: "bg-canvas", border: "border-seam-strong", solid: "bg-faint", ring: "ring-seam", icon: CircleDashed },
  plum: { text: "text-plum", soft: "bg-plum-50", border: "border-plum/40", solid: "bg-plum", ring: "ring-plum/30", icon: Info },
  info: { text: "text-muted", soft: "bg-canvas", border: "border-seam-strong", solid: "bg-faint", ring: "ring-seam", icon: Info },
  /* a single prediction's result: quieter than the detector states, so red stays reserved for drift */
  correct: { text: "text-stable-ink", soft: "bg-raised", border: "border-seam-strong", solid: "bg-stable", ring: "ring-seam", icon: CircleCheck },
  wrong: { text: "text-drift-ink", soft: "bg-raised", border: "border-seam-strong", solid: "bg-drift", ring: "ring-seam", icon: CircleX },
};
export const tone = (t) => TONES[t] || TONES.neutral;

export function ToneIcon({ tone: t, className = "h-4 w-4", spin = false }) {
  const { icon: Icon, text } = tone(t);
  return <Icon className={`${className} shrink-0 ${text} ${spin ? "animate-spin [animation-duration:2.4s]" : ""}`} aria-hidden="true" />;
}

/* ------------------------------------------------------------------ states */
/** Detector state as a labelled pill: icon + label + colour. */
export function StateBadge({ status, adapting = false, size = "md", className = "" }) {
  const key = adapting ? "ADAPTING" : status;
  const meta = statusMeta(key);
  const t = tone(meta.tone);
  const sizes = { sm: "px-2 py-0.5 text-xs gap-1", md: "px-2.5 py-1 text-sm gap-1.5", lg: "px-3 py-1.5 text-md gap-2" };
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full border font-medium ${t.soft} ${t.border} ${t.text} ${sizes[size]} ${className}`}>
      <ToneIcon tone={meta.tone} className={size === "lg" ? "h-[18px] w-[18px]" : size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} spin={adapting} />
      {meta.label}
    </span>
  );
}

const TRACK = ["STABLE", "WARNING", "DRIFT"];

/**
 * Stable → Warning → Drift, with the current state lit. While a new model is being trained an "Adapting" step is
 * appended. The three states are not progress: the detector can return to Stable at any time.
 */
export function StateTrack({ status, adapting = false, adaptingTo = null, size = "md", label = "Detector state" }) {
  const lg = size === "lg";
  return (
    <ol className={`flex flex-wrap items-center ${lg ? "gap-2" : "gap-1.5"}`} aria-label={label}>
      {TRACK.map((s, i) => {
        const on = status === s;
        const meta = statusMeta(s);
        const t = tone(meta.tone);
        return (
          <li key={s} className="flex items-center gap-1.5" aria-current={on ? "step" : undefined}>
            {i > 0 && <ChevronRight className={`${lg ? "h-4 w-4" : "h-3.5 w-3.5"} text-seam-strong`} aria-hidden="true" />}
            <span className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${lg ? "px-3.5 py-1.5 text-md" : "px-2.5 py-0.5 text-xs"} ${on
              ? `${t.soft} ${t.border} ${t.text}` : "border-dashed border-seam-strong bg-transparent text-faint"}`}>
              {on ? <ToneIcon tone={meta.tone} className={lg ? "h-[18px] w-[18px]" : "h-3.5 w-3.5"} />
                : <span className={`${lg ? "h-2 w-2" : "h-1.5 w-1.5"} rounded-full border border-faint`} aria-hidden="true" />}
              {meta.label}
              {on && <span className="sr-only"> (current state)</span>}
            </span>
          </li>
        );
      })}
      {adapting && (
        <li className="flex items-center gap-1.5">
          <ChevronRight className={`${lg ? "h-4 w-4" : "h-3.5 w-3.5"} text-seam-strong`} aria-hidden="true" />
          <span className={`inline-flex items-center gap-1.5 rounded-full border ${tone("adapted").border} ${tone("adapted").soft} ${tone("adapted").text} font-medium ${lg ? "px-3.5 py-1.5 text-md" : "px-2.5 py-0.5 text-xs"}`}>
            <ToneIcon tone="adapted" spin className={lg ? "h-[18px] w-[18px]" : "h-3.5 w-3.5"} />
            {adaptingTo ? `Adapting to ${adaptingTo}` : "Adapting"}
          </span>
        </li>
      )}
    </ol>
  );
}

export function HealthBadge({ band, score, size = "md" }) {
  const m = healthMeta(band);
  const t = tone(m.tone);
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-medium ${t.soft} ${t.border} ${t.text} ${size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm"}`}>
      <ToneIcon tone={m.tone} className="h-3.5 w-3.5" />{m.label}{score !== undefined && score !== null && <span className="tabular">· {score}</span>}
    </span>
  );
}

/** Model version as a hang tag. `active` fills it with the brand ink. */
export function VersionTag({ version, active = false, size = "md", title, className = "" }) {
  if (!version) return <span className="text-faint">—</span>;
  return (
    <span className={`vtag ${active ? "vtag-active" : ""} ${size === "lg" ? "vtag-lg" : ""} ${className}`}
      title={title || (active ? `Model ${version} (active)` : `Model ${version}`)}>
      {version}
      {active && <span className="sr-only"> (active)</span>}
    </span>
  );
}

export function SeverityBadge({ severity }) {
  if (!severity) return null;
  const t = { High: "drift", Medium: "warning", Low: "neutral" }[severity] || "neutral";
  return <Badge tone={t}>{severity} severity</Badge>;
}

/* ------------------------------------------------------------------ layout */
export function PageHeader({ title, lede, actions, children, eyebrow }) {
  return (
    <header className="mb-7 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
        <h1 className="display text-2xl text-navy md:text-[2.25rem] md:leading-[2.5rem]">{title}</h1>
        {lede && <p className="mt-2 max-w-prose text-md leading-relaxed text-muted">{lede}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 lg:justify-end">{actions}</div>}
    </header>
  );
}

/** An unboxed section: heading, optional description and actions, separated from the next by space. */
export function Section({ title, description, actions, children, className = "", id }) {
  return (
    <section className={className} aria-labelledby={id ? `${id}-title` : undefined} id={id}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {title && <h2 id={id ? `${id}-title` : undefined} className="text-md font-semibold text-fg">{title}</h2>}
            {description && <p className="mt-0.5 max-w-prose text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** A bordered panel for grouped content or tables. `flush` removes body padding (tables, lists). */
export function Panel({ title, description, actions, children, className = "", flush = false, footer, ...rest }) {
  return (
    <section className={`panel ${className}`} {...rest}>
      {(title || actions) && (
        <div className="panel-head">
          <div className="min-w-0">
            {title && <h2 className="text-md font-semibold text-fg">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={flush ? "" : "p-5"}>{children}</div>
      {footer && <div className="border-t border-seam px-5 py-3 text-sm text-muted">{footer}</div>}
    </section>
  );
}

/** A strip of figures divided by hairlines: one object, not a grid of KPI cards. */
const MEASURE_COLS = { 2: "lg:grid-cols-2", 3: "lg:grid-cols-3", 4: "lg:grid-cols-4", 5: "lg:grid-cols-5", 6: "lg:grid-cols-6", 7: "lg:grid-cols-7" };
export function Measures({ children, className = "" }) {
  const n = Children.toArray(children).filter(Boolean).length;
  return (
    <div className={`hairlines ${className}`}>
      <dl className={`hairlines-inner grid-cols-2 sm:grid-cols-3 ${MEASURE_COLS[n] || "lg:grid-cols-6"}`}>{children}</dl>
    </div>
  );
}

export function Measure({ label, value, sub, tone: t, to, title }) {
  const valueClass = t ? tone(t).text : "text-navy";
  const body = (
    <>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={`figure mt-1 text-xl ${valueClass}`} title={title}>{value}</dd>
      {sub && <dd className="mt-0.5 text-xs text-muted">{sub}</dd>}
    </>
  );
  const cls = "min-w-0 px-4 py-3.5";
  return to
    ? <div className={`${cls} transition-colors hover:bg-navy-50/60`}><Link to={to} className="block focus-visible:outline-offset-4">{body}</Link></div>
    : <div className={cls}>{body}</div>;
}

/* ------------------------------------------------------------------ small parts */
const BADGE_TONES = {
  neutral: "bg-canvas text-muted ring-1 ring-inset ring-seam-strong",
  navy: "bg-navy-100 text-navy",
  plum: "bg-plum-50 text-plum ring-1 ring-inset ring-plum/25",
  stable: "bg-stable-soft text-stable-ink",
  warning: "bg-warning-soft text-warning-ink",
  drift: "bg-drift-soft text-drift-ink",
  adapted: "bg-adapted-soft text-adapted-ink",
  correct: "bg-raised text-stable-ink ring-1 ring-inset ring-seam-strong",
  wrong: "bg-raised text-drift-ink ring-1 ring-inset ring-seam-strong",
};

export function Badge({ children, tone: t = "neutral", className = "", icon = false, ...rest }) {
  return (
    <span className={`badge ${BADGE_TONES[t] || BADGE_TONES.neutral} ${className}`} {...rest}>
      {icon && <ToneIcon tone={t} className="h-3 w-3" />}{children}
    </span>
  );
}

export function SimulationChip({ className = "" }) {
  return (
    <span className={`chip toile border-navy/25 bg-raised text-navy ${className}`} title="Synthetic data from the simulation, never mixed with live data">
      <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />Simulation
    </span>
  );
}

export function LiveChip({ className = "" }) {
  return (
    <span className={`chip border-seam-strong bg-raised text-navy ${className}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-navy" aria-hidden="true" />Live data
    </span>
  );
}

export function StreamChip({ stream }) {
  return stream === "simulation" ? <SimulationChip /> : <LiveChip />;
}

export function Spinner({ className = "h-4 w-4" }) {
  return <LoaderCircle className={`animate-spin ${className}`} aria-hidden="true" />;
}

/** Loading state that says what is being retrieved. */
export function Loading({ label = "Loading…", rows = 3, className = "" }) {
  return (
    <div className={`py-6 ${className}`} role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-sm text-muted"><Spinner />{label}</div>
      {rows > 0 && (
        <div className="mt-4 space-y-2.5" aria-hidden="true">
          {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton h-3.5" style={{ width: `${92 - i * 14}%` }} />)}
        </div>
      )}
    </div>
  );
}

/** A failed request: what happened, a reference for support, and a way to try again. */
export function ErrorNote({ error, onRetry, title, className = "" }) {
  if (!error) return null;
  const offline = error.status === 0;
  const forbidden = error.status === 403;
  return (
    <div className={`flex items-start gap-3 rounded-md border border-drift/35 bg-drift-soft/60 px-4 py-3 text-sm ${className}`} role="alert">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-drift-ink" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-fg">{title || (offline ? "The server could not be reached" : forbidden ? "Not allowed for your role" : "Something went wrong")}</p>
        <p className="mt-0.5 text-fg/85">{error.message || String(error)}</p>
        {error.requestId && <p className="mt-1 text-xs text-muted">Reference {error.requestId}</p>}
      </div>
      {onRetry && <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Notice({ tone: t = "neutral", title, children, className = "", icon = true, action }) {
  const x = tone(t);
  return (
    <div className={`flex items-start gap-3 rounded-md border px-4 py-3 text-sm ${x.border} ${t === "neutral" ? "bg-surface" : x.soft} ${className}`} role="status">
      {icon && <ToneIcon tone={t} className="mt-0.5 h-4 w-4" />}
      <div className="min-w-0 flex-1 text-fg">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={title ? "mt-0.5 text-fg/85" : ""}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

/** Empty state: why there is nothing yet, and what to do next. */
export function Empty({ title, children, action, icon: Icon, className = "" }) {
  return (
    <div className={`flex flex-col items-start px-5 py-8 ${className}`}>
      {Icon && <Icon className="mb-3 h-5 w-5 text-faint" aria-hidden="true" />}
      <p className="font-medium text-fg">{title}</p>
      {children && <div className="mt-1 max-w-prose text-sm text-muted">{children}</div>}
      {action && <div className="mt-4 flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}

export function Field({ label, error, hint, htmlFor, children, className = "", optional = false }) {
  return (
    <div className={className}>
      {label && (
        <label className="field-label" htmlFor={htmlFor}>
          {label}{optional && <span className="ml-1 font-normal text-faint">(optional)</span>}
        </label>
      )}
      {children}
      {error ? <p className="mt-1 flex items-center gap-1 text-xs text-drift-ink" id={htmlFor ? `${htmlFor}-error` : undefined}>
        <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />{error}</p>
        : hint ? <p className="hint">{hint}</p> : null}
    </div>
  );
}

/** Accessible tabs (roving tabindex, arrow keys). */
export function Tabs({ tabs, value, onChange, label, size = "md" }) {
  const refs = useRef([]);
  const idx = Math.max(0, tabs.findIndex((t) => t.value === value));
  const onKey = (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const n = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (idx + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    onChange(tabs[n].value);
    refs.current[n]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="inline-flex rounded-md border border-seam-strong bg-canvas p-0.5" onKeyDown={onKey}>
      {tabs.map((t, i) => {
        const on = t.value === value;
        const Icon = t.icon;
        return (
          <button key={t.value} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" aria-selected={on} tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.value)}
            className={`inline-flex items-center gap-1.5 rounded-[5px] font-medium transition-colors ${size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm"} ${on
              ? "bg-raised text-navy shadow-[0_0_0_1px_rgba(23,32,54,.12)]" : "text-muted hover:text-fg"}`}>
            {Icon && <Icon className="h-3.5 w-3.5" aria-hidden="true" />}{t.label}
            {t.count !== undefined && <span className="tabular text-faint">{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Progressive disclosure: technical detail on request. */
export function Disclosure({ summary, children, defaultOpen = false, className = "" }) {
  return (
    <details className={`group rounded-md border border-seam bg-surface ${className}`} open={defaultOpen || undefined}>
      <summary className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm font-medium text-fg hover:bg-navy-50/50">
        <span className="min-w-0">{summary}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="border-t border-seam px-4 py-3.5">{children}</div>
    </details>
  );
}

export function CopyButton({ value, label = "Copy", className = "" }) {
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return undefined;
    const t = setTimeout(() => setDone(false), 1800);
    return () => clearTimeout(t);
  }, [done]);
  return (
    <button type="button" className={`btn btn-quiet btn-sm px-1.5 ${className}`} aria-label={done ? "Copied" : `${label}: ${value}`}
      onClick={() => navigator.clipboard?.writeText(String(value)).then(() => setDone(true)).catch(() => {})}>
      {done ? <Check className="h-3.5 w-3.5 text-stable-ink" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
      <span className="sr-only" aria-live="polite">{done ? "Copied" : ""}</span>
    </button>
  );
}

/** An identifier that people copy (event ids, prediction ids). */
export function Ident({ value, prefix = "", copy = true }) {
  if (value === null || value === undefined || value === "") return <span className="text-faint">—</span>;
  return (
    <span className="inline-flex max-w-full items-center gap-0.5">
      <code className="truncate rounded bg-canvas px-1 py-px text-[12px] text-fg">{prefix}{value}</code>
      {copy && <CopyButton value={value} label="Copy identifier" />}
    </span>
  );
}

/** Live vs simulation. The simulation option carries the toile hatch so it is never mistaken for live data. */
export function StreamSwitch({ stream, onChange }) {
  const opt = (value, label) => {
    const on = stream === value;
    return (
      <button type="button" role="radio" aria-checked={on} onClick={() => onChange(value)}
        className={`inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 text-sm font-medium transition-colors ${on
          ? `${value === "simulation" ? "toile" : ""} bg-raised text-navy shadow-[0_0_0_1px_rgba(23,32,54,.14)]` : "text-muted hover:text-fg"}`}>
        {value === "simulation" ? <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />}
        {label}
      </button>
    );
  };
  return (
    <div role="radiogroup" aria-label="Data stream" className="inline-flex rounded-md border border-seam-strong bg-canvas p-0.5">
      {opt("live", "Live data")}{opt("simulation", "Simulation")}
    </div>
  );
}

export function SimulationBanner({ children }) {
  return (
    <div className="toile mb-6 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-navy/20 bg-raised px-4 py-2.5 text-sm text-fg">
      <span className="inline-flex items-center gap-1.5 font-semibold text-navy"><FlaskConical className="h-4 w-4" aria-hidden="true" />Simulation</span>
      <span className="text-fg/85">{children || "You are looking at the synthetic replay. These records are not customer activity and are kept out of every live figure."}</span>
    </div>
  );
}

export function Table({ children, className = "", caption }) {
  return (
    <div className={`relative overflow-x-auto scrollbar-thin ${className}`}>
      <table className="min-w-full border-separate border-spacing-0">
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}

export function DefinitionList({ items, columns = 2 }) {
  return (
    <dl className={`grid grid-cols-1 gap-x-8 gap-y-3.5 ${columns === 3 ? "sm:grid-cols-2 xl:grid-cols-3" : columns === 1 ? "" : "sm:grid-cols-2"}`}>
      {items.filter(Boolean).map(([term, value, hint]) => (
        <div key={term} className="min-w-0">
          <dt className="text-xs text-muted">{term}</dt>
          <dd className="mt-0.5 break-words text-sm text-fg">{value ?? "—"}</dd>
          {hint && <dd className="mt-0.5 text-xs text-faint">{hint}</dd>}
        </div>
      ))}
    </dl>
  );
}

export function Pagination({ page, pages, total, onChange, noun = "records" }) {
  if (!total) return null;
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm text-muted">
      <span className="tabular">{total.toLocaleString()} {noun}</span>
      <div className="flex items-center gap-1">
        <button type="button" className="btn btn-quiet btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </button>
        <span className="tabular px-1">Page {page} of {pages}</span>
        <button type="button" className="btn btn-quiet btn-sm" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page">
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function useModal(open, onClose, busy, initialFocus) {
  const latest = useRef({ onClose, busy });
  latest.current = { onClose, busy };
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    const t = setTimeout(() => initialFocus.current?.focus(), 0);
    const onKey = (e) => { if (e.key === "Escape" && !latest.current.busy) latest.current.onClose(); };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { clearTimeout(t); window.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; previous?.focus?.(); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** Focus-trapping confirmation dialog for consequential actions. The server's response decides the outcome. */
export function ConfirmDialog({ open, title, children, confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false,
  busy = false, confirmDisabled = false, onConfirm, onCancel }) {
  const cancelRef = useRef(null);
  const titleId = useId();
  useModal(open, onCancel, busy, cancelRef);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <button type="button" className="absolute inset-0 cursor-default bg-navy/45 animate-fade-in" aria-label={cancelLabel} tabIndex={-1} onClick={() => !busy && onCancel()} />
      <div role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="relative max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-lg bg-surface shadow-dialog sm:rounded-lg">
        <div className="border-b border-seam px-6 py-4">
          <h2 id={titleId} className="display text-xl text-navy">{title}</h2>
        </div>
        <div className="space-y-4 px-6 py-5 text-sm text-fg">{children}</div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-seam bg-canvas/50 px-6 py-3.5">
          <button ref={cancelRef} type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
          <button type="button" className={danger ? "btn btn-danger" : "btn btn-primary"} onClick={onConfirm} disabled={busy || confirmDisabled}>
            {busy && <Spinner />}{confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Side panel for record details. */
export function Drawer({ open, title, subtitle, onClose, children, width = "max-w-xl" }) {
  const closeRef = useRef(null);
  const titleId = useId();
  useModal(open, onClose, false, closeRef);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" className="absolute inset-0 cursor-default bg-navy/35 animate-fade-in" aria-label="Close" tabIndex={-1} onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className={`relative flex h-full w-full ${width} flex-col bg-surface shadow-dialog animate-slide-in`}>
        <div className="flex items-start justify-between gap-3 border-b border-seam px-6 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="display text-xl text-navy">{title}</h2>
            {subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}
          </div>
          <button ref={closeRef} type="button" className="btn btn-quiet px-2" onClick={onClose} aria-label="Close"><X className="h-5 w-5" aria-hidden="true" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

/** Small "why" hint next to a term. */
export function Hint({ children, label = "What does this mean?" }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-flex align-middle">
      <button type="button" className="rounded-full text-faint hover:text-navy" aria-label={label} aria-expanded={open} aria-controls={id}
        onClick={() => setOpen((o) => !o)} onBlur={() => setOpen(false)}>
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {open && (
        <span id={id} role="tooltip" className="absolute left-1/2 top-6 z-30 w-64 -translate-x-1/2 rounded-md bg-navy px-3 py-2 text-xs font-normal leading-relaxed text-white shadow-pop">
          {children}
        </span>
      )}
    </span>
  );
}

/** Uniform "N/A" for unmeasured values. */
export const NA = "N/A";
export const has = (v) => v !== null && v !== undefined && !(typeof v === "number" && Number.isNaN(v));
export const na = (v, f = (x) => x) => (has(v) ? f(v) : NA);
