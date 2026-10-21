import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Bell, X } from "lucide-react";
import { SimulationChip, Tabs, ToneIcon } from "./ui";
import { useAuth } from "../context/AuthContext";
import { useRealtime, useRealtimeEvents } from "../context/RealtimeContext";
import { Overview } from "../lib/endpoints";
import { timeAgo } from "../lib/format";
import { buildNotifications, categorize, CATEGORIES, countUnread, eventKey, isToast, notificationLink, notificationTitle,
  toastContent } from "../lib/notifications";

const SEEN_KEY = "driftwear.notifications.seen";
function readSeen(userId) {
  try { return localStorage.getItem(`${SEEN_KEY}.${userId}`); } catch { return null; }
}

/**
 * Notification center: every item is a real backend event, from the WebSocket stream merged with
 * GET /api/events/recent (so the history survives a reload). The backend decides who receives what:
 * users get their own prediction events and model / status events; analysts and admins get everything.
 */
export function NotificationCenter() {
  const { user, isStaff } = useAuth();
  const { events } = useRealtime();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("ALL");
  const [initial, setInitial] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [lastSeen, setLastSeen] = useState(() => readSeen(user?.id));
  const panelRef = useRef(null);
  const buttonRef = useRef(null);

  useEffect(() => {
    if (!user) return undefined;
    let alive = true;
    setLastSeen(readSeen(user.id));
    Overview.recentEvents(100).then((list) => alive && setInitial(list || [])).catch((e) => alive && setLoadError(e));
    return () => { alive = false; };
  }, [user]);

  useEffect(() => {
    if (!open) return undefined;
    panelRef.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") { setOpen(false); buttonRef.current?.focus(); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const items = useMemo(() => buildNotifications(events, initial), [events, initial]);
  const unread = countUnread(items, lastSeen);
  const counts = useMemo(() => items.reduce((acc, e) => ({ ...acc, [categorize(e)]: (acc[categorize(e)] || 0) + 1 }), {}), [items]);
  const shown = filter === "ALL" ? items : items.filter((e) => categorize(e) === filter);

  const markRead = useCallback(() => {
    const ts = items[0]?.timestamp;
    if (!ts) return;
    setLastSeen(ts);
    try { localStorage.setItem(`${SEEN_KEY}.${user?.id}`, ts); } catch { /* storage unavailable */ }
  }, [items, user]);

  const tabs = [{ value: "ALL", label: "All", count: items.length },
    ...Object.entries(CATEGORIES).filter(([k]) => counts[k]).map(([k, c]) => ({ value: k, label: c.label, count: counts[k] }))];

  return (
    <>
      <button ref={buttonRef} type="button" className="btn btn-quiet relative px-2" onClick={() => setOpen(true)}
        aria-haspopup="dialog" aria-expanded={open} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
        <Bell className="h-5 w-5" aria-hidden="true" />
        {unread > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-plum px-1 text-[10.5px] font-semibold text-white tabular">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && createPortal(
        <div className="fixed inset-0 z-40 flex justify-end">
          <button type="button" className="absolute inset-0 cursor-default bg-navy/25 animate-fade-in" aria-label="Close notifications" tabIndex={-1} onClick={() => setOpen(false)} />
          <div ref={panelRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Notifications"
            className="relative flex h-full w-full max-w-md flex-col bg-surface shadow-dialog outline-none animate-slide-in">
            <div className="flex items-center justify-between gap-3 border-b border-seam px-5 py-3.5">
              <div>
                <h2 className="display text-xl text-navy">Notifications</h2>
                <p className="text-xs text-muted">{isStaff ? "Every pipeline event on both streams" : "Your predictions and model updates"}</p>
              </div>
              <div className="flex items-center gap-1">
                <button type="button" className="btn btn-quiet btn-sm" onClick={markRead} disabled={!unread}>Mark all read</button>
                <button type="button" className="btn btn-quiet px-1.5" onClick={() => setOpen(false)} aria-label="Close"><X className="h-5 w-5" aria-hidden="true" /></button>
              </div>
            </div>
            {tabs.length > 1 && <div className="overflow-x-auto border-b border-seam px-5 py-2.5"><Tabs tabs={tabs} value={filter} onChange={setFilter} label="Filter notifications" size="sm" /></div>}
            <ol className="flex-1 divide-y divide-seam overflow-y-auto">
              {shown.length ? shown.map((e) => {
                const fresh = !lastSeen || String(e.timestamp) > String(lastSeen);
                const cat = CATEGORIES[categorize(e)];
                return (
                  <li key={eventKey(e)}>
                    <Link to={notificationLink(e, { staff: isStaff })} onClick={() => setOpen(false)}
                      className={`flex gap-3 px-5 py-3 hover:bg-navy-50/70 ${fresh ? "bg-plum-50/60" : ""}`}>
                      <ToneIcon tone={cat?.tone} className="mt-0.5 h-4 w-4" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-sm font-medium text-fg">{notificationTitle(e)}</span>
                          <time className="shrink-0 text-xs text-muted" dateTime={e.timestamp}>{timeAgo(e.timestamp)}</time>
                        </div>
                        <p className="mt-0.5 text-sm text-muted">{e.message}</p>
                        {(e.stream === "simulation" || fresh) && (
                          <div className="mt-1.5 flex items-center gap-2">
                            {e.stream === "simulation" && <SimulationChip />}
                            {fresh && <span className="text-xs font-medium text-plum">New</span>}
                          </div>
                        )}
                      </div>
                    </Link>
                  </li>
                );
              }) : (
                <li className="px-5 py-10 text-sm text-muted">
                  {loadError ? `Earlier notifications could not be loaded (${loadError.message}). New ones still appear here as they happen.`
                    : "Nothing yet. Drift alerts, adaptations, new model versions and data events appear here as the pipeline reports them."}
                </li>
              )}
            </ol>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

/** Toasts for drift, adaptation, new versions, activation and failures, wherever the user is. */
export function ToastStack() {
  const { isStaff } = useAuth();
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id));
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
  }, []);

  useRealtimeEvents((ev) => {
    if (!isToast(ev)) return;
    const toast = { id: eventKey(ev), ev, ...toastContent(ev) };
    setToasts((t) => [toast, ...t.filter((x) => x.id !== toast.id)].slice(0, 3));
    clearTimeout(timers.current.get(toast.id));
    timers.current.set(toast.id, setTimeout(() => dismiss(toast.id), toast.category === "DRIFT" ? 16000 : 9000));
  });
  useEffect(() => () => timers.current.forEach((t) => clearTimeout(t)), []);

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-30 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => {
        const cat = CATEGORIES[t.category];
        return (
          <div key={t.id} role={t.category === "DRIFT" ? "alert" : "status"}
            className="pointer-events-auto overflow-hidden rounded-lg border border-seam bg-surface shadow-pop animate-toast-in">
            <div className="flex items-start gap-3 px-4 py-3">
              <ToneIcon tone={cat?.tone} className="mt-0.5 h-4 w-4" />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-fg">{t.title}</p>
                  <button type="button" className="-mr-1 rounded text-muted hover:text-fg" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
                {t.facts.length > 0 && (
                  <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
                    {t.facts.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="font-medium text-fg">{String(v)}</dd></div>)}
                  </dl>
                )}
                <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-muted">
                  <span>{timeAgo(t.timestamp)}</span>
                  <Link to={notificationLink(t.ev, { staff: isStaff })} className="link text-xs" onClick={() => dismiss(t.id)}>View details</Link>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
