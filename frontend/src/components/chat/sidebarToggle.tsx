import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import { type SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "../ui/button";
import { SidebarLeftIcon } from "./icons";

export function SidebarToggle({
  className,
}: ComponentProps<typeof SidebarTrigger>) {
  const { t } = useTranslation();
  const { toggleSidebar } = useSidebar();

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          className={className}
          data-testid="sidebar-toggle-button"
          onClick={toggleSidebar}
          size="icon-sm"
          variant="outline"
        >
          <SidebarLeftIcon size={16} />
        </Button>
      </TooltipTrigger>
      <TooltipContent align="start" className="hidden md:block">
        {t("ui.toggleSidebar")}
      </TooltipContent>
    </Tooltip>
  );
}
