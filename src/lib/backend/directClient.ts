import {
  fastApiBrowserBaseUrl,
  fastApiWorkspaceId,
  isFastApiDirectMode,
  isFastApiProxyMode,
  isSingleWorkspaceMode,
} from "./mode";
import {
  getLogtoAccessToken,
} from "../auth/logtoToken";
import {
  isLocalSessionAuthMode,
  isLogtoAuthMode,
} from "../auth/logtoConfig";
import { getLocalCsrfToken } from "../auth/localSession";

const DIRECT_TOKEN_STORAGE_KEY = "asianode.fastapi.direct-token";

export type DirectToken = {
  accessToken: string;
  expiresAt: number;
  workspaceId: string;
};

let memoryToken: DirectToken | null = null;

function getBasePath() {
  return (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
}

function getStoredToken() {
  if (typeof window === "undefined") {
    return null;
  }

  if (memoryToken) {
    if (memoryToken.expiresAt > Date.now() + 30_000) {
      return memoryToken;
    }
    memoryToken = null;
  }

  try {
    const raw = window.sessionStorage.getItem(DIRECT_TOKEN_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as DirectToken;
    if (
      !parsed.accessToken ||
      !parsed.workspaceId ||
      !Number.isFinite(parsed.expiresAt) ||
      parsed.expiresAt <= Date.now() + 30_000
    ) {
      window.sessionStorage.removeItem(DIRECT_TOKEN_STORAGE_KEY);
      return null;
    }

    memoryToken = parsed;
    return parsed;
  } catch {
    window.sessionStorage.removeItem(DIRECT_TOKEN_STORAGE_KEY);
    return null;
  }
}

export function setStoredDirectToken(token: DirectToken) {
  memoryToken = token;
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(
      DIRECT_TOKEN_STORAGE_KEY,
      JSON.stringify(token)
    );
    window.dispatchEvent(new Event("asianode-auth-change"));
  }
}

export function clearStoredDirectToken() {
  memoryToken = null;
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(DIRECT_TOKEN_STORAGE_KEY);
    window.dispatchEvent(new Event("asianode-auth-change"));
  }
}

export function getStoredDirectToken() {
  return getStoredToken();
}

async function getApiAccessToken() {
  if (isLogtoAuthMode) {
    return getLogtoAccessToken();
  }

  return getStoredToken()?.accessToken ?? null;
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

function appendWorkspaceId(url: URL, token: DirectToken | null) {
  const path = url.pathname;
  const isWorkspaceScoped =
    path.startsWith("/api/v1/chat") ||
    path.startsWith("/api/v1/chats") ||
    path.startsWith("/api/v1/votes") ||
    path.startsWith("/api/v1/documents") ||
    path.startsWith("/api/v1/suggestions") ||
    path.startsWith("/api/v1/knowledge-") ||
    path.startsWith("/api/v1/admin/") ||
    path === "/api/v1/files/upload" ||
    path === "/api/v1/products" ||
    path === "/api/v1/content/search";

  if (!isWorkspaceScoped) {
    return;
  }

  // In Logto mode the backend is intentionally single-workspace for the MVP.
  // Override legacy caller-supplied values so the browser cannot accidentally
  // switch business context before a real workspace selector exists.
  const workspaceId =
    isSingleWorkspaceMode && (isLogtoAuthMode || isLocalSessionAuthMode)
      ? fastApiWorkspaceId
      : url.searchParams.get("workspace_id") ||
        token?.workspaceId ||
        (isFastApiProxyMode ? fastApiWorkspaceId : null);
  if (workspaceId) {
    url.searchParams.set("workspace_id", workspaceId);
  }
}

function mapLegacyApiPath(
  input: RequestInfo | URL,
  method: string,
  token: DirectToken | null
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
  } else if (path === "/api/vote") {
    targetPath = "/api/v1/votes";
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
    return `${source.pathname}${source.search}`;
  }

  const target = new URL(targetPath, "http://vite-fastapi-proxy.local");
  target.search = query.toString();
  appendWorkspaceId(target, token);
  return `${target.pathname}${target.search}`;
}

function mapLegacyApiUrl(
  input: RequestInfo | URL,
  method: string,
  token: DirectToken | null
) {
  return new URL(mapLegacyApiPath(input, method, token), fastApiBrowserBaseUrl);
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
  if (
    isLocalSessionAuthMode &&
    ["DELETE", "PATCH", "POST", "PUT"].includes(method) &&
    !requestHeaders.has("X-CSRF-Token")
  ) {
    requestHeaders.set("X-CSRF-Token", await getLocalCsrfToken());
  }

  if (isFastApiProxyMode && typeof window !== "undefined") {
    const token = isLogtoAuthMode ? null : getStoredToken();
    const accessToken = await getApiAccessToken();
    const headers = requestHeaders;

    if (accessToken && !headers.has("authorization")) {
      headers.set("authorization", `Bearer ${accessToken}`);
    }

    return fetch(mapLegacyApiPath(input, method, token), {
      ...init,
      credentials: init?.credentials ?? "include",
      headers,
    });
  }

  if (!isFastApiDirectMode || typeof window === "undefined") {
    return fetch(input, init);
  }

  const storedToken = isLogtoAuthMode ? null : getStoredToken();
  const accessToken = await getApiAccessToken();
  const target = mapLegacyApiUrl(input, method, storedToken);
  const headers = requestHeaders;

  if (accessToken && !headers.has("authorization")) {
    headers.set("authorization", `Bearer ${accessToken}`);
  }

  return fetch(target, {
    ...init,
    credentials: init?.credentials ?? "include",
    headers,
  });
}
