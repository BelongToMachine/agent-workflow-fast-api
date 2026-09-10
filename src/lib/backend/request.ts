import { apiFetch } from "./directClient";

export type BackendErrorPayload = {
  cause?: string;
  code?: string;
  detail?:
    | string
    | { msg?: string }[]
    | { code?: string; message?: string };
  message?: string;
  requestId?: string;
};

export class BackendRequestError extends Error {
  readonly payload: BackendErrorPayload | null;
  readonly status: number;
  readonly requestId?: string;

  constructor(status: number, payload: BackendErrorPayload | null) {
    const detail = Array.isArray(payload?.detail)
      ? payload.detail
          .map((item) => item.msg)
          .filter(Boolean)
          .join(", ")
      : typeof payload?.detail === "object"
        ? payload.detail.message
        : payload?.detail;
    super(
      payload?.cause ??
        payload?.message ??
        detail ??
        `Backend request failed with status ${status}.`
    );
    this.name = "BackendRequestError";
    this.payload = payload;
    this.requestId = payload?.requestId;
    this.status = status;
  }
}

export type BackendRequestOptions = {
  timeoutMs?: number;
};

type BackendAuthorizationFailureHandler = (error: BackendRequestError) => void;

let authorizationFailureHandler: BackendAuthorizationFailureHandler | null = null;

export function setBackendAuthorizationFailureHandler(
  handler: BackendAuthorizationFailureHandler | null
) {
  authorizationFailureHandler = handler;
}

function hasBody(init: RequestInit) {
  return init.body !== undefined && init.body !== null;
}

function normalizeInit(init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers);

  if (
    hasBody(init) &&
    !(init.body instanceof FormData) &&
    !headers.has("content-type")
  ) {
    headers.set("content-type", "application/json");
  }

  return { ...init, headers };
}

export async function requestBackend<TData>(
  input: RequestInfo | URL,
  init?: RequestInit,
  options: BackendRequestOptions = {}
): Promise<TData> {
  const timeoutMs = options.timeoutMs;
  const timeoutController = timeoutMs
    ? new AbortController()
    : null;
  const parentSignal = init?.signal;
  let timeoutTriggered = false;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let abortFromParent: (() => void) | null = null;

  if (timeoutController && timeoutMs) {
    timeoutId = setTimeout(() => {
      timeoutTriggered = true;
      timeoutController.abort();
    }, timeoutMs);
    abortFromParent = () => timeoutController.abort();
    if (parentSignal) {
      if (parentSignal.aborted) {
        abortFromParent();
      } else {
        parentSignal.addEventListener("abort", abortFromParent, { once: true });
      }
    }
  }

  try {
    const response = await apiFetch(
      input,
      normalizeInit({
        ...init,
        ...(timeoutController ? { signal: timeoutController.signal } : {}),
      })
    );

    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json")
      ? ((await response.json().catch(() => null)) as unknown)
      : await response.text();

    if (!response.ok) {
      const error = new BackendRequestError(
        response.status,
        payload && typeof payload === "object"
          ? (payload as BackendErrorPayload)
          : null
      );
      if (response.status === 401 || response.status === 403) {
        authorizationFailureHandler?.(error);
      }
      throw error;
    }

    return payload as TData;
  } catch (error) {
    if (timeoutTriggered) {
      throw new BackendRequestError(504, {
        code: "backend:timeout",
        message: "The backend request timed out.",
      });
    }
    throw error;
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    if (parentSignal && abortFromParent) {
      parentSignal.removeEventListener("abort", abortFromParent);
    }
  }
}
