import {
  fastApiBrowserBaseUrl,
  fastApiWorkspaceId,
  isFastApiDirectMode,
  isFastApiProxyMode,
  isSingleWorkspaceMode,
} from "./mode";
import { getLocalCsrfToken } from "../auth/localSession";

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
  appendWorkspaceId(target);
  return `${target.pathname}${target.search}`;
}

function mapLegacyApiUrl(
  input: RequestInfo | URL,
  method: string
) {
  return new URL(mapLegacyApiPath(input, method), fastApiBrowserBaseUrl);
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
    return fetch(mapLegacyApiPath(input, method), {
      ...init,
      credentials: init?.credentials ?? "include",
      headers: requestHeaders,
    });
  }

  if (!isFastApiDirectMode || typeof window === "undefined") {
    return fetch(input, init);
  }

  const target = mapLegacyApiUrl(input, method);

  return fetch(target, {
    ...init,
    credentials: init?.credentials ?? "include",
    headers: requestHeaders,
  });
}
