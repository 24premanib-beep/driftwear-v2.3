import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { configureApi } from "../lib/api";
import { Auth } from "../lib/endpoints";

/**
 * Session state. The JWT comes from POST /api/auth/login and is kept in localStorage (no refresh tokens; see the
 * README's known limitations). The server is the authority: any 401 ends the session with the server's own reason
 * (expired, revoked by sign-out elsewhere, account disabled), which the sign-in page then shows.
 */
const AuthContext = createContext(null);
const TOKEN_KEY = "driftwear.token";

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function writeToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable (private mode): keep the session in memory only */ }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(readToken);
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(readToken()));
  const [bootError, setBootError] = useState(null);       // server unreachable while restoring a session
  const [notice, setNotice] = useState(null);             // why the last session ended
  const tokenRef = useRef(token);
  const verified = useRef(null);                          // token whose user we already have (just signed in)

  const clear = useCallback((message = null) => {
    tokenRef.current = null;
    verified.current = null;
    writeToken(null);
    setToken(null);
    setUser(null);
    setNotice(message);
  }, []);

  useEffect(() => {
    configureApi({
      getToken: () => tokenRef.current,
      onUnauthorized: (err) => clear(err?.message || "Your session has ended. Please sign in again."),
    });
  }, [clear]);

  const restore = useCallback(() => {
    if (!tokenRef.current) { setChecking(false); return () => {}; }
    if (verified.current === tokenRef.current) { setChecking(false); return () => {}; }
    let alive = true;
    setChecking(true);
    setBootError(null);
    Auth.me()
      .then((u) => { if (alive) { verified.current = tokenRef.current; setUser(u); } })
      .catch((err) => {
        if (!alive) return;
        if (err?.status === 401) clear(err.message);       // expired / revoked / disabled: the server says which
        else setBootError(err);                            // offline or server error: keep the token, offer a retry
      })
      .finally(() => alive && setChecking(false));
    return () => { alive = false; };
  }, [clear]);

  useEffect(() => restore(), [token, restore]);

  const login = useCallback(async (email, password) => {
    const data = await Auth.login(email, password);
    tokenRef.current = data.access_token;
    verified.current = data.access_token;
    writeToken(data.access_token);
    setUser(data.user);
    setNotice(null);
    setBootError(null);
    setToken(data.access_token);
    return data.user;
  }, []);

  const register = useCallback(async (name, email, password) => {
    await Auth.register(name, email, password);
    return login(email, password);
  }, [login]);

  const logout = useCallback(async () => {
    try { await Auth.logout(); } catch { /* sign out locally regardless */ }
    clear("You signed out. Signing out ends your session on every device.");
  }, [clear]);

  const value = useMemo(() => ({
    token, user, checking, notice, bootError, login, register, logout, retry: restore,
    role: user?.role || null,
    isStaff: user?.role === "admin" || user?.role === "analyst",
    isAdmin: user?.role === "admin",
  }), [token, user, checking, notice, bootError, login, register, logout, restore]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
