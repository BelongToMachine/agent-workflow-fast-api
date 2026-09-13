"use client";

import { useFormStatus } from "react-dom";
import { useTranslation } from "react-i18next";

import { LoaderIcon } from "@/components/chat/icons";

import { Button } from "../ui/button";

export function SubmitButton({
  children,
  isSuccessful,
}: {
  children: React.ReactNode;
  isSuccessful: boolean;
}) {
  const { pending } = useFormStatus();
  const { t } = useTranslation();

  return (
    <Button
      aria-disabled={pending || isSuccessful}
      className="relative"
      disabled={pending || isSuccessful}
      type={pending ? "button" : "submit"}
    >
      {children}

      {pending || isSuccessful ? (
        <span className="absolute right-4 animate-spin">
          <LoaderIcon />
        </span>
      ) : null}

      <output aria-live="polite" className="sr-only">
        {pending || isSuccessful ? t("common.loadingShort") : t("ui.submitForm")}
      </output>
    </Button>
  );
}
