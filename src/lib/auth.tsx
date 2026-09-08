import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useEffect,
  useState,
} from "react";
import { useLogto } from "@logto/react";
import {
  clearStoredDirectToken,
  getStoredDirectToken,
} from "./backend/directClient";
import {
  getLogtoEndSessionUri,
  isLocalSessionAuthMode,
  isLogtoAuthMode,
  logtoAppId,
} from "./auth/logtoConfig";
import { clearLogtoBrowserStorage } from "./auth/logtoStorage";
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

let registeredSignOut: (() => Promise<void>) | null = null;

function registerSignOut(handler: (() => Promise<void>) | null) {
  registeredSignOut = handler;
}

function decodeDevelopmentUser(accessToken: string): User {
  const encodedPayload = accessToken.split(".")[1];
  if (!encodedPayload) {
    return { id: "authenticated-user" };
  }

  try {
    const normalized = encodedPayload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(window.atob(padded)) as {
      email?: string | null;
      permissions?: Permission[];
      role?: WorkspaceRole;
      subject?: string;
      workspaceId?: string | null;
    };
    return {
      email: payload.email ?? null,
      id: payload.subject ?? "authenticated-user",
      permissions: payload.permissions,
      role: payload.role,
      workspaceId: payload.workspaceId,
    };
  } catch {
    return { id: "authenticated-user" };
  }
}

function DevelopmentAuthProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Session>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const handler = async () => {
      clearStoredDirectToken();
      window.location.assign("/dev/oidc");
    };
    registerSignOut(handler);
    return () => registerSignOut(null);
  }, []);

  const refreshSession = useCallback(() => {
    const token = getStoredDirectToken();
    setData(token ? { user: decodeDevelopmentUser(token.accessToken) } : null);
    setIsReady(true);
  }, []);

  useEffect(() => {
    refreshSession();
    window.addEventListener("asianode-auth-change", refreshSession);
    window.addEventListener("storage", refreshSession);
    const sessionCheck = window.setInterval(refreshSession, 30_000);
    return () => {
      window.removeEventListener("asianode-auth-change", refreshSession);
      window.removeEventListener("storage", refreshSession);
      window.clearInterval(sessionCheck);
    };
  }, [refreshSession]);

  const update = useCallback(async () => {
    refreshSession();
    const token = getStoredDirectToken();
    return token ? { user: decodeDevelopmentUser(token.accessToken) } : null;
  }, [refreshSession]);
  const signOut = useCallback(async () => clearStoredDirectToken(), []);
  const invalidate = useCallback(async () => {
    clearStoredDirectToken();
    window.location.assign("/dev/oidc");
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

function LogtoAuthProvider({ children }: { children: ReactNode }) {
  const {
    getIdToken,
    getIdTokenClaims,
    isAuthenticated,
    isLoading,
    clearAllTokens,
    signOut: logtoSignOut,
  } = useLogto();
  const [data, setData] = useState<Session>(null);
  const [isReady, setIsReady] = useState(false);

  const readSession = useCallback(async (): Promise<Session> => {
    const idToken = await getIdToken();
    if (!idToken) {
      return null;
    }

    try {
      const claims = await getIdTokenClaims();
      if (!claims?.sub) {
        return null;
      }

      return {
        user: {
          email: claims.email ?? null,
          id: claims.sub,
          image: claims.picture ?? null,
          name: claims.name ?? claims.username ?? null,
        },
      };
    } catch {
      return null;
    }
  }, [getIdToken, getIdTokenClaims]);

  useEffect(() => {
    let active = true;
    setIsReady(false);
    void readSession().then((session) => {
      if (!active) {
        return;
      }
      setData(session);
      setIsReady(true);
    });

    return () => {
      active = false;
    };
  }, [isAuthenticated, readSession]);

  const update = useCallback(async () => {
    const session = await readSession();
    setData(session);
    setIsReady(true);
    return session;
  }, [readSession]);

  const signOut = useCallback(async () => {
    const postLogoutRedirectUri = `${window.location.origin}/`;
    const fallbackLogtoLogoutUri = getLogtoEndSessionUri(
      postLogoutRedirectUri
    );
    window.setTimeout(() => {
      void (async () => {
        await clearAllTokens();
        clearLogtoBrowserStorage();
        if (fallbackLogtoLogoutUri) {
          window.location.assign(fallbackLogtoLogoutUri);
          return;
        }
        window.location.assign(postLogoutRedirectUri);
      })();
    }, 2500);

    try {
      await logtoSignOut(postLogoutRedirectUri);
    } finally {
      await clearAllTokens();
      clearLogtoBrowserStorage();
    }
  }, [clearAllTokens, logtoSignOut]);

  const invalidate = useCallback(
    async (reason = "session_expired") => {
      await clearAllTokens();
      clearLogtoBrowserStorage();
      setData(null);
      setIsReady(true);
      window.location.assign(`/login?reason=${encodeURIComponent(reason)}`);
    },
    [clearAllTokens]
  );

  useEffect(() => {
    registerSignOut(signOut);
    return () => registerSignOut(null);
  }, [signOut]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (
        !event.key ||
        !logtoAppId ||
        !event.key.startsWith(`logto:${logtoAppId}`)
      ) {
        return;
      }

      void update();
    };

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [update]);

  const value = useMemo<SessionContextValue>(
    () => ({
      data,
      invalidate,
      signOut,
      status:
        !isReady || (isLoading && !isAuthenticated)
          ? "loading"
          : data
            ? "authenticated"
            : "unauthenticated",
      update,
    }),
    [data, invalidate, isAuthenticated, isLoading, isReady, signOut, update]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

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
  if (isLocalSessionAuthMode) {
    return <LocalSessionAuthProvider>{children}</LocalSessionAuthProvider>;
  }

  if (isLogtoAuthMode) {
    return <LogtoAuthProvider>{children}</LogtoAuthProvider>;
  }

  return <DevelopmentAuthProvider>{children}</DevelopmentAuthProvider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within AuthProvider");
  }
  return context;
}

export async function signOut() {
  if (registeredSignOut) {
    await registeredSignOut();
    return;
  }

  clearStoredDirectToken();
  if (isLogtoAuthMode) {
    clearLogtoBrowserStorage();
    window.location.assign("/login?reason=signed_out");
    return;
  }

  if (isLocalSessionAuthMode) {
    window.location.assign("/login?reason=signed_out");
    return;
  }

  window.location.assign("/dev/oidc");
}
