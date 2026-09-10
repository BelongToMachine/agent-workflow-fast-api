/* eslint-disable react/only-export-components */

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { fastApiWorkspaceId } from "../backend/mode";
import {
  type BackendRequestError,
  setBackendAuthorizationFailureHandler,
} from "../backend/request";
import { useBackendQuery } from "../backend/reactQuery";
import type { Permission, WorkspaceRole } from "../permissions";
import { useSession } from "../auth";

export type WorkspaceMembership = {
  membershipId: string;
  overrides: { effect: "grant" | "deny"; permission: string }[];
  permissions: Permission[];
  role: WorkspaceRole;
  status: string;
  workspaceId: string;
  workspaceName: string;
};

export type CurrentUserResponse = {
  accessState: "ready" | "pending_workspace";
  email: string | null;
  image: string | null;
  isDevelopment: boolean;
  isGuest: boolean;
  memberships: WorkspaceMembership[];
  name: string | null;
  status: "active" | "suspended";
  userId: string;
};

export type ApplicationAuthStatus =
  | "loading"
  | "unauthenticated"
  | "initializing"
  | "pending_workspace"
  | "authenticated"
  | "suspended"
  | "error";

type ApplicationAuthContextValue = {
  activeMembership: WorkspaceMembership | null;
  currentUser: CurrentUserResponse | null;
  error: BackendRequestError | null;
  hasPermission: (permission: Permission) => boolean;
  refreshCurrentUser: () => Promise<void>;
  signOut: () => Promise<void>;
  status: ApplicationAuthStatus;
};

const ApplicationAuthContext =
  createContext<ApplicationAuthContextValue | null>(null);

const CURRENT_USER_REQUEST_TIMEOUT_MS = 10_000;

function errorCode(error: BackendRequestError | null) {
  return error?.payload?.code ?? null;
}

function shouldRetryCurrentUser(
  failureCount: number,
  error: unknown
) {
  if (failureCount >= 1) {
    return false;
  }

  if (error && typeof error === "object" && "status" in error) {
    const status = error.status;
    return typeof status === "number" ? status >= 500 : true;
  }

  return true;
}

export function ApplicationAuthProvider({ children }: { children: ReactNode }) {
  const {
    data: session,
    invalidate,
    signOut: signOutSession,
    status: sessionStatus,
  } = useSession();
  const queryClient = useQueryClient();
  const identity = session?.user?.id ?? "anonymous";
  const previousIdentity = useRef<string | null>(null);
  const [blockedStatus, setBlockedStatus] = useState<
    "pending_workspace" | "suspended" | null
  >(null);

  const currentUserQuery = useBackendQuery<CurrentUserResponse>({
    enabled: sessionStatus === "authenticated",
    path: "/api/v1/me",
    queryKey: ["backend", "user", identity, "current-user"],
    requestOptions: { timeoutMs: CURRENT_USER_REQUEST_TIMEOUT_MS },
    retry: shouldRetryCurrentUser,
    retryDelay: 500,
  });
  const { refetch: refetchCurrentUser } = currentUserQuery;

  const currentUser = useMemo<CurrentUserResponse | null>(() => {
    if (!session?.user) {
      return null;
    }

    return currentUserQuery.data ?? null;
  }, [currentUserQuery.data, session]);

  const activeMembership = useMemo(
    () => {
      if (!currentUser) {
        return null;
      }

      // The MVP has one configured workspace. Do not silently select an
      // unexpected membership when the backend configuration is inconsistent.
      return (
        currentUser.memberships.find(
          (membership) => membership.workspaceId === fastApiWorkspaceId
        ) ?? null
      );
    },
    [currentUser]
  );

  const backendError =
    (currentUserQuery.error as BackendRequestError | null);

  useEffect(() => {
    if (previousIdentity.current && previousIdentity.current !== identity) {
      queryClient.removeQueries({ queryKey: ["backend"] });
    }
    previousIdentity.current = identity;
    setBlockedStatus(null);
  }, [identity, queryClient]);

  useEffect(() => {
    if (!currentUser) {
      return;
    }
    setBlockedStatus(null);
  }, [currentUser]);

  useEffect(() => {
    setBackendAuthorizationFailureHandler((error) => {
      const code = errorCode(error);
      if (error.status === 401) {
        void invalidate("session_expired");
        return;
      }
      if (code === "user:suspended") {
        setBlockedStatus("suspended");
      } else if (code === "workspace:membership_required") {
        setBlockedStatus("pending_workspace");
      }
    });

    return () => setBackendAuthorizationFailureHandler(null);
  }, [invalidate]);

  const status = useMemo<ApplicationAuthStatus>(() => {
    if (sessionStatus === "loading") {
      return "loading";
    }
    if (sessionStatus === "unauthenticated") {
      return "unauthenticated";
    }
    if (blockedStatus) {
      return blockedStatus;
    }
    const code = errorCode(backendError);
    if (code === "user:suspended") {
      return "suspended";
    }
    if (code === "workspace:membership_required") {
      return "pending_workspace";
    }
    if (backendError) {
      return backendError.status === 401 ? "unauthenticated" : "error";
    }
    if (currentUserQuery.isLoading || !currentUser) {
      return "initializing";
    }
    if (currentUser.status === "suspended") {
      return "suspended";
    }
    return currentUser.accessState === "pending_workspace"
      ? "pending_workspace"
      : "authenticated";
  }, [
    backendError,
    blockedStatus,
    currentUser,
    currentUserQuery.isLoading,
    sessionStatus,
  ]);

  const refreshCurrentUser = useCallback(async () => {
    await refetchCurrentUser({ throwOnError: false });
  }, [refetchCurrentUser]);

  const signOut = useCallback(async () => {
    queryClient.removeQueries({ queryKey: ["backend"] });
    await signOutSession();
  }, [queryClient, signOutSession]);

  const hasPermission = useCallback(
    (permission: Permission) =>
      activeMembership?.permissions.includes(permission) ?? false,
    [activeMembership]
  );

  const value = useMemo<ApplicationAuthContextValue>(
    () => ({
      activeMembership,
      currentUser,
      error: backendError,
      hasPermission,
      refreshCurrentUser,
      signOut,
      status,
    }),
    [
      activeMembership,
      backendError,
      currentUser,
      hasPermission,
      refreshCurrentUser,
      signOut,
      status,
    ]
  );

  return (
    <ApplicationAuthContext.Provider value={value}>
      {children}
    </ApplicationAuthContext.Provider>
  );
}

export function useApplicationAuth() {
  const context = useContext(ApplicationAuthContext);
  if (!context) {
    throw new Error("useApplicationAuth must be used within ApplicationAuthProvider");
  }
  return context;
}
