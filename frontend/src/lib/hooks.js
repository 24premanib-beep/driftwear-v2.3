import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

/** Load data with loading/error state. reload({silent:true}) keeps the current data on screen. */
export function useApi(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const seq = useRef(0);
  const applied = useRef(0);

  // A response is applied unless a NEWER request has already been applied: data never goes backwards, and a
  // stream of overlapping refreshes (a busy pipeline) still shows each result instead of waiting for a quiet moment.
  const reload = useCallback(async ({ silent = false } = {}) => {
    const id = ++seq.current;
    if (!silent) setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await loaderRef.current();
      if (id > applied.current) {
        applied.current = id;
        setState((s) => ({ data, error: null, loading: id === seq.current ? false : s.loading }));
      }
      return data;
    } catch (error) {
      if (id > applied.current && id === seq.current) setState((s) => ({ ...s, error, loading: false }));
      return undefined;
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);

  const setData = useCallback((d) => setState((s) => ({ ...s, data: typeof d === "function" ? d(s.data) : d })), []);
  return { ...state, reload, setData };
}

/** ?stream=simulation in the URL selects the simulation stream; anything else is live. */
export function useStreamParam(allowSimulation = true) {
  const [params, setParams] = useSearchParams();
  const stream = allowSimulation && params.get("stream") === "simulation" ? "simulation" : "live";
  const setStream = useCallback((value) => {
    const next = new URLSearchParams(params);
    if (value === "simulation") next.set("stream", "simulation");
    else next.delete("stream");
    setParams(next, { replace: true });
  }, [params, setParams]);
  return [stream, setStream];
}

/** Run an async action with busy/error/result state (buttons, forms). */
export function useAction(action) {
  const [state, setState] = useState({ busy: false, error: null, result: null });
  const actionRef = useRef(action);
  actionRef.current = action;
  const run = useCallback(async (...args) => {
    setState({ busy: true, error: null, result: null });
    try {
      const result = await actionRef.current(...args);
      setState({ busy: false, error: null, result });
      return result;
    } catch (error) {
      setState({ busy: false, error, result: null });
      return undefined;
    }
  }, []);
  const reset = useCallback(() => setState({ busy: false, error: null, result: null }), []);
  return { ...state, run, reset };
}

/** One URL search parameter as state (tabs, selected record), so views can be linked and survive a reload. */
export function useQueryParam(key, fallback = "") {
  const [params, setParams] = useSearchParams();
  const value = params.get(key) ?? fallback;
  const set = useCallback((next) => {
    const q = new URLSearchParams(params);
    if (next === null || next === undefined || next === "" || next === fallback) q.delete(key); else q.set(key, String(next));
    setParams(q, { replace: true });
  }, [params, setParams, key, fallback]);
  return [value, set];
}
