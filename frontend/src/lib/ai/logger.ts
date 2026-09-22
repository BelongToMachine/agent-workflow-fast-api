type LogLevel = "error" | "info" | "warn";

const MAX_ERROR_TEXT_LENGTH = 2000;

function serializeCause(cause: unknown, depth = 0): unknown {
  if (depth >= 2 || cause === null || cause === undefined) {
    return;
  }

  if (cause instanceof Error) {
    return {
      message: redact(cause.message),
      name: cause.name,
      ...(cause.cause ? { cause: serializeCause(cause.cause, depth + 1) } : {}),
    };
  }

  return redact(String(cause));
}

function redact(value: string) {
  return value
    .replace(/sk-[A-Za-z0-9_-]+/g, "[REDACTED_API_KEY]")
    .replace(
      /(postgres(?:ql)?:\/\/[^:]+:)[^@]+(@)/gi,
      "$1[REDACTED_PASSWORD]$2"
    )
    .replace(
      /((?:api[_-]?key|token|secret|password)\s*[:=]\s*["']?)[^,\s"']+/gi,
      "$1[REDACTED]"
    )
    .slice(0, MAX_ERROR_TEXT_LENGTH);
}

export function serializeError(error: unknown) {
  if (error instanceof Error) {
    return {
      message: redact(error.message),
      name: error.name,
      ...(error.cause ? { cause: serializeCause(error.cause) } : {}),
      ...(process.env.NODE_ENV !== "production" ||
      process.env.DEBUG_AI_LOGS === "1"
        ? { stack: redact(error.stack ?? "") }
        : {}),
    };
  }

  return { message: redact(String(error)), name: "UnknownError" };
}

export function logEvent(
  level: LogLevel,
  event: string,
  fields: Record<string, unknown> = {}
) {
  const payload = {
    event,
    level,
    timestamp: new Date().toISOString(),
    ...fields,
  };
  const line = `[ai-agent] ${JSON.stringify(payload)}`;

  if (level === "error") {
    console.error(line);
  } else if (level === "warn") {
    console.warn(line);
  } else {
    console.info(line);
  }
}

export function logError(
  event: string,
  error: unknown,
  fields: Record<string, unknown> = {}
) {
  logEvent("error", event, {
    ...fields,
    error: serializeError(error),
  });
}

export function summarizeToolInput(input: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(input).map(([key, value]) => {
      if (typeof value === "string") {
        return [`${key}Length`, value.length];
      }
      return [key, value];
    })
  );
}

export function getClientErrorMessage(error: unknown, requestId: string) {
  const message =
    error instanceof Error ? redact(error.message) : redact(String(error));

  if (process.env.NODE_ENV !== "production") {
    return `[${requestId}] ${message || "Unknown chat error"}`;
  }

  return `Oops, an error occurred. Reference: ${requestId}`;
}

export function getRequestIdFromError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    message.match(/\[([a-z0-9-]+)\]/i)?.[1] ??
    message.match(/Reference:\s*([a-z0-9-]+)/i)?.[1]
  );
}
