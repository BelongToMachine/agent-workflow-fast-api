export const isProductionEnvironment = process.env.NODE_ENV === "production";
export const isDevelopmentEnvironment = process.env.NODE_ENV === "development";
export const isMockDatabase = process.env.MOCK_DB === "1";
export const isChatLimitsDisabled = process.env.DISABLE_CHAT_LIMITS === "1";
export const isGuestAccessEnabled =
  !isProductionEnvironment && process.env.DISABLE_GUEST_AUTH !== "1";
export const isPublicRegistrationEnabled =
  !isProductionEnvironment || process.env.ALLOW_PUBLIC_REGISTRATION === "1";

export const isTestEnvironment = Boolean(
  process.env.PLAYWRIGHT_TEST_BASE_URL ||
    process.env.PLAYWRIGHT ||
    process.env.CI_PLAYWRIGHT
);

export const guestRegex = /^guest-\d+$/;

export const DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001";

export const DUMMY_PASSWORD = "frontend-only";

export const suggestionKeys = [
  "suggestions.price",
  "suggestions.turkey",
  "suggestions.content",
  "suggestions.missingData",
] as const;
