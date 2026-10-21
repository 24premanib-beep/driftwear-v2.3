import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { wsUrl } from "../lib/api";
import { applyEvent, backoffDelay, REFRESH_EVENTS } from "../lib/realtime";
import { useAuth } from "./AuthContext";

/**
 * One WebSocket per signed-in tab.
 * Protocol: connect → send {"type":"auth","token"} → CONNECTED (status snapshot) → pipeline events.
 * Reconnects with exponential backoff; pings every 25 s so proxies keep the socket open.
 */
const RealtimeContext = createContext(null);
const MAX_EVENTS = 200;

export function RealtimeProvider({ children }) {
  const { token } = useAuth();
  const [connection, setConnection] = useState("offline");   // offline | connecting | open | reconnecting | unauthorized
  const [snapshot, setSnapshot] = useState(null);
  const [events, setEvents] = useState([]);
  const listeners = useRef(new Set());

  useEffect(() => {
    if (!token) {
      setConnection("offline");
      setSnapshot(null);
      setEvents([]);
      return undefined;
    }
    let ws = null;
    let attempt = 0;
    let retryTimer = null;
    let pingTimer = null;
    let stopped = false;

    const connect = () => {
      setConnection(attempt === 0 ? "connecting" : "reconnecting");
      try {
        ws = new WebSocket(wsUrl());
      } catch {
        retryTimer = setTimeout(connect, backoffDelay(attempt++));
        return;
      }
      ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
      ws.onmessage = (msg) => {
        let ev;
        try { ev = JSON.parse(msg.data); } catch { return; }
        if (ev.event === "CONNECTED") {
          attempt = 0;
          setConnection("open");
          setSnapshot(ev.data?.status || null);
          clearInterval(pingTimer);
          pingTimer = setInterval(() => ws?.readyState === 1 && ws.send('{"type":"ping"}'), 25000);
          return;
        }
        if (ev.event === "PONG") return;
        if (ev.event === "AUTH_FAILED") { stopped = true; setConnection("unauthorized"); return; }
        setSnapshot((s) => applyEvent(s, ev));
        if (ev.event !== "PERFORMANCE_UPDATED" || ev.data?.backfills?.length) {
          setEvents((prev) => [ev, ...prev].slice(0, MAX_EVENTS));
        }
        listeners.current.forEach((fn) => { try { fn(ev); } catch { /* a listener must not break the socket */ } });
      };
      ws.onclose = (e) => {
        clearInterval(pingTimer);
        if (stopped) return;
        if (e.code === 4401) { setConnection("unauthorized"); return; }
        setConnection("reconnecting");
        retryTimer = setTimeout(connect, backoffDelay(attempt++));
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      clearInterval(pingTimer);
      if (ws && ws.readyState === 0) {
        // still connecting (e.g. React StrictMode re-running effects): close once open instead of aborting,
        // which avoids a noisy "closed before the connection is established" browser warning
        ws.onmessage = null;
        ws.onclose = null;
        ws.onopen = () => ws.close(1000);
      } else if (ws && ws.readyState === 1) {
        ws.close(1000);
      }
    };
  }, [token]);

  const subscribe = useCallback((fn) => {
    listeners.current.add(fn);
    return () => listeners.current.delete(fn);
  }, []);

  const value = useMemo(() => ({ connection, snapshot, events, subscribe }), [connection, snapshot, events, subscribe]);
  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useRealtime() {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error("useRealtime must be used inside <RealtimeProvider>");
  return ctx;
}

/** Call `handler(event)` for every event (optionally only one stream). */
export function useRealtimeEvents(handler, stream = null) {
  const { subscribe } = useRealtime();
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((ev) => {
    if (!stream || ev.stream === stream) ref.current(ev);
  }), [subscribe, stream]);
}

/**
 * Re-fetch page data whenever the pipeline reports a change on this stream. Throttled, not debounced: while events
 * keep arriving (a streaming simulation) the page still refreshes about once per `delay`, instead of freezing until
 * the stream pauses.
 */
export function useLiveRefresh(refresh, stream, { delay = 900, events = REFRESH_EVENTS } = {}) {
  const timer = useRef(null);
  const ref = useRef(refresh);
  ref.current = refresh;
  useRealtimeEvents((ev) => {
    if (!events.has(ev.event) || timer.current) return;
    timer.current = setTimeout(() => { timer.current = null; ref.current(); }, delay);
  }, stream);
  useEffect(() => () => clearTimeout(timer.current), []);
}
