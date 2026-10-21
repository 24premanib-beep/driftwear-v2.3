import { Link } from "react-router-dom";
import { BrandMark } from "../components/Layout";
import { Disclosure, StateTrack, VersionTag } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { DriftIllustration } from "./Landing";

const INPUTS = ["Previous category", "Orders so far", "Days since last order", "Season", "Month", "Price", "Discount", "Style preference"];

const SECTIONS = [
  { id: "model", title: "What the prediction model does" },
  { id: "decay", title: "Why predictions become less accurate" },
  { id: "error", title: "What a prediction error is" },
  { id: "outcome", title: "Why the actual outcome must arrive first" },
  { id: "data-vs-concept", title: "Data drift and concept drift" },
  { id: "detectors", title: "DDM, ADWIN and Page-Hinkley" },
  { id: "states", title: "Stable, Warning and Drift" },
  { id: "window", title: "Change point and the post-change window" },
  { id: "versions", title: "New versions and how they are watched" },
  { id: "phases", title: "Before, during and after" },
  { id: "registry", title: "The registry and rollback" },
  { id: "simulation", title: "Why simulation stays separate" },
];

function Part({ n, id, title, children, figure }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-24 border-t border-seam py-10 first:border-t-0 first:pt-0">
      <div className={figure ? "grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : ""}>
        <div className="max-w-prose">
          <p className="text-sm tabular text-faint">{String(n).padStart(2, "0")}</p>
          <h2 id={`${id}-h`} className="display mt-1 text-2xl text-navy">{title}</h2>
          <div className="mt-3 space-y-3 text-md leading-relaxed text-fg/90">{children}</div>
        </div>
        {figure && <div className="min-w-0">{figure}</div>}
      </div>
    </section>
  );
}

function ErrorStrip() {
  const errors = [0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1];
  return (
    <figure className="rounded-lg border border-seam bg-surface p-5">
      <div className="flex flex-wrap gap-1" aria-hidden="true">
        {errors.map((e, i) => (
          <span key={i} className={`flex h-7 w-6 items-center justify-center rounded-sm text-xs font-semibold tabular ${e ? "bg-drift-soft text-drift-ink" : "bg-canvas text-muted"} ${i === 12 ? "ml-2" : ""}`}>{e}</span>
        ))}
      </div>
      <figcaption className="mt-3 text-sm text-muted">An error stream: 0 for a correct prediction, 1 for a wrong one. Wrong answers start to cluster on the right; that sustained rise is what a detector looks for. (Illustration.)</figcaption>
    </figure>
  );
}

function OutcomeTimeline() {
  const rows = [["Purchase arrives", "Validated and predicted: Tops, 55%. Stored with model v1.0.", "done"],
    ["Waiting", "Accuracy unknown. The detector is not touched.", "wait"],
    ["Actual category arrives", "The customer bought Bottoms.", "done"],
    ["Error computed", "Wrong: error = 1. The detector reads it and may change state.", "done"]];
  return (
    <figure className="rounded-lg border border-seam bg-surface p-5">
      <ol className="relative space-y-4 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-seam-strong">
        {rows.map(([t, d, s]) => (
          <li key={t} className="relative flex gap-3">
            <span className={`relative z-10 mt-1.5 h-[11px] w-[11px] shrink-0 rounded-full border-2 ${s === "wait" ? "border-dashed border-warning bg-surface" : "border-navy bg-navy"}`} aria-hidden="true" />
            <div><p className="text-sm font-semibold text-fg">{t}</p><p className="text-sm text-muted">{d}</p></div>
          </li>
        ))}
      </ol>
      <figcaption className="mt-3 text-xs text-muted">If the model was replaced while waiting, the purchase is re-scored by the current model for drift monitoring. The stored prediction is never rewritten.</figcaption>
    </figure>
  );
}

function WindowDiagram() {
  return (
    <figure className="rounded-lg border border-seam bg-surface p-4">
      <svg viewBox="0 0 520 170" className="h-auto w-full" role="img" aria-label="Diagram: the change point is estimated where the error rate jumps; only the records between the change point and the drift alarm are used to train the new model.">
        <rect x="250" y="20" width="150" height="110" fill="#2A4FC2" opacity="0.08" />
        <line x1="20" x2="500" y1="130" y2="130" stroke="#C9C3B8" />
        <path d="M20 112 L80 108 L140 114 L200 110 L250 112 L270 70 L320 56 L360 62 L400 50" fill="none" stroke="#172036" strokeWidth="2.5" strokeLinejoin="round" />
        <line x1="250" x2="250" y1="14" y2="130" stroke="#172036" strokeDasharray="4 4" />
        <line x1="400" x2="400" y1="14" y2="130" stroke="#B8261F" strokeWidth="2" />
        <g fontFamily="Archivo, system-ui, sans-serif" fontSize="12">
          <text x="256" y="148" fill="#2443A8">Post-change window: training data for the new model</text>
          <text x="180" y="12" fill="#172036">Change point</text>
          <text x="404" y="30" fill="#A32019">Drift confirmed</text>
          <text x="20" y="162" fill="#5F5C56">Older records are not used: they describe the old pattern</text>
        </g>
      </svg>
    </figure>
  );
}

export function HowItWorksContent() {
  const { user } = useAuth();
  return (
    <div className="grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav className="hidden lg:block" aria-label="On this page">
        <div className="sticky top-24">
          <p className="mb-2 text-sm font-medium text-fg">On this page</p>
          <ol className="space-y-1.5 text-sm">
            {SECTIONS.map((s, i) => <li key={s.id}><a href={`#${s.id}`} className="flex gap-2 text-muted hover:text-navy"><span className="w-5 tabular text-faint">{i + 1}</span>{s.title}</a></li>)}
          </ol>
        </div>
      </nav>
      <article className="min-w-0">
        <header className="mb-12 grid items-center gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div>
            <h1 className="display-tight text-3xl text-navy md:text-4xl">How DriftWear works</h1>
            <p className="mt-4 max-w-prose text-md leading-relaxed text-fg/85">
              Fashion prediction is the example. The real job is noticing when yesterday's model no longer describes today's customers, retraining it
              responsibly, and proving whether the retraining helped. Every question below is answered by a page in the product.
            </p>
          </div>
          <figure className="panel p-3"><DriftIllustration /><figcaption className="px-1 pt-1 text-xs text-muted">An illustration of the idea, not live data.</figcaption></figure>
        </header>

        <Part n={1} id="model" title="What the prediction model does" figure={
          <figure className="rounded-lg border border-seam bg-surface p-5">
            <ul className="flex flex-wrap gap-1.5">{INPUTS.map((x) => <li key={x} className="rounded-sm bg-canvas px-2 py-1 text-xs text-fg">{x}</li>)}</ul>
            <p className="my-3 text-center text-sm text-faint" aria-hidden="true">↓</p>
            <p className="rounded-md bg-navy px-3 py-2 text-center text-sm font-medium text-white">Random Forest (scikit-learn)</p>
            <p className="my-3 text-center text-sm text-faint" aria-hidden="true">↓</p>
            <p className="text-center text-sm text-fg">Next category, with a probability for each of the six</p>
            <figcaption className="mt-3 text-xs text-muted">Two derived features are added before the model: the price after discount, and the month on a circle so December sits next to January.</figcaption>
          </figure>}>
          <p>For each purchase, the active model predicts which of six categories (tops, bottoms, dresses, footwear, outerwear, accessories) the customer buys next. It uses eight fields of the purchase and the customer's history.</p>
          <p>Every prediction is stored with the model version that made it and a short explanation. “Why this prediction?” follows each tree's decisions and credits each move in probability to the input that caused it; the credits add up to the probability shown. They describe the model's reasoning, not why the customer behaves that way.</p>
          {user && <p><Link to="/app/predict" className="link">Make a prediction</Link></p>}
        </Part>

        <Part n={2} id="decay" title="Why predictions become less accurate">
          <p>A model learns the patterns in the data it was trained on. When trends move on (baggy trousers replace fitted ones, sneakers replace heels), the same kind of customer starts buying something else.</p>
          <p>Nothing crashes. The model keeps answering confidently, just wrongly more often. Without monitoring, nobody notices until the business does.</p>
        </Part>

        <Part n={3} id="error" title="What a prediction error is" figure={<ErrorStrip />}>
          <p>Once the actual category is known, each prediction becomes a single number: 0 if it was right, 1 if it was wrong. In arrival order, these numbers form the error stream.</p>
          <p>The error stream is the heartbeat of DriftWear. Accuracy is one minus its rolling average; drift detectors read it one value at a time.</p>
        </Part>

        <Part n={4} id="outcome" title="Why the actual outcome must arrive first" figure={<OutcomeTimeline />}>
          <p>At the moment of purchase nobody knows what the customer will buy next, so the accuracy of a fresh prediction is unknown. DriftWear shows it as awaiting its outcome and never pretends otherwise.</p>
          <p>The actual category can arrive minutes or days later, through the form, a live-event integration or a labeled CSV. Only then is the error computed and the detector updated.</p>
          {user && <p><Link to="/app/live" className="link">Follow a live event through these stages</Link></p>}
        </Part>

        <Part n={5} id="data-vs-concept" title="Data drift and concept drift">
          <div className="not-prose overflow-x-auto">
            <table className="min-w-full border-separate border-spacing-0 text-sm">
              <thead><tr><th className="th" /><th className="th">Data drift</th><th className="th">Concept drift</th></tr></thead>
              <tbody>
                {[["In one sentence", "The input data changed.", "The relationship between the input and the target changed."],
                  ["In symbols", <code key="a">P(X) changes</code>, <code key="b">P(y | X) changes</code>],
                  ["Example", "More festive-season purchases; higher average discounts.", "Casual customers at mid prices switch from tops to baggy bottoms."],
                  ["Needs actual outcomes", "No", "Yes"],
                  ["Measured by", "PSI and a KS test per feature, against a reference window", "DDM, ADWIN or Page-Hinkley on the error stream"],
                  ["Triggers retraining", "No. It is diagnostic only.", "Yes, when the primary detector confirms drift."]].map(([k, a, b]) => (
                  <tr key={k}><td className="td font-medium">{k}</td><td className="td">{a}</td><td className="td">{b}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>Inputs can shift while predictions stay right (seasons come and go), and customers can change what they buy while their inputs look the same. Retraining on input shifts alone would chase seasonality; the error stream is what decides.</p>
        </Part>

        <Part n={6} id="detectors" title="DDM, ADWIN and Page-Hinkley">
          <dl className="grid gap-4 sm:grid-cols-3">
            {[["DDM", "Drift Detection Method", "Tracks the error rate and its spread, remembers the best level seen, and warns at 2 standard deviations above it, drift at 3. Built in, always available."],
              ["ADWIN", "Adaptive windowing", "Keeps a window of recent errors whose size adapts; when an older and a newer part differ significantly, it drops the old part and signals drift."],
              ["Page-Hinkley", "Page-Hinkley test", "Adds up how far each error sits above the running average. Small bumps cancel out; a lasting rise pushes the sum past a threshold."]].map(([n, full, text]) => (
              <div key={n} className="rounded-lg border border-seam bg-surface p-4"><dt className="font-semibold text-fg">{n}<span className="block text-xs font-normal text-muted">{full}</span></dt><dd className="mt-2 text-sm text-muted">{text}</dd></div>
            ))}
          </dl>
          <p>One detector is primary: only it can trigger adaptation. The others run as shadows on the same errors, for comparison. ADWIN and Page-Hinkley come from the River library; on a server without River, only DDM is offered and no shadow is shown as running.</p>
        </Part>

        <Part n={7} id="states" title="Stable, Warning and Drift">
          <div className="rounded-lg border border-seam bg-surface p-4"><StateTrack status="WARNING" label="Example: the detector in its warning zone" /></div>
          <ul className="space-y-2">
            <li><strong className="font-semibold">Stable:</strong> errors are at their normal level for the active model.</li>
            <li><strong className="font-semibold">Warning:</strong> errors are rising. The detector watches closely; nothing changes and nothing is retrained.</li>
            <li><strong className="font-semibold">Drift:</strong> the rise is statistically significant and sustained. The relationship has changed, so the model adapts.</li>
          </ul>
          <p>The states are not a progress bar: after a warning the detector often returns to stable.</p>
        </Part>

        <Part n={8} id="window" title="Change point and the post-change window" figure={<WindowDiagram />}>
          <p>Drift is confirmed some time after it began. DriftWear estimates the change point (where the error rate jumps the most) and trains the new model only on records after it, at least 15 and at most 300.</p>
          <p>Training on the whole history would average the old and new patterns; training on the post-change window learns the new one.</p>
        </Part>

        <Part n={9} id="versions" title="New versions and how they are watched">
          <p className="flex flex-wrap items-center gap-2">A drift adaptation creates a major version: <VersionTag version="v1.0" /> → <VersionTag version="v2.0" active />.</p>
          <p>As more records of the new pattern arrive, scheduled refreshes after about 25, 75 and 150 records create minor versions such as v2.1, v2.2 and v2.3. Administrators can also retrain on request.</p>
          <p>After a drift adaptation the detector is reset and calibrated on the new model's out-of-fold errors, so it judges the new model by its own normal level. If retraining fails, the previous model stays active and the failure is recorded.</p>
        </Part>

        <Part n={10} id="phases" title="Before, during and after">
          <ul className="space-y-2">
            <li><strong className="font-semibold">Before drift:</strong> up to 50 outcomes before the change point, the old model still working.</li>
            <li><strong className="font-semibold">During drift:</strong> from the change point to the alarm, the old model failing.</li>
            <li><strong className="font-semibold">After adaptation:</strong> up to 50 outcomes after the new model took over.</li>
          </ul>
          <p>Accuracy, precision, recall, F1 and error rate are measured in each phase from real outcomes. Until enough outcomes arrive after the adaptation, the verdict reads “Measuring recovery”, never an estimate.</p>
        </Part>

        <Part n={11} id="registry" title="The registry and rollback">
          <p>Every version is kept with its checksummed model file, the reason it exists, its training window, its validation scores (out-of-fold, on its own window) and its live scores (on real outcomes). The two kinds of score are never mixed.</p>
          <p>If a new version performs badly, an administrator can roll back to an earlier one with a written reason. The server verifies the file's SHA-256 checksum before loading it, records who, when and why, cancels refreshes of the replaced model and notifies everyone. Nothing is deleted.</p>
        </Part>

        <Part n={12} id="simulation" title="Why simulation stays separate">
          <p>Real drift cannot be ordered on demand, so the simulation replays a synthetic dataset with three fashion-trend periods and lets you change the trend. It runs on its own stream, with its own models, detector and history.</p>
          <p>Simulated records are labelled everywhere they appear and never counted in live figures; otherwise a demonstration would distort the evidence about real customers.</p>
          {user && <p><Link to="/app/simulation" className="link">Run the demonstration</Link></p>}
        </Part>

        <section className="border-t border-seam py-10" aria-labelledby="faq-h">
          <h2 id="faq-h" className="display text-2xl text-navy">Questions people ask</h2>
          <div className="mt-4 space-y-2">
            {[["Why not simply retrain every week?", "Scheduled retraining is late when trends change fast and wasteful when nothing changed. Detecting drift retrains when the evidence says the old model stopped working."],
              ["How do you avoid retraining on random noise?", "The detector needs a significant, sustained rise (DDM: three standard deviations), it is calibrated on the model's own out-of-fold errors after every retrain, and a warning on its own never retrains."],
              ["How do you know adaptation helped?", "Metrics are measured on real outcomes before drift, during drift and after adaptation, and the adaptive model is compared with v1.0 frozen at the start on the same records."],
              ["What if the new model is worse?", "Every version stays in the registry. An administrator compares versions and rolls back; the detector restarts for the restored model."]].map(([q, a]) => (
              <Disclosure key={q} summary={q}><p className="text-sm text-fg/85">{a}</p></Disclosure>
            ))}
          </div>
        </section>

        <div className="flex flex-wrap gap-3 border-t border-seam pt-8">
          <Link to={user ? "/app/simulation" : "/login"} className="btn btn-primary">{user ? "Watch drift happen in the simulation" : "Sign in to try it"}</Link>
          {user && <Link to="/app" className="btn btn-secondary">Open the dashboard</Link>}
        </div>
      </article>
    </div>
  );
}

/** Public version: no sign-in needed and no private data. */
export default function HowItWorksPublic() {
  const { user } = useAuth();
  return (
    <div className="min-h-screen bg-canvas">
      <header className="mx-auto flex max-w-content items-center justify-between px-5 py-5 lg:px-8">
        <Link to="/" aria-label="DriftWear home"><BrandMark tone="dark" /></Link>
        <Link to={user ? "/app" : "/login"} className="btn btn-primary">{user ? "Open DriftWear" : "Sign in"}</Link>
      </header>
      <main className="mx-auto max-w-content px-5 pb-16 pt-6 lg:px-8"><HowItWorksContent /></main>
    </div>
  );
}
