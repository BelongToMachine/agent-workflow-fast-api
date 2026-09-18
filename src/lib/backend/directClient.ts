import {
  fastApiBrowserBaseUrl,
  fastApiWorkspaceId,
  isFastApiDirectMode,
  isFastApiProxyMode,
  isSingleWorkspaceMode,
} from "./mode";
import {
  getLocalCsrfToken,
  invalidateLocalCsrfToken,
} from "../auth/localSession";

function getBasePath() {
  return (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
}

function getInputUrl(input: RequestInfo | URL) {
  if (input instanceof Request) {
    return new URL(input.url, window.location.href);
  }

  return new URL(input.toString(), window.location.href);
}

function pathWithoutBasePath(pathname: string) {
  const basePath = getBasePath();
  if (basePath && pathname.startsWith(`${basePath}/`)) {
    return pathname.slice(basePath.length);
  }
  return pathname;
}

function appendWorkspaceId(url: URL) {
  const path = url.pathname;
  const isWorkspaceScoped =
    path.startsWith("/api/v1/chat") ||
    path.startsWith("/api/v1/chats") ||
    path.startsWith("/api/v1/documents") ||
    path.startsWith("/api/v1/suggestions") ||
    path.startsWith("/api/v1/knowledge-") ||
    path.startsWith("/api/v1/business-import") ||
    path.startsWith("/api/v1/admin/") ||
    path === "/api/v1/files/upload" ||
    path === "/api/v1/products" ||
    path === "/api/v1/content/search";

  if (!isWorkspaceScoped) {
    return;
  }

  // The browser currently targets one configured workspace. Override legacy
  // caller-supplied values so it cannot accidentally switch business context.
  const workspaceId = isSingleWorkspaceMode
    ? fastApiWorkspaceId
    : url.searchParams.get("workspace_id") ||
      (isFastApiProxyMode ? fastApiWorkspaceId : null);
  if (workspaceId) {
    url.searchParams.set("workspace_id", workspaceId);
  }
}

function mapLegacyApiPath(
  input: RequestInfo | URL,
  method: string
) {
  const source = getInputUrl(input);
  const path = pathWithoutBasePath(source.pathname);
  const query = new URLSearchParams(source.searchParams);
  let targetPath: string | null = null;

  if (path === "/api/chat") {
    if (method === "DELETE") {
      const chatId = query.get("id");
      if (chatId) {
        targetPath = `/api/v1/chats/${encodeURIComponent(chatId)}`;
        query.delete("id");
      }
    } else {
      targetPath = "/api/v1/chat";
    }
  } else {
    const streamMatch = path.match(/^\/api\/chat\/([^/]+)\/stream$/);
    if (streamMatch) {
      targetPath = `/api/v1/chat/${encodeURIComponent(streamMatch[1])}/stream`;
    }
  }

  if (path === "/api/messages") {
    const chatId = query.get("chatId");
    if (chatId) {
      targetPath = `/api/v1/chats/${encodeURIComponent(chatId)}/messages`;
      query.delete("chatId");
    }
  } else if (path === "/api/history") {
    targetPath = "/api/v1/chats";
  } else if (path === "/api/document") {
    targetPath = "/api/v1/documents";
  } else if (path === "/api/suggestions") {
    targetPath = "/api/v1/suggestions";
  } else if (path === "/api/models") {
    targetPath = "/api/v1/models";
  } else if (path === "/api/files/upload") {
    targetPath = "/api/v1/files/upload";
  } else if (
    path === "/api/knowledge-bases" ||
    path.startsWith("/api/knowledge-bases/")
  ) {
    targetPath = path.replace(/^\/api\//, "/api/v1/");
  } else if (
    path === "/api/admin/members" ||
    path.startsWith("/api/admin/members/")
  ) {
    targetPath = path.replace(/^\/api\//, "/api/v1/");
  } else if (path === "/api/admin/access-candidates") {
    targetPath = path.replace(/^\/api\//, "/api/v1/");
  } else if (
    path === "/api/admin/knowledge-base-grants" ||
    path.startsWith("/api/admin/knowledge-base-grants/")
  ) {
    targetPath = path.replace(/^\/api\//, "/api/v1/");
  }

  if (!targetPath) {
    const target = new URL(source.pathname, "http://vite-fastapi-proxy.local");
    target.search = query.toString();
    appendWorkspaceId(target);
    return `${target.pathname}${target.search}`;
  }

  const target = new URL(targetPath, "http://vite-fastapi-proxy.local");
  target.search = query.toString();
  appendWorkspaceId(target);
  return `${target.pathname}${target.search}`;
}

function mapLegacyApiUrl(
  input: RequestInfo | URL,
  method: string
) {
  return new URL(mapLegacyApiPath(input, method), fastApiBrowserBaseUrl);
}

function cloneRequestInput(input: RequestInfo | URL) {
  return input instanceof Request ? input.clone() : input;
}

async function isCsrfFailure(response: Response) {
  if (response.status !== 403) {
    return false;
  }

  const payload = (await response.clone().json().catch(() => null)) as {
    code?: unknown;
  } | null;
  return payload?.code === "csrf:token_invalid";
}

async function sendWithCsrfRecovery(
  method: string,
  requestHeaders: Headers,
  send: () => Promise<Response>,
) {
  let response = await send();
  if (
    !["DELETE", "PATCH", "POST", "PUT"].includes(method) ||
    !(await isCsrfFailure(response))
  ) {
    return response;
  }

  invalidateLocalCsrfToken();
  requestHeaders.set("X-CSRF-Token", await getLocalCsrfToken(true));
  return send();
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const method = (
    init?.method ?? (input instanceof Request ? input.method : "GET")
  ).toUpperCase();

  const requestHeaders = new Headers(
    init?.headers ?? (input instanceof Request ? input.headers : undefined)
  );
  if (["DELETE", "PATCH", "POST", "PUT"].includes(method) && !requestHeaders.has("X-CSRF-Token")) {
    requestHeaders.set("X-CSRF-Token", await getLocalCsrfToken());
  }

  if (isFastApiProxyMode && typeof window !== "undefined") {
    const target = mapLegacyApiPath(input, method);
    return sendWithCsrfRecovery(method, requestHeaders, () =>
      fetch(cloneRequestInput(target), {
        ...init,
        credentials: init?.credentials ?? "include",
        headers: requestHeaders,
      }),
    );
  }

  if (!isFastApiDirectMode || typeof window === "undefined") {
    return fetch(input, init);
  }

  const target = mapLegacyApiUrl(input, method);
  return sendWithCsrfRecovery(method, requestHeaders, () =>
    fetch(cloneRequestInput(target), {
      ...init,
      credentials: init?.credentials ?? "include",
      headers: requestHeaders,
    }),
  );
}

export type ApiUploadProgressHandler = (loaded: number, total: number) => void;

function xhrResponse(xhr: XMLHttpRequest) {
  const headers = new Headers();
  const contentType = xhr.getResponseHeader("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  return new Response(xhr.responseText, {
    headers,
    status: xhr.status,
    statusText: xhr.statusText,
  });
}

function sendUploadRequest(
  target: string | URL,
  formData: FormData,
  requestHeaders: Headers,
  withCredentials: boolean,
  onProgress?: ApiUploadProgressHandler,
) {
  return new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", target.toString(), true);
    xhr.withCredentials = withCredentials;
    requestHeaders.forEach((value, key) => xhr.setRequestHeader(key, value));
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress?.(event.loaded, event.total);
      }
    });
    xhr.addEventListener("load", () => resolve(xhrResponse(xhr)));
    xhr.addEventListener("error", () => reject(new TypeError("Network request failed.")));
    xhr.addEventListener("abort", () => reject(new DOMException("The upload was aborted.", "AbortError")));
    xhr.send(formData);
  });
}

export async function apiUpload(
  input: RequestInfo | URL,
  formData: FormData,
  onProgress?: ApiUploadProgressHandler,
): Promise<Response> {
  const method = "POST";
  const requestHeaders = new Headers(
    input instanceof Request ? input.headers : undefined,
  );
  if (!requestHeaders.has("X-CSRF-Token")) {
    requestHeaders.set("X-CSRF-Token", await getLocalCsrfToken());
  }

  let target: string | URL = input instanceof Request ? input.url : input;
  let withCredentials = false;
  if (isFastApiProxyMode && typeof window !== "undefined") {
    target = mapLegacyApiPath(input, method);
    withCredentials = true;
  } else if (isFastApiDirectMode && typeof window !== "undefined") {
    target = mapLegacyApiUrl(input, method);
    withCredentials = true;
  }

  const send = () =>
    sendUploadRequest(target, formData, requestHeaders, withCredentials, onProgress);
  return sendWithCsrfRecovery(method, requestHeaders, send);
}
