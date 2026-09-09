import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useEffect,
  useState,
} from "react";
import {
  getLocalSession,
  signOutLocalSession,
} from "./auth/localSession";
import type { Permission, WorkspaceRole } from "./permissions";

export type User = {
  email?: string | null;
  id?: string | null;
  image?: string | null;
  name?: string | null;
  permissions?: Permission[];
  role?: WorkspaceRole;
  workspaceId?: string | null;
};

export type Session = { user: User } | null;

type SessionContextValue = {
  data: Session;
  invalidate: (reason?: string) => Promise<void>;
  status: "authenticated" | "loading" | "unauthenticated";
  update: () => Promise<Session>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

function LocalSessionAuthProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Session>(null);
  const [isReady, setIsReady] = useState(false);

  const sessionToContext = useCallback((session: Awaited<ReturnType<typeof getLocalSession>>) => {
    return session.authenticated && session.user
      ? {
          user: {
            email: session.user.email ?? null,
            id: session.user.userId,
            image: session.user.image ?? null,
            name: session.user.name ?? null,
          },
        }
      : null;
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const session = await getLocalSession();
      setData(sessionToContext(session));
    } catch {
      setData(null);
    } finally {
      setIsReady(true);
    }
  }, [sessionToContext]);

  useEffect(() => {
    void refreshSession();
    window.addEventListener("asianode-auth-change", refreshSession);
    return () => window.removeEventListener("asianode-auth-change", refreshSession);
  }, [refreshSession]);

  const update = useCallback(async () => {
    try {
      const session = await getLocalSession();
      const nextData = sessionToContext(session);
      setData(nextData);
      setIsReady(true);
      return nextData;
    } catch {
      setData(null);
      setIsReady(true);
      return null;
    }
  }, [sessionToContext]);

  const signOut = useCallback(async () => {
    try {
      await signOutLocalSession();
    } finally {
      setData(null);
      setIsReady(true);
      window.location.assign("/login?reason=signed_out");
    }
  }, []);

  const invalidate = useCallback(async (reason = "session_expired") => {
    setData(null);
    setIsReady(true);
    window.location.assign(`/login?reason=${encodeURIComponent(reason)}`);
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      data,
      invalidate,
      signOut,
      status: data ? "authenticated" : isReady ? "unauthenticated" : "loading",
      update,
    }),
    [data, invalidate, isReady, signOut, update]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  return <LocalSessionAuthProvider>{children}</LocalSessionAuthProvider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within AuthProvider");
  }
  return context;
}
