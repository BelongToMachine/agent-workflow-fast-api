"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  fastApiBrowserBaseUrl,
  isFastApiDirectMode,
  isFastApiProxyMode,
} from "@/lib/backend/mode";
import { Spinner } from "@/components/ui/spinner";

type ConnectionState =
  | { status: "checking" }
  | { status: "success"; message: string; payload: unknown }
  | { status: "error"; message: string; payload?: unknown };

export function FastApiConnectionTest() {
  const { t } = useTranslation();
  const [connection, setConnection] = useState<ConnectionState>({
    status: "checking",
  });

  const checkConnection = useCallback(async () => {
    setConnection({ status: "checking" });

    try {
      const response = await fetch(
        isFastApiDirectMode
          ? `${fastApiBrowserBaseUrl}/api/v1/healthz`
          : "/api/v1/healthz",
        { cache: "no-store" }
      );
      const payload = await response.json();

      if (!response.ok) {
        setConnection({
          message: isFastApiDirectMode
            ? t("settings.browserCannotConnect")
            : t("settings.proxyCannotConnect"),
          payload,
          status: "error",
        });
        return;
      }

      const isFastApi = isFastApiDirectMode || isFastApiProxyMode;
      setConnection({
        message: isFastApiDirectMode
          ? t("settings.directConnectionSuccess")
          : t("settings.proxyConnectionSuccess"),
        payload,
        status: isFastApi ? "success" : "error",
      });
    } catch {
      setConnection({
        message: t("settings.integrationRequestFailed"),
        status: "error",
      });
    }
  }, [t]);

  const handleCheckConnection = useCallback(() => {
    checkConnection().catch(() => undefined);
  }, [checkConnection]);

  useEffect(() => {
    checkConnection().catch(() => undefined);
  }, [checkConnection]);

  const isSuccess = connection.status === "success";

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-6">
      <section className="w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-sm">
        <p className="text-sm text-muted-foreground">{t("settings.backendMigration")}</p>
        <h1 className="mt-2 text-2xl font-semibold text-foreground">
          {t("settings.connectionTestTitle")}
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          {t("settings.connectionTestDescription")}
        </p>

        <div
          aria-live="polite"
          className={`mt-6 rounded-lg border p-4 text-sm ${
            connection.status === "checking"
              ? "border-border bg-muted text-muted-foreground"
              : isSuccess
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "border-destructive/30 bg-destructive/10 text-destructive"
          }`}
        >
          {connection.status === "checking" ? (
            <span className="flex items-center gap-2">
              <Spinner />
              {t("settings.checkingConnection")}
            </span>
          ) : (
            connection.message
          )}
        </div>

        {connection.status !== "checking" && connection.payload ? (
          <pre className="mt-4 overflow-x-auto rounded-lg bg-muted p-4 text-xs text-muted-foreground">
            {JSON.stringify(connection.payload, null, 2)}
          </pre>
        ) : null}

        <button
          className="mt-6 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={connection.status === "checking"}
          onClick={handleCheckConnection}
          type="button"
        >
          {connection.status === "checking" ? <Spinner /> : null}
          {t("settings.retest")}
        </button>
      </section>
    </main>
  );
}
