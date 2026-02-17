import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  AuthContextType,
  MFAChallenge,
  MFAMethod,
  SessionInfo,
  SSOProvider,
  User,
  AuthApiError,
} from "@/types/auth";
import { isMFAChallenge } from "@/types/auth";

// ─── Constants ───────────────────────────────────────────────────────

const API_BASE = "/api/v1/auth";
const SESSION_CHECK_INTERVAL_MS = 60_000;
const IDLE_WARNING_BEFORE_EXPIRY_MS = 5 * 60 * 1000;

// ─── Context ─────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextType | null>(null);

// ─── Hook ────────────────────────────────────────────────────────────

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within <AuthProvider>");
  }
  return ctx;
}

// ─── Helpers ─────────────────────────────────────────────────────────

async function authRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    credentials: "include",
    ...options,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }))) as AuthApiError;
    const msg = body.errors[0]?.message ?? "Authentication failed";
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Provider ────────────────────────────────────────────────────────

interface AuthProviderProps {
  children: ReactNode;
  onIdleWarning?: () => void;
}

export function AuthProvider({ children, onIdleWarning }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mfaChallenge, setMfaChallenge] = useState<MFAChallenge | null>(null);
  const expiresAtRef = useRef<string | null>(null);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Set session from API response ──────────────────────────────────
  const applySession = useCallback((session: SessionInfo) => {
    setUser(session.user);
    expiresAtRef.current = session.expires_at;
    setError(null);
    setMfaChallenge(null);
  }, []);

  // ── Schedule idle warning ──────────────────────────────────────────
  const scheduleIdleWarning = useCallback(() => {
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    const expiresAt = expiresAtRef.current;
    if (!expiresAt || !onIdleWarning) return;
    const msUntilExpiry = new Date(expiresAt).getTime() - Date.now();
    const warningMs = msUntilExpiry - IDLE_WARNING_BEFORE_EXPIRY_MS;
    if (warningMs > 0) {
      idleTimerRef.current = setTimeout(onIdleWarning, warningMs);
    }
  }, [onIdleWarning]);

  // ── Fetch current session ──────────────────────────────────────────
  const fetchMe = useCallback(async () => {
    try {
      const res = await authRequest<{ data: SessionInfo }>("/me");
      applySession(res.data);
      scheduleIdleWarning();
    } catch {
      setUser(null);
      expiresAtRef.current = null;
    }
  }, [applySession, scheduleIdleWarning]);

  // ── Initial session check + polling ────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function check() {
      setLoading(true);
      await fetchMe();
      if (!cancelled) setLoading(false);
    }

    void check();

    const interval = setInterval(() => {
      void fetchMe();
    }, SESSION_CHECK_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    };
  }, [fetchMe]);

  // ── Login with email/password ──────────────────────────────────────
  const login = useCallback(
    async (email: string, password: string, rememberMe?: boolean) => {
      setError(null);
      setLoading(true);
      try {
        const res = await authRequest<{
          data: SessionInfo | MFAChallenge;
        }>("/login", {
          method: "POST",
          body: JSON.stringify({ email, password, remember_me: rememberMe }),
        });
        if (isMFAChallenge(res.data)) {
          setMfaChallenge(res.data);
        } else {
          applySession(res.data);
          scheduleIdleWarning();
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Login failed");
      } finally {
        setLoading(false);
      }
    },
    [applySession, scheduleIdleWarning],
  );

  // ── Login via SSO redirect ─────────────────────────────────────────
  const loginSSO = useCallback(
    async (provider: SSOProvider, idpHint?: string) => {
      setError(null);
      try {
        const res = await authRequest<{ data: { redirect_url: string } }>(
          "/sso/initiate",
          {
            method: "POST",
            body: JSON.stringify({ provider, idp_hint: idpHint }),
          },
        );
        window.location.href = res.data.redirect_url;
      } catch (err) {
        setError(err instanceof Error ? err.message : "SSO login failed");
      }
    },
    [],
  );

  // ── Logout ─────────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    try {
      await authRequest("/logout", { method: "POST" });
    } catch {
      // best-effort
    } finally {
      setUser(null);
      setMfaChallenge(null);
      expiresAtRef.current = null;
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    }
  }, []);

  // ── Refresh session ────────────────────────────────────────────────
  const refreshSession = useCallback(async () => {
    try {
      const res = await authRequest<{ data: SessionInfo }>("/refresh", {
        method: "POST",
      });
      applySession(res.data);
      scheduleIdleWarning();
    } catch (err) {
      setUser(null);
      expiresAtRef.current = null;
      setError(err instanceof Error ? err.message : "Session refresh failed");
    }
  }, [applySession, scheduleIdleWarning]);

  // ── Permission / role checks ───────────────────────────────────────
  const hasPermission = useCallback(
    (permission: string) => user?.permissions.includes(permission) ?? false,
    [user],
  );

  const hasRole = useCallback(
    (role: string) => user?.roles.includes(role) ?? false,
    [user],
  );

  // ── MFA verification ──────────────────────────────────────────────
  const verifyMFA = useCallback(
    async (code: string, method: MFAMethod, rememberDevice?: boolean) => {
      if (!mfaChallenge) {
        setError("No MFA challenge in progress");
        return;
      }
      setError(null);
      setLoading(true);
      try {
        const res = await authRequest<{ data: SessionInfo }>("/mfa/verify", {
          method: "POST",
          body: JSON.stringify({
            mfa_token: mfaChallenge.mfa_token,
            code,
            method,
            remember_device: rememberDevice,
          }),
        });
        applySession(res.data);
        scheduleIdleWarning();
      } catch (err) {
        setError(err instanceof Error ? err.message : "MFA verification failed");
      } finally {
        setLoading(false);
      }
    },
    [mfaChallenge, applySession, scheduleIdleWarning],
  );

  const clearMFAChallenge = useCallback(() => {
    setMfaChallenge(null);
    setError(null);
  }, []);

  // ── Context value ──────────────────────────────────────────────────
  const value: AuthContextType = {
    user,
    loading,
    error,
    mfaChallenge,
    login,
    loginSSO,
    logout,
    refreshSession,
    hasPermission,
    hasRole,
    verifyMFA,
    clearMFAChallenge,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ─── Protected Route Wrapper ─────────────────────────────────────────

interface RequireAuthProps {
  children: ReactNode;
  permission?: string;
  role?: string;
  fallback?: ReactNode;
}

export function RequireAuth({
  children,
  permission,
  role,
  fallback,
}: RequireAuthProps) {
  const { user, loading, hasPermission, hasRole } = useAuth();

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return fallback ?? null;
  }

  if (permission && !hasPermission(permission)) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2">
        <p className="text-red-400">Insufficient permissions</p>
        <p className="text-sm text-gray-500">
          Required: <code className="text-gray-400">{permission}</code>
        </p>
      </div>
    );
  }

  if (role && !hasRole(role)) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2">
        <p className="text-red-400">Insufficient role</p>
        <p className="text-sm text-gray-500">
          Required: <code className="text-gray-400">{role}</code>
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
