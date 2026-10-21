import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Sparkle } from "lucide-react";
import { ProbabilityBars } from "../components/charts";
import { ExplanationPanel } from "../components/insights";
import { DefinitionList, Disclosure, Empty, ErrorNote, Field, Hint, Ident, Loading, Notice, PageHeader, Panel, Spinner, StateBadge,
  Table, VersionTag } from "../components/ui";
import { useLiveRefresh } from "../context/RealtimeContext";
import { Predictions } from "../lib/endpoints";
import { dateTime, money, pct, timeAgo } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { MONTHS, useMeta } from "../lib/meta";

function localNow() {
  const d = new Date();
  d.setSeconds(0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

const INITIAL = { customer_id: "", previous_category: "Tops", customer_preference: "Casual", purchase_frequency: 6,
  recency: 21, purchase_date: localNow(), price: 1499, discount: 10, actual_category: "" };

/** What happened when an actual category was recorded (backend OutcomeOut). */
export function OutcomeSummary({ outcome, predictedVersion }) {
  const changed = outcome.rescored;
  return (
    <Notice tone={outcome.new_model_version ? "adapted" : outcome.is_correct ? "stable" : "warning"}
      title={outcome.is_correct ? `Correct: the customer bought ${outcome.actual_category}.` : `Wrong: the customer bought ${outcome.actual_category}, not ${outcome.predicted_category}.`}>
      <p>
        Scored as outcome #{outcome.step + 1} (error = {outcome.is_correct ? 0 : 1}). The detector moved from {outcome.previous_status.toLowerCase()} to{" "}
        <strong className="font-medium">{outcome.status.toLowerCase()}</strong>; recent accuracy is {pct(outcome.rolling_accuracy)}.
      </p>
      {changed && (
        <p className="mt-1">The model changed before this outcome arrived, so {outcome.scored_version} re-scored the purchase for drift monitoring.
          The stored prediction{predictedVersion ? ` by ${predictedVersion}` : ""} is unchanged.</p>
      )}
      {outcome.drift_detected && <p className="mt-1 font-medium text-drift-ink">This outcome confirmed concept drift.</p>}
      {outcome.new_model_version && <p className="mt-1 font-medium text-adapted-ink">The model adapted: {outcome.new_model_version} is now active.</p>}
      {outcome.adaptation_error && <p className="mt-1 text-drift-ink">Adaptation failed and the previous model stays active: {outcome.adaptation_error}</p>}
    </Notice>
  );
}

function OutcomeForm({ prediction, categories, onDone }) {
  const [actual, setActual] = useState("");
  const action = useAction(() => Predictions.recordOutcome(prediction.id, actual));
  if (action.result) return <OutcomeSummary outcome={action.result} predictedVersion={prediction.model_version} />;
  return (
    <div className="rounded-md border border-dashed border-seam-strong bg-canvas/50 p-4">
      <p className="text-sm font-medium text-fg">Accuracy is not known yet</p>
      <p className="mt-0.5 text-sm text-muted">The prediction is stored. When you learn what the customer bought, record it here or later in Prediction history.
        Only then is the error computed and the drift detector updated.</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label="Actual category" htmlFor={`actual-${prediction.id}`} className="min-w-[200px] flex-1">
          <select id={`actual-${prediction.id}`} className="input" value={actual} onChange={(e) => setActual(e.target.value)}>
            <option value="">Choose what was bought</option>
            {categories.map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>
        <button type="button" className="btn btn-primary" disabled={!actual || action.busy}
          onClick={async () => { const r = await action.run(); if (r) onDone?.(r); }}>
          {action.busy && <Spinner />}{action.busy ? "Recording…" : "Record outcome"}
        </button>
      </div>
      <ErrorNote error={action.error} className="mt-3" />
    </div>
  );
}

function Result({ result, categories, onChanged }) {
  const p = result.prediction;
  const f = p.features || {};
  const expl = result.explanation || p.explanation;
  const top = expl?.contributions?.find((c) => c.direction === "supports");
  const runnerUp = Object.entries(p.probabilities || {}).filter(([c]) => c !== p.predicted_category).sort((a, b) => b[1] - a[1])[0];
  const close = runnerUp && p.confidence - runnerUp[1] < 0.05;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div>
          <p className="text-sm text-muted">Predicted next category</p>
          <p className="display-tight text-4xl text-navy">{p.predicted_category}</p>
          <p className="mt-1 flex items-center gap-1.5 text-md text-fg">
            <span className="figure">{pct(p.confidence)}</span> probability
            <Hint label="What does the probability mean?">The Random Forest's probability for this category (its trees' averaged vote). It is not the chance that the prediction is correct; that is only known once the actual category arrives.</Hint>
          </p>
        </div>
        <DefinitionList columns={1} items={[
          ["Made by", <VersionTag key="v" version={p.model_version} />],
          ["Prediction", <Ident key="i" value={p.id} prefix="#" />],
          ["Made at", <time key="t" dateTime={p.created_at} title={dateTime(p.created_at)}>{dateTime(p.created_at)}</time>],
        ]} />
      </div>

      {result.outcome ? <OutcomeSummary outcome={result.outcome} predictedVersion={p.model_version} />
        : <OutcomeForm key={p.id} prediction={p} categories={categories} onDone={onChanged} />}

      <section aria-labelledby="probs">
        <h3 id="probs" className="mb-2 text-sm font-semibold text-fg">Probability for each category</h3>
        <ProbabilityBars probabilities={p.probabilities} predicted={p.predicted_category} categories={categories} />
        {close && <p className="mt-2 text-sm text-warning-ink">A close call: {runnerUp[0]} is within {Math.max(0, Math.round((p.confidence - runnerUp[1]) * 1000) / 10)} points. Treat this prediction with caution.</p>}
      </section>

      <Disclosure summary={<span>Why this prediction?{top && <span className="ml-2 font-normal text-muted">Biggest push: {top.label.toLowerCase()} ({String(top.value)})</span>}</span>}>
        <ExplanationPanel explanation={expl} />
      </Disclosure>

      <Disclosure summary="Technical details">
        <DefinitionList items={[
          ["Detector state when predicted", <StateBadge key="s" status={p.status_at_prediction} size="sm" />],
          ["Frozen v1.0 would predict", p.baseline_prediction],
          ["Customer", f.Customer_ID || "Not given"], ["Purchase date", f.Purchase_Date],
          ["Previous category", f.Previous_Category], ["Preference", f.Customer_Preference],
          ["Orders so far", f.Purchase_Frequency], ["Days since last order", f.Recency],
          ["Month and season", `${MONTHS[(f.Month || 1) - 1]} · ${f.Season}`], ["Price and discount", `${money(f.Price)} · ${f.Discount}% off`],
          ["Stream", "Live (prediction form)"], ["Server message", result.message],
        ]} />
      </Disclosure>
    </div>
  );
}

function Fieldset({ legend, children, note }) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-3 text-sm font-semibold text-navy">{legend}</legend>
      {note && <p className="-mt-2 mb-3 text-xs text-muted">{note}</p>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

export default function Predict() {
  const meta = useMeta();
  const [form, setForm] = useState(INITIAL);
  const [monthOverride, setMonthOverride] = useState("");
  const [seasonOverride, setSeasonOverride] = useState("");
  const [result, setResult] = useState(null);
  const submit = useAction((payload) => Predictions.predict(payload));
  const pending = useApi(() => Predictions.list({ labeled: false, source: "api", page_size: 6 }), []);
  useLiveRefresh(() => pending.reload({ silent: true }), "live", { events: new Set(["PREDICTION_RESULT", "PREDICTION_CREATED"]) });

  const b = meta.bounds;
  const dateMonth = form.purchase_date ? Number(form.purchase_date.slice(5, 7)) : new Date().getMonth() + 1;
  const month = monthOverride ? Number(monthOverride) : dateMonth;
  const season = seasonOverride || meta.month_to_season[String(month)] || meta.month_to_season[month];
  const serverErrors = submit.error?.fieldErrors || {};
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const clientErrors = useMemo(() => {
    const errs = {};
    const check = (key, bound, label, { exclusiveMin = false, integer = false } = {}) => {
      const v = Number(form[key]);
      const [lo, hi] = b[bound];
      if (form[key] === "" || Number.isNaN(v)) errs[key] = `Enter ${label}.`;
      else if (integer && !Number.isInteger(v)) errs[key] = "Use a whole number.";
      else if ((exclusiveMin ? v <= lo : v < lo) || v > hi) errs[key] = exclusiveMin ? `Must be more than ${lo} and at most ${hi.toLocaleString()}.` : `Must be between ${lo} and ${hi.toLocaleString()}.`;
    };
    check("purchase_frequency", "Purchase_Frequency", "the number of orders", { integer: true });
    check("recency", "Recency", "days since the last order", { integer: true });
    check("price", "Price", "a price", { exclusiveMin: true });
    check("discount", "Discount", "a discount");
    if (form.customer_id && !/^[A-Za-z0-9_-]{1,20}$/.test(form.customer_id)) errs.customer_id = "Letters, numbers, - and _ only (up to 20).";
    if (form.purchase_date && new Date(form.purchase_date) > new Date(Date.now() + 60000)) errs.purchase_date = "The purchase date cannot be in the future.";
    return errs;
  }, [form, b]);
  const invalid = Object.keys(clientErrors).length > 0;
  const err = (k) => clientErrors[k] || serverErrors[k];

  const onSubmit = async (e) => {
    e.preventDefault();
    if (invalid) return;
    const payload = {
      customer_id: form.customer_id.trim() || null, previous_category: form.previous_category,
      customer_preference: form.customer_preference, purchase_frequency: Number(form.purchase_frequency),
      recency: Number(form.recency), price: Number(form.price), discount: Number(form.discount),
      purchase_date: form.purchase_date ? `${form.purchase_date}:00` : null, month, season,
      actual_category: form.actual_category || null,
    };
    const r = await submit.run(payload);
    if (r) { setResult(r); pending.reload({ silent: true }); }
  };

  const select = (id, key, options) => (
    <select id={id} className="input" value={form[key]} onChange={set(key)}>{options.map((c) => <option key={c}>{c}</option>)}</select>
  );
  const number = (id, key, extra) => (
    <input id={id} type="number" inputMode="numeric" className={`input ${err(key) ? "input-invalid" : ""}`} value={form[key]} onChange={set(key)}
      aria-invalid={Boolean(err(key)) || undefined} aria-describedby={err(key) ? `${id}-error` : undefined} {...extra} />
  );

  return (
    <>
      <PageHeader title="Live prediction"
        lede="Describe a purchase to predict the category this customer buys next. The prediction is stored with the model version that made it; whether it was right is only known once the actual category is recorded." />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <Panel title="Purchase">
          <form onSubmit={onSubmit} className="space-y-7" noValidate>
            <Fieldset legend="Customer">
              <Field label="Customer ID" optional htmlFor="cid" error={err("customer_id")} hint="For example C1042">
                <input id="cid" className={`input ${err("customer_id") ? "input-invalid" : ""}`} maxLength={20} value={form.customer_id} onChange={set("customer_id")} placeholder="C1042" />
              </Field>
              <Field label="Style preference" htmlFor="pref">{select("pref", "customer_preference", meta.preferences)}</Field>
              <Field label="Previous category bought" htmlFor="prev">{select("prev", "previous_category", meta.categories)}</Field>
              <Field label="Orders so far" htmlFor="freq" error={err("purchase_frequency")} hint={`Whole number, ${b.Purchase_Frequency[0]}–${b.Purchase_Frequency[1]}`}>
                {number("freq", "purchase_frequency", { min: b.Purchase_Frequency[0], max: b.Purchase_Frequency[1], step: 1 })}
              </Field>
              <Field label="Days since last order" htmlFor="rec" error={err("recency")} hint={`Whole number, ${b.Recency[0]}–${b.Recency[1]}`} className="sm:col-span-2">
                {number("rec", "recency", { min: b.Recency[0], max: b.Recency[1], step: 1 })}
              </Field>
            </Fieldset>

            <Fieldset legend="This purchase">
              <Field label="Date and time" htmlFor="pdate" error={err("purchase_date")} hint="Sets the month and season">
                <input id="pdate" type="datetime-local" className={`input ${err("purchase_date") ? "input-invalid" : ""}`} value={form.purchase_date} onChange={set("purchase_date")} />
              </Field>
              <Field label="Price (₹)" htmlFor="price" error={err("price")} hint={`More than 0, up to ${b.Price[1].toLocaleString()}`}>
                <input id="price" type="number" inputMode="decimal" step="any" min="0" max={b.Price[1]} className={`input ${err("price") ? "input-invalid" : ""}`}
                  value={form.price} onChange={set("price")} aria-invalid={Boolean(err("price")) || undefined} />
              </Field>
              <Field label={`Discount: ${form.discount}%`} htmlFor="disc" error={err("discount")} hint={`${b.Discount[0]}–${b.Discount[1]}%`} className="sm:col-span-2">
                <input id="disc" type="range" className="mt-1 w-full accent-[#172036]" min={b.Discount[0]} max={b.Discount[1]} value={form.discount} onChange={set("discount")} />
              </Field>
              <Field label="Month" htmlFor="month" hint={monthOverride ? "Set by hand" : "From the date"}>
                <select id="month" className="input" value={monthOverride} onChange={(e) => setMonthOverride(e.target.value)}>
                  <option value="">{MONTHS[dateMonth - 1]} (from the date)</option>
                  {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                </select>
              </Field>
              <Field label="Season" htmlFor="season" hint={seasonOverride ? "Set by hand" : "From the month"}>
                <select id="season" className="input" value={seasonOverride} onChange={(e) => setSeasonOverride(e.target.value)}>
                  <option value="">{season} (from the month)</option>
                  {meta.seasons.map((s) => <option key={s}>{s}</option>)}
                </select>
              </Field>
            </Fieldset>

            <Fieldset legend="Outcome" note="Only if you already know what the customer bought. Otherwise leave it and record it later.">
              <Field label="Actual category" optional htmlFor="actual" className="sm:col-span-2">
                <select id="actual" className="input" value={form.actual_category} onChange={set("actual_category")}>
                  <option value="">Not known yet</option>
                  {meta.categories.map((c) => <option key={c}>{c}</option>)}
                </select>
              </Field>
            </Fieldset>

            <div className="border-t border-seam pt-5">
              <ErrorNote error={submit.error && !Object.keys(serverErrors).length ? submit.error : null} className="mb-4"
                title={submit.error?.status === 429 ? "Too many predictions" : undefined} />
              {Object.keys(serverErrors).length > 0 && <p className="mb-3 text-sm text-drift-ink">The server rejected some values. They are marked above.</p>}
              <button type="submit" className="btn btn-primary" disabled={submit.busy || invalid}>
                {submit.busy ? <Spinner /> : <Sparkle className="h-4 w-4" aria-hidden="true" />}{submit.busy ? "Predicting…" : "Predict next category"}
              </button>
              {invalid && <p className="mt-2 text-xs text-muted">Fix the marked fields to continue.</p>}
            </div>
          </form>
        </Panel>

        <div className="space-y-6">
          <Panel title="Prediction" aria-live="polite">
            {submit.busy && !result ? <Loading label="Validating the purchase and asking the active model…" rows={4} /> : !result ? (
              <Empty title="The prediction appears here" icon={Sparkle}>
                You will see the predicted category, the probability for each category, the model version that made it, and which inputs pushed the model towards its answer.
              </Empty>
            ) : <Result key={result.prediction.id} result={result} categories={meta.categories} onChanged={() => pending.reload({ silent: true })} />}
          </Panel>

          <Panel title="Your form predictions awaiting an outcome" flush
            actions={<Link to="/app/history?labeled=false" className="link text-sm">All in history</Link>}>
            {pending.loading && !pending.data ? <Loading label="Loading your open predictions…" rows={2} className="px-5" />
              : pending.error ? <ErrorNote error={pending.error} onRetry={() => pending.reload()} className="m-4" />
                : pending.data?.items?.length ? (
                  <Table caption="Predictions awaiting their actual category">
                    <thead><tr><th className="th">Prediction</th><th className="th">Predicted</th><th className="th">Model</th><th className="th">Made</th></tr></thead>
                    <tbody>
                      {pending.data.items.map((it) => (
                        <tr key={it.id}>
                          <td className="td tabular text-muted">#{it.id}</td>
                          <td className="td font-medium">{it.predicted_category} <span className="font-normal text-muted">{pct(it.confidence, 0)}</span></td>
                          <td className="td"><VersionTag version={it.model_version} /></td>
                          <td className="td text-muted" title={dateTime(it.created_at)}>{timeAgo(it.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                ) : <p className="px-5 py-5 text-sm text-muted">Nothing waiting. Every prediction you made on this form has its actual category.</p>}
          </Panel>
        </div>
      </div>
    </>
  );
}
