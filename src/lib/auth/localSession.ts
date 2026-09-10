import { apiFetch } from "../backend/directClient";

export type LocalSessionUser = {
  userId: string;
  email?: string | null;
  name?: string | null;
  image?: string | null;
};

export type LocalSessionResponse = {
  authenticated: boolean;
  user: LocalSessionUser | null;
};

export class LocalAuthRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "LocalAuthRequestError";
    this.status = status;
  }
}

let csrfToken: string | null = null;
let csrfRefreshAt = 0;
let csrfRefreshPromise: Promise<string> | null = null;

const CSRF_TOKEN_MAX_AGE_MS = 60 * 60 * 1000;
const CSRF_REFRESH_MARGIN_MS = 5 * 60 * 1000;

async function responsePayload(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json().catch(() => null)) as {
      authenticated?: boolean;
      csrfToken?: string;
      message?: string;
      detail?: string | { msg?: string }[] | { message?: string };
      user?: LocalSessionUser | null;
    } | null;
  }
  return null;
}

function errorMessage(payload: Awaited<ReturnType<typeof responsePayload>>) {
  if (Array.isArray(payload?.detail)) {
    return payload.detail
      .map((item) => item.msg)
      .filter(Boolean)
      .join(", ");
  }
  if (payload?.detail && typeof payload.detail === "object") {
    return payload.detail.message ?? "Authentication request failed.";
  }
  return payload?.message ?? payload?.detail ?? "Authentication request failed.";
}

async function getCsrfToken(force = false) {
  if (!force && csrfToken && Date.now() < csrfRefreshAt) {
    return csrfToken;
  }

  if (csrfRefreshPromise) {
    return csrfRefreshPromise;
  }

  const refreshPromise = (async () => {
    const response = await apiFetch("/api/v1/auth/csrf", {
      credentials: "include",
    });
    const payload = await responsePayload(response);
    if (!response.ok || !payload?.csrfToken) {
      throw new LocalAuthRequestError(response.status, errorMessage(payload));
    }

    csrfToken = payload.csrfToken;
    csrfRefreshAt = Date.now() + CSRF_TOKEN_MAX_AGE_MS - CSRF_REFRESH_MARGIN_MS;
    return csrfToken;
  })();
  csrfRefreshPromise = refreshPromise;

  try {
    return await refreshPromise;
  } finally {
    if (csrfRefreshPromise === refreshPromise) {
      csrfRefreshPromise = null;
    }
  }
}

export function invalidateLocalCsrfToken() {
  csrfToken = null;
  csrfRefreshAt = 0;
}

export async function getLocalCsrfToken(force = false) {
  return getCsrfToken(force);
}

export async function getLocalSession(): Promise<LocalSessionResponse> {
  const response = await apiFetch("/api/v1/auth/session", {
    credentials: "include",
  });
  const payload = await responsePayload(response);
  if (!response.ok || !payload || typeof payload.authenticated !== "boolean") {
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  return {
    authenticated: payload.authenticated,
    user: payload.user ?? null,
  };
}

export async function signInWithLocalSession(
  email: string,
  password: string
): Promise<LocalSessionResponse> {
  const token = await getCsrfToken();
  const response = await apiFetch("/api/v1/auth/login", {
    body: JSON.stringify({ email, password }),
    credentials: "include",
    headers: {
      "content-type": "application/json",
      "X-CSRF-Token": token,
    },
    method: "POST",
  });
  const payload = await responsePayload(response);
  if (!response.ok && response.status === 403) {
    // A stale token must not make the user retry valid credentials forever.
    invalidateLocalCsrfToken();
  }
  if (!response.ok || !payload || typeof payload.authenticated !== "boolean") {
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  window.dispatchEvent(new Event("asianode-auth-change"));
  return {
    authenticated: payload.authenticated,
    user: payload.user ?? null,
  };
}

export async function signOutLocalSession() {
  const token = await getCsrfToken();
  const response = await apiFetch("/api/v1/auth/logout", {
    credentials: "include",
    headers: { "X-CSRF-Token": token },
    method: "POST",
  });
  const payload = await responsePayload(response);
  if (!response.ok) {
    if (response.status === 403) {
      invalidateLocalCsrfToken();
    }
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  invalidateLocalCsrfToken();
  window.dispatchEvent(new Event("asianode-auth-change"));
}

export async function activateLocalInvitation(
  token: string,
  password: string,
  name?: string
): Promise<LocalSessionResponse> {
  const csrf = await getCsrfToken();
  const response = await apiFetch("/api/v1/auth/activate", {
    body: JSON.stringify({ token, password, name: name || undefined }),
    credentials: "include",
    headers: {
      "content-type": "application/json",
      "X-CSRF-Token": csrf,
    },
    method: "POST",
  });
  const payload = await responsePayload(response);
  if (!response.ok) {
    if (response.status === 403) {
      invalidateLocalCsrfToken();
    }
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }
  if (!payload || typeof payload.authenticated !== "boolean") {
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  window.dispatchEvent(new Event("asianode-auth-change"));
  return {
    authenticated: payload.authenticated,
    user: payload.user ?? null,
  };
}

export async function changeLocalPassword(
  currentPassword: string,
  newPassword: string
): Promise<LocalSessionResponse> {
  const csrf = await getCsrfToken();
  const response = await apiFetch("/api/v1/auth/change-password", {
    body: JSON.stringify({ currentPassword, newPassword }),
    credentials: "include",
    headers: {
      "content-type": "application/json",
      "X-CSRF-Token": csrf,
    },
    method: "POST",
  });
  const payload = await responsePayload(response);
  if (!response.ok) {
    if (response.status === 403) {
      invalidateLocalCsrfToken();
    }
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }
  if (!payload || typeof payload.authenticated !== "boolean") {
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  window.dispatchEvent(new Event("asianode-auth-change"));
  return {
    authenticated: payload.authenticated,
    user: payload.user ?? null,
  };
}
