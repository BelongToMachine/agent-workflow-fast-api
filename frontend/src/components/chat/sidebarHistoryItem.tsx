import { Link } from "@/lib/router";
import { useTranslation } from "react-i18next";
import { memo, useCallback } from "react";
import type { ChatHistoryEntry } from "@/lib/backend/chatHistoryCache";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdownMenu";
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "../ui/sidebar";
import {
  MoreHorizontalIcon,
  TrashIcon,
} from "./icons";
import { getSidebarNavigationItemClassName } from "./sidebarStyles";

const PureChatItem = ({
  chat,
  isActive,
  onDelete,
  setOpenMobile,
}: {
  chat: ChatHistoryEntry;
  isActive: boolean;
  onDelete: (chatId: string) => void;
  setOpenMobile: (open: boolean) => void;
}) => {
  const { t } = useTranslation();
  const closeMobile = useCallback(() => {
    setOpenMobile(false);
  }, [setOpenMobile]);

  const handleDelete = useCallback(() => {
    onDelete(chat.id);
  }, [chat.id, onDelete]);

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        className={getSidebarNavigationItemClassName(isActive)}
        isActive={isActive}
      >
        <Link
          aria-current={isActive ? "page" : undefined}
          href={`/chat/${chat.id}`}
          onClick={closeMobile}
        >
          <span className="truncate">{chat.title}</span>
        </Link>
      </SidebarMenuButton>

      <DropdownMenu modal={true}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuAction
            className="mr-0.5 rounded-md text-sidebar-foreground/50 ring-0 transition-colors duration-150 focus-visible:ring-0 hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            showOnHover={!isActive}
          >
            <MoreHorizontalIcon />
            <span className="sr-only">{t("sidebar.more")}</span>
          </SidebarMenuAction>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" side="bottom">
          {/*
            Temporarily disabled until chat visibility is needed again.
            <DropdownMenuSub>
              <DropdownMenuSubTrigger className="cursor-pointer">
                <ShareIcon />
                <span>Share</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuPortal>
                <DropdownMenuSubContent>
                  Private/Public options
                </DropdownMenuSubContent>
              </DropdownMenuPortal>
            </DropdownMenuSub>
          */}

          <DropdownMenuItem onSelect={handleDelete} variant="destructive">
            <TrashIcon />
            <span>{t("common.delete")}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuItem>
  );
};

export const ChatItem = memo(PureChatItem, (prevProps, nextProps) => {
  if (prevProps.isActive !== nextProps.isActive) {
    return false;
  }
  if (
    prevProps.chat.title !== nextProps.chat.title ||
    prevProps.chat.visibility !== nextProps.chat.visibility
  ) {
    return false;
  }
  return true;
});
