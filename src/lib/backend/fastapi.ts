import "server-only";

const DEFAULT_FASTAPI_URL = "http://127.0.0.1:8000";

export const isFastApiBackendEnabled =
  process.env.USE_FASTAPI_BACKEND === "1" ||
  process.env.USE_FASTAPI_BACKEND === "true";

export const isFastApiAttachmentUploadEnabled =
  process.env.USE_FASTAPI_ATTACHMENT_UPLOAD === "1" ||
  process.env.USE_FASTAPI_ATTACHMENT_UPLOAD === "true";

const fastApiBaseUrl = (
  process.env.VITE_FASTAPI_URL ?? DEFAULT_FASTAPI_URL
).replace(/\/$/, "");

export function getFastApiUrl(path: string): string {
  return `${fastApiBaseUrl}/${path.replace(/^\//, "")}`;
}

export function fetchFastApi(path: string, init?: RequestInit) {
  return fetch(getFastApiUrl(path), {
    ...init,
    cache: "no-store",
  });
}
