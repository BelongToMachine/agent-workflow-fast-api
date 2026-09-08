import type { LogtoConfig } from "@logto/react";

const readEnv = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

export const logtoEndpoint = readEnv(import.meta.env.VITE_LOGTO_ENDPOINT);
export const logtoAppId = readEnv(import.meta.env.VITE_LOGTO_APP_ID);
export const logtoApiResource = readEnv(
  import.meta.env.VITE_LOGTO_API_RESOURCE
);

export function getLogtoEndSessionUri(postLogoutRedirectUri: string) {
  if (!logtoEndpoint || !logtoAppId) {
    return null;
  }

  try {
    const normalizedEndpoint = logtoEndpoint.replace(/\/+$/, "");
    const endpoint = normalizedEndpoint.endsWith("/oidc")
      ? `${normalizedEndpoint}/session/end`
      : `${normalizedEndpoint}/oidc/session/end`;
    const url = new URL(endpoint);
    url.searchParams.set("client_id", logtoAppId);
    url.searchParams.set("post_logout_redirect_uri", postLogoutRedirectUri);
    return url.toString();
  } catch {
    return null;
  }
}

export const isLogtoConfigured = Boolean(
  logtoEndpoint && logtoAppId && logtoApiResource
);

export type AuthMode = "development" | "preview" | "local_session";

const AUTH_MODE_STORAGE_KEY = "asianode.auth-mode";

/**
 * Local development defaults to the dev OIDC simulator. Any built
 * built environments are forced onto an explicitly configured remote or
 * local-session mode so production cannot silently fall back to development
 * credentials.
 */
function readAuthMode(): AuthMode {
  const requestedMode = readEnv(import.meta.env.VITE_AUTH_MODE);
  if (requestedMode === "local_session") {
    return "local_session";
  }

  if (!import.meta.env.DEV) {
    return "preview";
  }

  if (!isLogtoConfigured || typeof window === "undefined") {
    return "development";
  }

  try {
    return window.localStorage.getItem(AUTH_MODE_STORAGE_KEY) === "preview"
      ? "preview"
      : "development";
  } catch {
    return "development";
  }
}

export const authMode = readAuthMode();
export const canSwitchAuthMode = import.meta.env.DEV;
export const isLogtoAuthMode =
  isLogtoConfigured && authMode === "preview";
export const isLocalSessionAuthMode = authMode === "local_session";

export function setAuthMode(nextMode: AuthMode) {
  if (!canSwitchAuthMode) {
    return;
  }

  if (nextMode === "preview" && !isLogtoConfigured) {
    window.alert(
      "Preview / Logto 模式需要先配置 VITE_LOGTO_ENDPOINT、VITE_LOGTO_APP_ID 和 VITE_LOGTO_API_RESOURCE。"
    );
    return;
  }

  window.localStorage.setItem(AUTH_MODE_STORAGE_KEY, nextMode);
  window.location.reload();
}

export const logtoConfig: LogtoConfig | null = isLogtoConfigured
  ? {
      appId: logtoAppId,
      endpoint: logtoEndpoint,
      resources: [logtoApiResource],
      scopes: ["email"],
    }
  : null;
