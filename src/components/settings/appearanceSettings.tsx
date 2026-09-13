"use client";

import { CheckIcon } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  accentColorOptions,
  getStoredAccentColor,
  storeAccentColor,
  type AccentColor,
} from "@/lib/accentColor";
import { cn } from "@/lib/utils";

export function AppearanceSettings() {
  const { t } = useTranslation();
  const [selectedAccentColor, setSelectedAccentColor] = useState<AccentColor>(
    getStoredAccentColor
  );

  const handleAccentColorChange = (accentColor: AccentColor) => {
    setSelectedAccentColor(accentColor);
    storeAccentColor(accentColor);
  };

  return (
    <section className="max-w-2xl">
      <div className="rounded-xl border border-border/60 bg-card/40 p-5 md:p-6">
        <div>
          <h2 className="text-base font-semibold tracking-tight">
            {t("settings.accentColorLabel")}
          </h2>
          <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
            {t("settings.accentColorDescription")}
          </p>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {accentColorOptions.map((option) => {
            const isSelected = selectedAccentColor === option.value;

            return (
              <button
                aria-pressed={isSelected}
                className={cn(
                  "flex min-h-20 flex-col items-start justify-between gap-3 rounded-lg border border-border/60 bg-background/60 p-3 text-left transition-colors hover:border-foreground/30 hover:bg-muted/50",
                  isSelected &&
                    "border-foreground/40 bg-muted/70 ring-1 ring-foreground/10"
                )}
                key={option.value}
                onClick={() => handleAccentColorChange(option.value)}
                type="button"
              >
                <span
                  aria-hidden="true"
                  className="size-5 rounded-full ring-1 ring-black/10 dark:ring-white/20"
                  style={{ backgroundColor: option.swatch }}
                />
                <span className="flex w-full items-center justify-between gap-2 text-xs font-medium">
                  {t(option.labelKey)}
                  {isSelected ? <CheckIcon className="size-3.5" /> : null}
                </span>
              </button>
            );
          })}
        </div>

        <div className="mt-8 border-t border-border/60 pt-6">
          <p className="text-sm font-medium">{t("settings.accentColorPreview")}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("settings.accentColorPreviewDescription")}
          </p>
          <div className="mt-4 rounded-lg border border-border/50 bg-background/60 p-4">
            <div className="flex justify-end">
              <div className="user-message-bubble max-w-[min(100%,24rem)] rounded-xl rounded-br-md px-3.5 py-2 text-sm leading-6">
                {t("settings.accentColorPreviewMessage")}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
