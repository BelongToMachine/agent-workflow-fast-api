"use client";

import {
  type InfiniteData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { isToday, isYesterday, subMonths, subWeeks } from "date-fns";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import type { User } from "@/lib/auth";
import { usePathname, useRouter } from "@/lib/router";
import { type MouseEvent, useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alertDialog";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  backendQueryKeys,
  useBackendIdentity,
  useBackendInfiniteQuery,
} from "@/lib/backend/reactQuery";
import {
  type ChatHistory,
  type ChatHistoryEntry,
  getLocalChatHistoryQueryKey,
} from "@/lib/backend/chatHistoryCache";
import { requestBackend } from "@/lib/backend/request";
import { Spinner } from "../ui/spinner";
import { ChatItem } from "./sidebarHistoryItem";

type GroupedChats = {
  today: ChatHistoryEntry[];
  yesterday: ChatHistoryEntry[];
  lastWeek: ChatHistoryEntry[];
  lastMonth: ChatHistoryEntry[];
  older: ChatHistoryEntry[];
};

const PAGE_SIZE = 20;
const EMPTY_CHAT_HISTORY: ChatHistoryEntry[] = [];

function getChatsFromPage(
  page: ChatHistory | null | undefined
): ChatHistoryEntry[] {
  return Array.isArray(page?.chats) ? page.chats : [];
}

const groupChatsByDate = (chats: ChatHistoryEntry[]): GroupedChats => {
  const now = new Date();
  const oneWeekAgo = subWeeks(now, 1);
  const oneMonthAgo = subMonths(now, 1);

  return chats.reduce(
    (groups, chat) => {
      const chatDate = new Date(chat.createdAt);

      if (isToday(chatDate)) {
        groups.today.push(chat);
      } else if (isYesterday(chatDate)) {
        groups.yesterday.push(chat);
      } else if (chatDate > oneWeekAgo) {
        groups.lastWeek.push(chat);
      } else if (chatDate > oneMonthAgo) {
        groups.lastMonth.push(chat);
      } else {
        groups.older.push(chat);
      }

      return groups;
    },
    {
      lastMonth: [],
      lastWeek: [],
      older: [],
      today: [],
      yesterday: [],
    } as GroupedChats
  );
};

export function SidebarHistory({ user }: { user: User | undefined }) {
  const { t } = useTranslation();
  const { setOpenMobile } = useSidebar();
  const pathname = usePathname();
  const id = pathname?.startsWith("/chat/") ? pathname.split("/")[2] : null;
  const queryClient = useQueryClient();
  const identity = useBackendIdentity(user?.id);
  const historyQueryKey = useMemo(
    () => backendQueryKeys.chatHistory(identity),
    [identity]
  );

  const {
    data: historyData,
    fetchNextPage,
    isFetching,
    isLoading,
  } = useBackendInfiniteQuery<ChatHistory, string | null>({
    enabled: Boolean(user),
    gcTime: 5 * 60_000,
    getNextPageParam: (lastPage) =>
      lastPage?.hasMore
        ? (getChatsFromPage(lastPage).at(-1)?.id ?? undefined)
        : undefined,
    initialPageParam: null,
    path: (endingBefore) => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (endingBefore) {
        params.set("ending_before", endingBefore);
      }
      return `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/history?${params.toString()}`;
    },
    queryKey: historyQueryKey,
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
    staleTime: 30_000,
  });

  const paginatedChatHistories = historyData?.pages;
  const isValidating = isFetching;
  const { data: localChats = EMPTY_CHAT_HISTORY } = useQuery<
    ChatHistoryEntry[]
  >({
    enabled: false,
    queryFn: () =>
      queryClient.getQueryData<ChatHistoryEntry[]>(
        getLocalChatHistoryQueryKey(historyQueryKey)
      ) ?? EMPTY_CHAT_HISTORY,
    queryKey: getLocalChatHistoryQueryKey(historyQueryKey),
  });
  const chatsFromHistory = useMemo(() => {
    const localChatIds = new Set(localChats.map((chat) => chat.id));
    const serverChats = (paginatedChatHistories ?? []).flatMap((page) =>
      getChatsFromPage(page)
    );
    return [
      ...localChats,
      ...serverChats.filter((chat) => !localChatIds.has(chat.id)),
    ];
  }, [localChats, paginatedChatHistories]);
  const groupedChats = useMemo(
    () => groupChatsByDate(chatsFromHistory),
    [chatsFromHistory]
  );

  const router = useRouter();
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  const hasReachedEnd = paginatedChatHistories
    ? paginatedChatHistories.some(
        (page) => page?.hasMore !== true || !Array.isArray(page?.chats)
      )
    : false;

  const hasEmptyChatHistory = !isLoading && chatsFromHistory.length === 0;

  const handleDelete = useCallback(async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (!deleteId || isDeleting) {
      return;
    }

    const chatToDelete = deleteId;
    const isCurrentChat = pathname === `/chat/${chatToDelete}`;
    setIsDeleting(true);

    if (isCurrentChat) {
      router.replace("/");
    }

    queryClient.setQueryData<InfiniteData<ChatHistory>>(
      historyQueryKey,
      (chatHistories) =>
        chatHistories
          ? {
              ...chatHistories,
              pages: chatHistories.pages.map((chatHistory) => ({
                ...chatHistory,
                chats: chatHistory.chats.filter(
                  (chat) => chat.id !== chatToDelete
                ),
              })),
            }
          : chatHistories
    );
    queryClient.setQueryData<ChatHistoryEntry[]>(
      getLocalChatHistoryQueryKey(historyQueryKey),
      (chats) => chats?.filter((chat) => chat.id !== chatToDelete)
    );

    try {
      await requestBackend(
        `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/chat?id=${chatToDelete}`,
        { method: "DELETE" }
      );
      toast.success(t("sidebar.chatDeleted"));
      setShowDeleteDialog(false);
    } catch {
      toast.error(t("common.error"));
    } finally {
      setIsDeleting(false);
    }
  }, [deleteId, historyQueryKey, isDeleting, pathname, queryClient, router, t]);

  const handleShowDeleteDialog = useCallback((chatId: string) => {
    setDeleteId(chatId);
    setShowDeleteDialog(true);
  }, []);

  const handleViewportEnter = useCallback(() => {
    if (!isValidating && !hasReachedEnd) {
      fetchNextPage().catch(() => undefined);
    }
  }, [fetchNextPage, hasReachedEnd, isValidating]);

  if (!user) {
    return (
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupContent>
          <div className="flex w-full flex-row items-center justify-center gap-2 px-2 text-[13px] text-sidebar-foreground/60">
            {t("sidebar.loginToSave")}
          </div>
        </SidebarGroupContent>
      </SidebarGroup>
    );
  }

  if (isLoading && chatsFromHistory.length === 0) {
    return (
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupLabel className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
          {t("sidebar.history")}
        </SidebarGroupLabel>
        <SidebarGroupContent>
          <div
            aria-live="polite"
            className="flex items-center justify-center gap-2 px-2 py-3 text-[11px] text-sidebar-foreground/60"
            role="status"
          >
            <Spinner className="size-3.5" />
            {t("common.loadingShort")}
          </div>
        </SidebarGroupContent>
      </SidebarGroup>
    );
  }

  if (hasEmptyChatHistory) {
    return (
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupLabel className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
          {t("sidebar.history")}
        </SidebarGroupLabel>
        <SidebarGroupContent>
          <div className="flex w-full flex-row items-center justify-center gap-2 px-2 text-[13px] text-sidebar-foreground/60">
            {t("sidebar.emptyHistory")}
          </div>
        </SidebarGroupContent>
      </SidebarGroup>
    );
  }

  return (
    <>
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupLabel className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
          {t("sidebar.history")}
        </SidebarGroupLabel>
        <SidebarGroupContent className="max-h-[35dvh] overflow-y-auto overscroll-contain no-scrollbar md:max-h-none md:overflow-visible">
          <SidebarMenu>
            <div className="flex flex-col gap-4">
              {groupedChats.today.length > 0 && (
                <div>
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
                    {t("sidebar.today")}
                  </div>
                  {groupedChats.today.map((chat) => (
                    <ChatItem
                      chat={chat}
                      isActive={chat.id === id}
                      key={chat.id}
                      onDelete={handleShowDeleteDialog}
                      setOpenMobile={setOpenMobile}
                    />
                  ))}
                </div>
              )}

              {groupedChats.yesterday.length > 0 && (
                <div>
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
                    {t("sidebar.yesterday")}
                  </div>
                  {groupedChats.yesterday.map((chat) => (
                    <ChatItem
                      chat={chat}
                      isActive={chat.id === id}
                      key={chat.id}
                      onDelete={handleShowDeleteDialog}
                      setOpenMobile={setOpenMobile}
                    />
                  ))}
                </div>
              )}

              {groupedChats.lastWeek.length > 0 && (
                <div>
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
                    {t("sidebar.last7Days")}
                  </div>
                  {groupedChats.lastWeek.map((chat) => (
                    <ChatItem
                      chat={chat}
                      isActive={chat.id === id}
                      key={chat.id}
                      onDelete={handleShowDeleteDialog}
                      setOpenMobile={setOpenMobile}
                    />
                  ))}
                </div>
              )}

              {groupedChats.lastMonth.length > 0 && (
                <div>
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
                    {t("sidebar.last30Days")}
                  </div>
                  {groupedChats.lastMonth.map((chat) => (
                    <ChatItem
                      chat={chat}
                      isActive={chat.id === id}
                      key={chat.id}
                      onDelete={handleShowDeleteDialog}
                      setOpenMobile={setOpenMobile}
                    />
                  ))}
                </div>
              )}

              {groupedChats.older.length > 0 && (
                <div>
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/70">
                    {t("sidebar.older")}
                  </div>
                  {groupedChats.older.map((chat) => (
                    <ChatItem
                      chat={chat}
                      isActive={chat.id === id}
                      key={chat.id}
                      onDelete={handleShowDeleteDialog}
                      setOpenMobile={setOpenMobile}
                    />
                  ))}
                </div>
              )}
            </div>
          </SidebarMenu>

          <motion.div onViewportEnter={handleViewportEnter} />

          {hasReachedEnd ? null : (
            <div className="mt-1 flex flex-row items-center gap-2 px-4 py-2 text-sidebar-foreground/50">
              <Spinner className="size-3.5" />
              <div className="text-[11px]">{t("common.loadingShort")}</div>
            </div>
          )}
        </SidebarGroupContent>
      </SidebarGroup>

      <AlertDialog onOpenChange={setShowDeleteDialog} open={showDeleteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("sidebar.deleteChatTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("sidebar.deleteChatDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction disabled={isDeleting} onClick={handleDelete}>
            {isDeleting ? <Spinner /> : null}
            {isDeleting ? t("common.deleting") : t("common.continue")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
