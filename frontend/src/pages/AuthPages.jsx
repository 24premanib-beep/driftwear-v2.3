import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/Layout";
import { ErrorNote, Field, Notice, Spinner, StateTrack } from "../components/ui";
import { useAuth } from "../context/AuthContext";

function AuthShell({ title, lede, children, footer }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-navy px-12 py-10 text-navy-200 lg:flex">
        <Link to="/" className="self-start rounded focus-visible:outline-plum-300"><BrandMark /></Link>
        <div className="max-w-md">
          <p className="display text-3xl text-white">Has the way customers buy changed?</p>
          <p className="mt-4 text-md leading-relaxed text-navy-200">
            DriftWear predicts the next fashion category a customer will buy, scores every prediction once the real purchase is known,
            and retrains the model when the relationship between purchases and categories shifts.
          </p>
          <div className="mt-8 rounded-lg bg-surface/95 px-4 py-3.5" aria-hidden="true">
            <p className="mb-2 text-xs text-muted">What the detector reports</p>
            <StateTrack status="WARNING" label="Example detector state" />
          </div>
        </div>
        <p className="text-sm text-navy-300">New here? <Link to="/how-it-works" className="font-medium text-white underline decoration-white/30 underline-offset-4 hover:decoration-white">Read how DriftWear works</Link></p>
      </aside>
      <main className="flex items-center justify-center bg-canvas px-5 py-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="mb-10 inline-block lg:hidden"><BrandMark tone="dark" /></Link>
          <h1 className="display text-2xl text-navy">{title}</h1>
          {lede && <p className="mt-1.5 text-sm text-muted">{lede}</p>}
          <div className="mt-7">{children}</div>
          <p className="mt-8 text-sm text-muted">{footer}</p>
        </div>
      </main>
    </div>
  );
}

function errorTitle(err) {
  if (!err) return undefined;
  if (err.status === 0) return "The server could not be reached";
  if (err.status === 429) return "Too many attempts";
  if (err.status === 401) return "Sign-in failed";
  return undefined;
}

export function Login() {
  const { login, user, notice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={location.state?.from || "/app"} replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(form.email.trim(), form.password);
      navigate(location.state?.from || "/app", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Sign in" lede="Use the account your administrator created, or one you registered."
      footer={<>No account yet? <Link to="/register" className="link">Create one</Link>. New accounts start with the user role.</>}>
      {notice && !error && <Notice tone="warning" className="mb-5">{notice}</Notice>}
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Email" htmlFor="email">
          <input id="email" type="email" autoComplete="email" required className="input" value={form.email} autoFocus
            onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Password" htmlFor="password">
          <input id="password" type="password" autoComplete="current-password" required className="input" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        <ErrorNote error={error} title={errorTitle(error)} />
        <button type="submit" className="btn btn-primary w-full py-2.5" disabled={busy || !form.email || !form.password}>
          {busy && <Spinner />}{busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </AuthShell>
  );
}

export function Register() {
  const { register, user } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/app" replace />;

  const fields = error?.fieldErrors || {};
  const weak = form.password && (form.password.length < 8 || !/[a-zA-Z]/.test(form.password) || !/\d/.test(form.password));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(form.name.trim(), form.email.trim(), form.password);
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Create an account" lede="Accounts can make predictions, send live events and follow their own results."
      footer={<>Already registered? <Link to="/login" className="link">Sign in</Link>. An administrator can grant analyst access for drift investigation.</>}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Name" htmlFor="name" error={fields.name}>
          <input id="name" autoComplete="name" required className="input" value={form.name} autoFocus
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Email" htmlFor="email" error={fields.email}>
          <input id="email" type="email" autoComplete="email" required className="input" value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Password" htmlFor="password" error={fields.password}
          hint={weak ? "Use at least 8 characters with letters and numbers." : "At least 8 characters, with letters and numbers."}>
          <input id="password" type="password" autoComplete="new-password" required className={`input ${weak ? "input-invalid" : ""}`} value={form.password}
            aria-invalid={weak || undefined} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        <ErrorNote error={error && !Object.keys(fields).length ? error : null} title={errorTitle(error)} />
        <button type="submit" className="btn btn-primary w-full py-2.5" disabled={busy || !form.name || !form.email || weak || !form.password}>
          {busy && <Spinner />}{busy ? "Creating your account…" : "Create account"}
        </button>
      </form>
    </AuthShell>
  );
}
