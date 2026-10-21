import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { Activity, BookOpen, ChartNoAxesCombined, ChevronDown, DatabaseZap, FlaskConical, Gauge, History, LayoutDashboard, LogOut,
  Menu, RadioTower, RefreshCcw, ScrollText, ShieldCheck, Sparkle, Split, Tags, Users, X } from "lucide-react";
import { NotificationCenter, ToastStack } from "./NotificationCenter";
import { StateTrack, VersionTag } from "./ui";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { pct } from "../lib/format";
import { currentPage, navFor } from "../lib/nav";

const ICONS = { Activity, BookOpen, ChartNoAxesCombined, DatabaseZap, FlaskConical, Gauge, History, LayoutDashboard, RadioTower, RefreshCcw,
  ScrollText, ShieldCheck, Sparkle, Split, Tags, Users };

export function BrandMark({ className = "", tone = "light" }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden="true">
        <path d="M10 3h17a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H10L2 16z" fill={tone === "light" ? "#FBFAF8" : "#172036"} />
        <circle cx="9.5" cy="16" r="2.2" fill={tone === "light" ? "#172036" : "#EFEDE9"} />
        <path d="M14.5 21h4.5l3-10h4.5" fill="none" stroke={tone === "light" ? "#7A3366" : "#D9A6C8"} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className={`display text-[1.35rem] leading-none tracking-tight ${tone === "light" ? "text-white" : "text-navy"}`}>DriftWear</span>
    </span>
  );
}

function Sidebar({ onNavigate }) {
  const { user } = useAuth();
  const groups = navFor(user?.role);
  return (
    <nav className="flex h-full flex-col bg-navy text-navy-200" aria-label="Main">
      <div className="px-5 pb-3 pt-4">
        <Link to="/app" onClick={onNavigate} className="inline-block rounded focus-visible:outline-plum-300"><BrandMark /></Link>
      </div>
      <div className="flex-1 overflow-y-auto px-3 pb-3 scrollbar-thin">
        {groups.map((g) => (
          <div key={g.label} className="mt-3 first:mt-0">
            <div className="px-3 pb-1 text-xs text-navy-300">{g.label}</div>
            <ul className="space-y-px">
              {g.items.map(({ to, label, icon, end }) => {
                const Icon = ICONS[icon];
                return (
                  <li key={to}>
                    <NavLink to={to} end={end} onClick={onNavigate}
                      className={({ isActive }) => `relative flex items-center gap-2.5 rounded-md px-3 py-[6px] text-sm transition-colors focus-visible:outline-plum-300 ${isActive
                        ? "bg-white/[.09] font-medium text-white before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-plum-300"
                        : "hover:bg-white/[.05] hover:text-white"}`}>
                      {Icon && <Icon className="h-4 w-4 shrink-0 opacity-90" aria-hidden="true" />}{label}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-white/10 px-5 py-3 text-xs text-navy-300">
        Signed in as <span className="font-medium text-white">{user?.name}</span>
        <span className="ml-1.5 rounded bg-white/10 px-1.5 py-px capitalize text-navy-100">{user?.role}</span>
      </div>
    </nav>
  );
}

function ConnectionStatus() {
  const { connection } = useRealtime();
  const map = {
    open: ["bg-stable", "Live updates on"],
    connecting: ["bg-warning", "Connecting…"],
    reconnecting: ["bg-warning animate-pulse", "Reconnecting…"],
    unauthorized: ["bg-drift", "Updates stopped: session ended"],
    offline: ["bg-faint", "Updates offline"],
  };
  const [dot, label] = map[connection] || map.offline;
  return (
    <span className="hidden items-center gap-2 text-sm text-muted md:inline-flex" role="status" aria-live="polite"
      title="Real-time updates over WebSocket: drift alerts, adaptations and new model versions">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />{label}
    </span>
  );
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    const onClick = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onClick); };
  }, [open]);
  const initials = (user?.name || "?").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="relative" ref={ref}>
      <button type="button" className="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 hover:bg-navy-50" aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-navy text-xs font-semibold text-white" aria-hidden="true">{initials}</span>
        <span className="hidden text-left text-sm leading-tight sm:block">
          <span className="block font-medium text-fg">{user?.name}</span>
          <span className="block text-xs capitalize text-muted">{user?.role}</span>
        </span>
        <ChevronDown className="h-4 w-4 text-muted" aria-hidden="true" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-2 w-64 overflow-hidden rounded-lg border border-seam bg-surface shadow-pop animate-fade-in">
          <div className="border-b border-seam px-4 py-3 text-sm">
            <div className="font-medium text-fg">{user?.name}</div>
            <div className="truncate text-muted">{user?.email}</div>
            <div className="mt-1.5 text-xs text-muted">Role: <span className="font-medium capitalize text-fg">{user?.role}</span></div>
          </div>
          <Link role="menuitem" to="/app/how-it-works" className="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-navy-50" onClick={() => setOpen(false)}>
            <BookOpen className="h-4 w-4 text-muted" aria-hidden="true" />How DriftWear works
          </Link>
          <button role="menuitem" type="button" className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-navy-50" onClick={logout}>
            <LogOut className="h-4 w-4 text-muted" aria-hidden="true" />Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * The live answer to the central question, on every page: the detector state of the stream being viewed,
 * the active model and the recent accuracy. Comes from the WebSocket snapshot; nothing here is computed locally.
 */
function StateRail() {
  const { snapshot, connection } = useRealtime();
  const { isStaff } = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const stream = isStaff && (params.get("stream") === "simulation" || location.pathname === "/app/simulation") ? "simulation" : "live";
  const s = snapshot?.[stream];
  return (
    <div className={`border-b border-seam ${stream === "simulation" ? "toile bg-surface" : "bg-surface"}`} role="region" aria-label="Detector status">
      <div className="mx-auto flex max-w-content flex-wrap items-center gap-x-6 gap-y-2 px-5 py-2.5 lg:px-8">
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-navy">
          {stream === "simulation" ? <><FlaskConical className="h-4 w-4" aria-hidden="true" />Simulation stream</>
            : <><span className="h-1.5 w-1.5 rounded-full bg-navy" aria-hidden="true" />Live stream</>}
        </span>
        {s ? (
          <>
            <StateTrack status={s.status} adapting={Boolean(s.adapting)} adaptingTo={s.adapting_to} label={`${stream} detector state`} />
            <dl className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-muted lg:ml-auto">
              <div className="flex items-center gap-2"><dt>Active model</dt><dd><VersionTag version={s.model_version} active /></dd></div>
              <div className="flex items-center gap-1.5"><dt>Detector</dt><dd className="font-medium text-fg">{s.detector}</dd></div>
              <div className="flex items-center gap-1.5"><dt>Recent accuracy</dt>
                <dd className="font-medium tabular text-fg">{s.rolling_accuracy === null || s.rolling_accuracy === undefined ? "N/A" : pct(s.rolling_accuracy)}</dd></div>
            </dl>
          </>
        ) : (
          <span className="text-sm text-muted">
            {connection === "open" ? "Waiting for the detector status…" : "Detector status appears when real-time updates are connected."}
          </span>
        )}
      </div>
    </div>
  );
}

export default function Layout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const page = currentPage(location.pathname);
  useEffect(() => {
    document.title = page ? `${page.item.label} · DriftWear` : "DriftWear";
  }, [page]);

  return (
    <div className="min-h-screen lg:pl-[248px]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop">
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] lg:block"><Sidebar /></aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" className="absolute inset-0 bg-navy/45" aria-label="Close menu" onClick={() => setOpen(false)} />
          <aside className="relative h-full w-[264px] animate-slide-in"><Sidebar onNavigate={() => setOpen(false)} /></aside>
        </div>
      )}
      <header className="sticky top-0 z-20 border-b border-seam bg-canvas/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-content items-center gap-3 px-5 py-2.5 lg:px-8">
          <button type="button" className="btn btn-quiet -ml-2 px-2 lg:hidden" onClick={() => setOpen((o) => !o)} aria-label={open ? "Close menu" : "Open menu"}>
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <nav aria-label="Breadcrumb" className="min-w-0 truncate text-sm">
            {page ? (
              <ol className="flex items-center gap-1.5">
                <li className="hidden text-muted sm:block">{page.group}</li>
                <li className="hidden text-seam-strong sm:block" aria-hidden="true">/</li>
                <li className="truncate font-medium text-fg" aria-current="page">{page.item.label}</li>
              </ol>
            ) : <span className="font-medium text-fg">DriftWear</span>}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <ConnectionStatus />
            <NotificationCenter />
            <AccountMenu />
          </div>
        </div>
      </header>
      <StateRail />
      <main id="main" className="mx-auto max-w-content px-5 pb-16 pt-8 lg:px-8" tabIndex={-1}>
        <Outlet />
      </main>
      <ToastStack />
    </div>
  );
}
