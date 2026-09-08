import {
  isLocalSessionAuthMode,
  isLogtoAuthMode,
} from "../auth/logtoConfig";

const apiMode = process.env.NEXT_PUBLIC_API_MODE || "fastapi-proxy";
const isProduction = import.meta.env.PROD;

export const isFastApiDirectMode =
  (!isProduction && apiMode === "fastapi-direct") ||
  (isProduction && (isLogtoAuthMode || isLocalSessionAuthMode));

export const isFastApiProxyMode =
  !isProduction && apiMode === "fastapi-proxy";

// The MVP intentionally exposes one workspace. Keep this explicit so the
// request boundary can be relaxed when workspace selection is implemented.
export const isSingleWorkspaceMode =
  process.env.NEXT_PUBLIC_SINGLE_WORKSPACE_MODE !== "false";

export const fastApiWorkspaceId =
  process.env.NEXT_PUBLIC_WORKSPACE_ID ||
  "00000000-0000-0000-0000-000000000001";

export const fastApiBrowserBaseUrl = (
  process.env.NEXT_PUBLIC_FASTAPI_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");
