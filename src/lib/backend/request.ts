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
  init?: RequestInit
): Promise<TData> {
  const response = await apiFetch(input, normalizeInit(init));
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
}
