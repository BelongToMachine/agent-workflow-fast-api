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

export type LocalPasswordResetRequestResponse = {
  requested: boolean;
  resetUrl?: string | null;
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

async function responsePayload(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json().catch(() => null)) as {
      authenticated?: boolean;
      csrfToken?: string;
      message?: string;
      requested?: boolean;
      resetUrl?: string | null;
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
  if (!force && csrfToken) {
    return csrfToken;
  }

  const response = await apiFetch("/api/v1/auth/csrf", {
    credentials: "include",
  });
  const payload = await responsePayload(response);
  if (!response.ok || !payload?.csrfToken) {
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  csrfToken = payload.csrfToken;
  return csrfToken;
}

export async function getLocalCsrfToken() {
  return getCsrfToken();
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
    csrfToken = null;
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
    csrfToken = response.status === 403 ? null : csrfToken;
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  csrfToken = null;
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
      csrfToken = null;
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
      csrfToken = null;
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

export async function requestLocalPasswordReset(
  email: string
): Promise<LocalPasswordResetRequestResponse> {
  const csrf = await getCsrfToken();
  const response = await apiFetch("/api/v1/auth/password-reset/request", {
    body: JSON.stringify({ email }),
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
      csrfToken = null;
    }
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }
  if (!payload || typeof payload.requested !== "boolean") {
    throw new LocalAuthRequestError(response.status, errorMessage(payload));
  }

  return {
    requested: payload.requested,
    resetUrl: payload.resetUrl ?? null,
  };
}

export async function resetLocalPassword(
  token: string,
  newPassword: string
): Promise<LocalSessionResponse> {
  const csrf = await getCsrfToken();
  const response = await apiFetch("/api/v1/auth/password-reset/confirm", {
    body: JSON.stringify({ token, newPassword }),
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
      csrfToken = null;
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
