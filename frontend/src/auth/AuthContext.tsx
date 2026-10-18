import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, setCsrfToken, setUnauthenticatedHandler } from "../api/client";
import { api } from "../api/endpoints";
import { clearReferenceCache } from "../api/reference";
import type { LoginRequest, LoginResult, Me, Role } from "../api/types";

type SignOutReason = "signed_out" | "expired" | null;

interface AuthApi {
  me: Me | null;
  checking: boolean;
  /** Increments on every sign-in/out so screens remount and drop form state. */
  sessionKey: number;
  signOutReason: SignOutReason;
  login: (req: LoginRequest) => Promise<LoginResult>;
  verifyOtp: (challengeId: string, otp: string) => Promise<LoginResult>;
  logout: () => Promise<void>;
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthApi | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMeState] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);
  const [sessionKey, setSessionKey] = useState(0);
  const [signOutReason, setSignOutReason] = useState<SignOutReason>(null);

  const signedIn = useRef(false);

  const setMe = useCallback((m: Me | null) => {
    signedIn.current = m !== null;
    clearReferenceCache();
    setCsrfToken(m?.csrf_token ?? null);
    setMeState(m);
    setSessionKey((k) => k + 1);
  }, []);

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      if (!signedIn.current) return;
      setSignOutReason("expired");
      setMe(null);
    });
    api.me().then(
      (m) => {
        setMe(m);
        setChecking(false);
      },
      () => {
        setChecking(false);
      },
    );
    return () => setUnauthenticatedHandler(null);
  }, [setMe]);

  // Idle / absolute expiry: drop the in-memory session when the server's clock says it ended.
  useEffect(() => {
    if (!me) return;
    const ends = Math.min(Date.parse(me.session.idle_expires_at), Date.parse(me.session.absolute_expires_at));
    if (Number.isNaN(ends)) return;
    const timer = window.setTimeout(() => {
      // Re-check: the server may have extended the idle window on activity.
      api.me().then(
        (m) => {
          setCsrfToken(m.csrf_token);
          setMeState(m);
        },
        (e: unknown) => {
        if (!(e instanceof ApiError) || e.status === 401) {
          setSignOutReason("expired");
          setMe(null);
        }
        },
      );
    }, Math.max(ends - Date.now(), 1000));
    return () => window.clearTimeout(timer);
  }, [me, setMe]);

  const complete = useCallback(
    (r: LoginResult) => {
      if (r.status === "SIGNED_IN" && r.me) {
        setSignOutReason(null);
        setMe(r.me);
      }
      return r;
    },
    [setMe],
  );

  const value = useMemo<AuthApi>(
    () => ({
      me,
      checking,
      sessionKey,
      signOutReason,
      login: async (req) => complete(await api.login(req)),
      verifyOtp: async (challenge_id, otp) => complete(await api.otp({ challenge_id, otp })),
      logout: async () => {
        try {
          await api.logout();
        } catch {
          // Session may already be gone; clear locally regardless.
        }
        setSignOutReason("signed_out");
        setMe(null);
      },
      hasRole: (...roles) => !!me && roles.some((r) => me.roles.includes(r)),
    }),
    [me, checking, sessionKey, signOutReason, complete, setMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider missing");
  return ctx;
}
