import { Link } from "react-router-dom";
import { BrandMark } from "../components/Layout";
import { useAuth } from "../context/AuthContext";

/** Illustration of the idea (not data): errors stay low, rise after a trend change, and fall after adaptation. */
export function DriftIllustration({ className = "" }) {
  return (
    <svg viewBox="0 0 640 280" className={`h-auto w-full ${className}`} role="img"
      aria-label="Illustration: the error rate stays low, rises when a fashion trend changes, the detector raises a warning and then confirms drift, and the error falls again after the model adapts. A frozen model's error stays high.">
      <rect x="0" y="0" width="640" height="280" fill="#FBFAF8" />
      {[50, 100, 150, 200].map((y) => <line key={y} x1="48" x2="620" y1={y} y2={y} stroke="#E6E2DA" />)}
      <line x1="48" x2="620" y1="236" y2="236" stroke="#C9C3B8" />
      <rect x="262" y="24" width="96" height="212" fill="#B8261F" opacity="0.06" />
      <rect x="358" y="24" width="262" height="212" fill="#2A4FC2" opacity="0.05" />
      <line x1="262" x2="262" y1="24" y2="236" stroke="#172036" strokeDasharray="4 4" />
      <line x1="318" x2="318" y1="24" y2="236" stroke="#C88A12" strokeDasharray="2 4" strokeWidth="1.5" />
      <line x1="358" x2="358" y1="24" y2="236" stroke="#B8261F" strokeWidth="2" />
      <path d="M48 196 C88 192 128 200 168 194 C208 188 238 198 262 192 C280 180 296 150 318 112 C334 86 346 72 358 66 C372 84 386 140 404 176 C424 196 470 188 520 192 C560 194 590 188 620 192"
        fill="none" stroke="#172036" strokeWidth="3" strokeLinecap="round" />
      <path d="M48 196 C88 192 128 200 168 194 C208 188 238 198 262 192 C292 150 330 96 372 76 C430 60 520 58 620 54"
        fill="none" stroke="#A39E94" strokeWidth="2" strokeDasharray="6 5" />
      <g fontFamily="Archivo, system-ui, sans-serif" fontSize="12" fill="#5F5C56">
        <text x="16" y="54">high</text><text x="16" y="200">low</text>
        <text x="48" y="258">Labeled purchases over time</text>
        <text x="266" y="40" fill="#172036">Trend changes</text>
        <text x="324" y="226" fill="#85590A">Warning</text>
        <text x="364" y="40" fill="#A32019" fontWeight="600">Drift confirmed</text>
        <text x="472" y="214" fill="#2443A8">Adapted model</text>
        <text x="520" y="46">Frozen model</text>
        <text x="16" y="20" fontWeight="600" fill="#172036">Prediction error</text>
      </g>
    </svg>
  );
}

const STEPS = [
  ["Predict", "Each purchase gets a predicted next category from the active model, stored with that model's version."],
  ["Score", "When the real category arrives, the prediction becomes an error of 0 or 1."],
  ["Detect", "A detector reads the stream of errors and moves from stable to warning to drift."],
  ["Adapt", "On confirmed drift, a new model is trained on the data after the change."],
  ["Prove", "Accuracy before, during and after drift shows whether the adaptation worked."],
];

export default function Landing() {
  const { user } = useAuth();
  return (
    <div className="min-h-screen bg-canvas">
      <header className="mx-auto flex max-w-content items-center justify-between px-5 py-5 lg:px-8">
        <Link to="/" aria-label="DriftWear home"><BrandMark tone="dark" /></Link>
        <nav className="flex items-center gap-2" aria-label="Public">
          <Link to="/how-it-works" className="btn btn-quiet">How it works</Link>
          {user ? <Link to="/app" className="btn btn-primary">Open DriftWear</Link> : <Link to="/login" className="btn btn-primary">Sign in</Link>}
        </nav>
      </header>
      <main>
        <section className="mx-auto grid max-w-content items-center gap-10 px-5 pb-16 pt-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:px-8">
          <div>
            <h1 className="display-tight text-[2.75rem] leading-[2.9rem] text-navy md:text-[4rem] md:leading-[4rem]">Fashion moves on. DriftWear notices when the model doesn't.</h1>
            <p className="mt-6 max-w-prose text-md leading-relaxed text-fg/85">
              DriftWear predicts the next clothing category a customer will buy, scores every prediction once the real purchase is known,
              detects when the relationship between purchases and categories has changed, and retrains the model on the new pattern.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to={user ? "/app" : "/login"} className="btn btn-primary px-5 py-2.5 text-base">{user ? "Open the dashboard" : "Sign in"}</Link>
              <Link to="/how-it-works" className="btn btn-secondary px-5 py-2.5 text-base">How DriftWear works</Link>
            </div>
          </div>
          <figure className="panel overflow-hidden p-4">
            <DriftIllustration />
            <figcaption className="mt-2 text-xs text-muted">An illustration of the idea, not live data.</figcaption>
          </figure>
        </section>
        <section className="border-t border-seam bg-surface">
          <div className="mx-auto max-w-content px-5 py-14 lg:px-8">
            <h2 className="display text-2xl text-navy">What happens to every purchase</h2>
            <ol className="mt-8 grid gap-8 md:grid-cols-5">
              {STEPS.map(([title, text], i) => (
                <li key={title} className="border-t-2 border-navy pt-3">
                  <div className="text-sm tabular text-faint">{i + 1}</div>
                  <div className="mt-1 text-md font-semibold text-fg">{title}</div>
                  <p className="mt-1 text-sm leading-relaxed text-muted">{text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>
        <footer className="mx-auto max-w-content px-5 py-8 text-sm text-muted lg:px-8">
          Live customer data and the simulation are kept on separate streams. Simulated records never appear in live figures.
        </footer>
      </main>
    </div>
  );
}
