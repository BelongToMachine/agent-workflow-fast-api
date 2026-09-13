import { memo, useCallback } from "react";
import { useTranslation } from "react-i18next";

import { initialArtifactData, useArtifact } from "@/hooks/useArtifact";
import { CrossIcon } from "./icons";

function PureArtifactCloseButton() {
  const { t } = useTranslation();
  const { setArtifact } = useArtifact();
  const handleClick = useCallback(() => {
    setArtifact((currentArtifact) =>
      currentArtifact.status === "streaming"
        ? {
            ...currentArtifact,
            isVisible: false,
          }
        : { ...initialArtifactData, status: "idle" }
    );
  }, [setArtifact]);

  return (
    <button
      className="group flex size-8 items-center justify-center rounded-lg border border-transparent text-muted-foreground transition-all duration-150 hover:border-border hover:bg-muted hover:text-foreground active:scale-95"
      data-testid="artifact-close-button"
      aria-label={t("common.close")}
      onClick={handleClick}
      type="button"
    >
      <CrossIcon size={16} />
    </button>
  );
}

export const ArtifactCloseButton = memo(PureArtifactCloseButton, () => true);
