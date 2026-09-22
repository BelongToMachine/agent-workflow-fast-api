import { apiFetch, apiUpload, type ApiUploadProgressHandler } from "./directClient";

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

async function parseBackendResponse<TData>(response: Response): Promise<TData> {
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

    return parseBackendResponse<TData>(response);
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

export type BackendStreamEvent = Record<string, unknown>;

export async function requestBackendEventStream(
  input: RequestInfo | URL,
  init: RequestInit,
  onEvent: (event: BackendStreamEvent) => void
): Promise<void> {
  const response = await apiFetch(input, normalizeInit(init));
  if (!response.ok) {
    await parseBackendResponse<never>(response);
    return;
  }
  if (!response.body) {
    throw new BackendRequestError(502, {
      code: "backend:invalid_stream",
      message: "The backend did not return a readable event stream.",
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const frames = pending.split("\n\n");
      pending = frames.pop() ?? "";
      for (const frame of frames) {
        const payload = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!payload) {
          continue;
        }
        try {
          const event = JSON.parse(payload) as unknown;
          if (event && typeof event === "object" && !Array.isArray(event)) {
            onEvent(event as BackendStreamEvent);
          }
        } catch {
          // Ignore a malformed provider frame: the terminal backend event holds
          // the actionable error, while a partial frame must not break the UI.
        }
      }
      if (done) {
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function requestBackendUpload<TData>(
  input: RequestInfo | URL,
  formData: FormData,
  onProgress?: ApiUploadProgressHandler,
): Promise<TData> {
  const response = await apiUpload(input, formData, onProgress);
  return parseBackendResponse<TData>(response);
}
