import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Lock, WifiOff } from "lucide-react";
import Layout, { BrandMark } from "./components/Layout";
import { ErrorNote, Loading } from "./components/ui";
import { useAuth } from "./context/AuthContext";
import { canAccess } from "./lib/nav";
import Adaptation from "./pages/Adaptation";
import AuditLogs from "./pages/AuditLogs";
import { Login, Register } from "./pages/AuthPages";
import Dashboard from "./pages/Dashboard";
import DataManagement from "./pages/DataManagement";
import DataValidation from "./pages/DataValidation";
import DriftAnalysis from "./pages/DriftAnalysis";
import DriftMonitoring from "./pages/DriftMonitoring";
import DriftPerformance from "./pages/DriftPerformance";
import History from "./pages/History";
import HowItWorksPublic, { HowItWorksContent } from "./pages/HowItWorks";
import Landing from "./pages/Landing";
import LiveData from "./pages/LiveData";
import Predict from "./pages/Predict";
import Registry from "./pages/Registry";
import Simulation from "./pages/Simulation";
import SystemMonitoring from "./pages/SystemMonitoring";
import UsersPage from "./pages/Users";

function SessionGate({ children }) {
  const { user, checking, bootError, retry } = useAuth();
  const location = useLocation();
  if (checking) {
    return <div className="mx-auto max-w-md px-6 pt-24"><BrandMark tone="dark" /><Loading label="Checking your session…" rows={0} /></div>;
  }
  if (bootError) {
    return (
      <div className="mx-auto max-w-md px-6 pt-24">
        <BrandMark tone="dark" />
        <div className="mt-6 flex items-center gap-2 text-md font-semibold text-fg"><WifiOff className="h-5 w-5 text-muted" aria-hidden="true" />DriftWear is not reachable</div>
        <p className="mt-1 text-sm text-muted">Your session is kept. Check your connection or the API server, then try again.</p>
        <ErrorNote error={bootError} onRetry={retry} className="mt-4" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return children;
}

/** Route-level role check. The API enforces the same rule, so this only avoids showing pages that would fail. */
function Allow({ access, children }) {
  const { role } = useAuth();
  return canAccess(access, role) ? children : <Forbidden access={access} />;
}

function Forbidden({ access }) {
  return (
    <div className="max-w-xl py-10">
      <Lock className="h-6 w-6 text-faint" aria-hidden="true" />
      <h1 className="display mt-3 text-2xl text-navy">This page is for {access === "admin" ? "administrators" : "analysts and administrators"}</h1>
      <p className="mt-2 text-md text-muted">
        {access === "admin"
          ? "Audit logs, user management and model rollback are limited to administrators."
          : "Drift investigation, model registry, data operations, simulation and system monitoring need the analyst role. An administrator can change your role on the Users page."}
      </p>
      <Link to="/app" className="btn btn-primary mt-6">Back to the dashboard</Link>
    </div>
  );
}

function NotFound({ inApp = false }) {
  return (
    <div className={inApp ? "max-w-xl py-10" : "mx-auto max-w-xl px-6 pt-24"}>
      {!inApp && <BrandMark tone="dark" />}
      <h1 className="display mt-6 text-2xl text-navy">Page not found</h1>
      <p className="mt-2 text-md text-muted">The address may be mistyped, or the page has moved.</p>
      <Link to={inApp ? "/app" : "/"} className="btn btn-primary mt-6">{inApp ? "Go to the dashboard" : "Go to the home page"}</Link>
    </div>
  );
}

/** /app/performance was merged into "Adaptation & performance"; old links keep working. */
function PerformanceRedirect() {
  const { search } = useLocation();
  const q = new URLSearchParams(search);
  q.set("tab", "performance");
  return <Navigate to={`/app/adaptation?${q}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/how-it-works" element={<HowItWorksPublic />} />
      <Route path="/app" element={<SessionGate><Layout /></SessionGate>}>
        <Route index element={<Dashboard />} />
        <Route path="predict" element={<Predict />} />
        <Route path="history" element={<History />} />
        <Route path="live" element={<LiveData />} />
        <Route path="drift" element={<Allow access="staff"><DriftMonitoring /></Allow>} />
        <Route path="drift-analysis" element={<Allow access="staff"><DriftAnalysis /></Allow>} />
        <Route path="adaptation" element={<Allow access="staff"><Adaptation /></Allow>} />
        <Route path="performance" element={<Allow access="staff"><PerformanceRedirect /></Allow>} />
        <Route path="drift-performance" element={<Allow access="staff"><DriftPerformance /></Allow>} />
        <Route path="models" element={<Allow access="staff"><Registry /></Allow>} />
        <Route path="data" element={<Allow access="staff"><DataManagement /></Allow>} />
        <Route path="validation" element={<Allow access="staff"><DataValidation /></Allow>} />
        <Route path="simulation" element={<Allow access="staff"><Simulation /></Allow>} />
        <Route path="system" element={<Allow access="staff"><SystemMonitoring /></Allow>} />
        <Route path="audit" element={<Allow access="admin"><AuditLogs /></Allow>} />
        <Route path="users" element={<Allow access="admin"><UsersPage /></Allow>} />
        <Route path="how-it-works" element={<HowItWorksContent />} />
        <Route path="*" element={<NotFound inApp />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
