"use client";

import { type InfiniteData, useQueryClient } from "@tanstack/react-query";
import {
  FilesIcon,
  KeyRoundIcon,
  MessageSquareIcon,
  PanelLeftIcon,
  PenSquareIcon,
  ShieldCheckIcon,
  TrashIcon,
} from "lucide-react";
import type { User } from "@/lib/auth";
import { Link, useRouter } from "@/lib/router";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { SidebarHistory } from "@/components/chat/sidebarHistory";
import { SidebarUserNav } from "@/components/chat/sidebarUserNav";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  backendQueryKeys,
  useBackendIdentity,
} from "@/lib/backend/reactQuery";
import {
  type ChatHistory,
  type ChatHistoryEntry,
  getLocalChatHistoryQueryKey,
} from "@/lib/backend/chatHistoryCache";
import { requestBackend } from "@/lib/backend/request";
import { getNewChatPath } from "@/lib/utils";
import { sidebarSelectedMenuItemClassName } from "./sidebarStyles";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../ui/alertDialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

export function AppSidebar({
  canManageKnowledgeBases,
  canViewPermissions,
  user,
}: {
  canManageKnowledgeBases: boolean;
  canViewPermissions: boolean;
  user: User | undefined;
}) {
  const router = useRouter();
  const { t } = useTranslation();
  const { setOpenMobile, toggleSidebar } = useSidebar();
  const queryClient = useQueryClient();
  const identity = useBackendIdentity(user?.id);
  const [showDeleteAllDialog, setShowDeleteAllDialog] = useState(false);

  const closeMobile = useCallback(() => {
    setOpenMobile(false);
  }, [setOpenMobile]);

  const handleToggleSidebar = useCallback(() => {
    toggleSidebar();
  }, [toggleSidebar]);

  const handleNewChat = useCallback(() => {
    setOpenMobile(false);
    router.push(getNewChatPath());
  }, [router, setOpenMobile]);

  const handleShowDeleteAllDialog = useCallback(() => {
    setShowDeleteAllDialog(true);
  }, []);

  const handleDeleteAll = useCallback(() => {
    setShowDeleteAllDialog(false);
    router.replace("/");
    const historyQueryKey = backendQueryKeys.chatHistory(identity);
    queryClient.setQueryData<InfiniteData<ChatHistory>>(
      historyQueryKey,
      (historyData) =>
        historyData
          ? {
              ...historyData,
              pages: historyData.pages.map(() => ({
                chats: [],
                hasMore: false,
              })),
            }
          : historyData
    );
    queryClient.setQueryData<ChatHistoryEntry[]>(
      getLocalChatHistoryQueryKey(historyQueryKey),
      []
    );

    requestBackend(`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/history`, {
      method: "DELETE",
    }).catch(() => undefined);

    toast.success(t("sidebar.allChatsDeleted"));
  }, [identity, queryClient, router, t]);

  return (
    <>
      <Sidebar collapsible="icon">
        <SidebarHeader className="pb-0 pt-3">
          <SidebarMenu>
            <SidebarMenuItem className="flex flex-row items-center justify-between">
              <div className="group/logo relative flex items-center justify-center">
                <SidebarMenuButton
                  asChild
                  className="size-8 !px-0 items-center justify-center group-data-[collapsible=icon]:group-hover/logo:opacity-0"
                  tooltip={t("app.name")}
                >
                  <Link href="/" onClick={closeMobile}>
                    <MessageSquareIcon className="size-4 text-sidebar-foreground/50" />
                  </Link>
                </SidebarMenuButton>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <SidebarMenuButton
                      className="pointer-events-none absolute inset-0 size-8 opacity-0 group-data-[collapsible=icon]:pointer-events-auto group-data-[collapsible=icon]:group-hover/logo:opacity-100"
                      onClick={handleToggleSidebar}
                    >
                      <PanelLeftIcon className="size-4" />
                    </SidebarMenuButton>
                  </TooltipTrigger>
                  <TooltipContent className="hidden md:block" side="right">
                    {t("sidebar.open")}
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="group-data-[collapsible=icon]:hidden">
                <SidebarTrigger className="text-sidebar-foreground/60 transition-colors duration-150 hover:text-sidebar-foreground" />
              </div>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup className="pt-1">
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    className={sidebarSelectedMenuItemClassName}
                    onClick={handleNewChat}
                    tooltip={t("sidebar.newChat")}
                  >
                    <PenSquareIcon className="size-4" />
                    <span className="font-medium">{t("sidebar.newChat")}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                {canViewPermissions ? (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      asChild
                      className="rounded-lg text-sidebar-foreground/60 transition-colors duration-150 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                      onClick={closeMobile}
                      tooltip={t("sidebar.permissions")}
                    >
                      <Link href="/settings/members">
                        <ShieldCheckIcon className="size-4" />
                        <span className="text-[13px]">{t("sidebar.permissions")}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ) : null}
                {canManageKnowledgeBases ? (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      asChild
                      className="rounded-lg text-sidebar-foreground/60 transition-colors duration-150 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                      onClick={closeMobile}
                      tooltip={t("sidebar.knowledgeAccess")}
                    >
                      <Link href="/settings/knowledge-bases">
                        <KeyRoundIcon className="size-4" />
                        <span className="text-[13px]">{t("sidebar.knowledgeAccess")}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ) : null}
                {canManageKnowledgeBases ? (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      asChild
                      className="rounded-lg text-sidebar-foreground/60 transition-colors duration-150 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                      onClick={closeMobile}
                      tooltip={t("sidebar.knowledgeFiles")}
                    >
                      <Link href="/settings/knowledge-bases/files">
                        <FilesIcon className="size-4" />
                        <span className="text-[13px]">{t("sidebar.knowledgeFiles")}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ) : null}
                {user ? (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      className="rounded-lg text-sidebar-foreground/40 transition-colors duration-150 hover:bg-destructive/10 hover:text-destructive"
                      onClick={handleShowDeleteAllDialog}
                      tooltip={t("sidebar.deleteAll")}
                    >
                      <TrashIcon className="size-4" />
                      <span className="text-[13px]">{t("sidebar.deleteAll")}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ) : null}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
          <SidebarHistory user={user} />
        </SidebarContent>
        <SidebarFooter className="border-t border-sidebar-border pt-2 pb-3">
          {user ? <SidebarUserNav user={user} /> : null}
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>

      <AlertDialog
        onOpenChange={setShowDeleteAllDialog}
        open={showDeleteAllDialog}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("sidebar.deleteAllTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("sidebar.deleteAllDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteAll}>
              {t("common.deleteAll")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
