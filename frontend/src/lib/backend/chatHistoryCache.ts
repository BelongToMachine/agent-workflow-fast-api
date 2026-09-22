import type { InfiniteData, QueryClient, QueryKey } from "@tanstack/react-query";

export type ChatHistoryEntry = {
  createdAt: Date | string;
  id: string;
  title: string;
  userId?: string;
  visibility: "private" | "public";
  workspaceId?: string;
};

export type ChatHistory = {
  chats: ChatHistoryEntry[];
  hasMore: boolean;
};

type UpsertChatHistoryOptions = {
  replaceExistingTitle?: boolean;
};

export function getLocalChatHistoryQueryKey(queryKey: QueryKey) {
  return [...queryKey, "local"] as const;
}

function mergeChatHistoryEntry(
  existingChat: ChatHistoryEntry,
  chat: ChatHistoryEntry,
  replaceExistingTitle: boolean
) {
  return {
    ...existingChat,
    ...chat,
    createdAt: existingChat.createdAt,
    title:
      replaceExistingTitle || existingChat.title === "New chat"
        ? chat.title
        : existingChat.title,
  };
}

export function upsertChatHistory(
  queryClient: QueryClient,
  queryKey: QueryKey,
  chat: ChatHistoryEntry,
  { replaceExistingTitle = false }: UpsertChatHistoryOptions = {}
) {
  queryClient.setQueryData<ChatHistoryEntry[]>(
    getLocalChatHistoryQueryKey(queryKey),
    (localChats = []) => {
      const existingIndex = localChats.findIndex(
        (existingChat) => existingChat.id === chat.id
      );
      if (existingIndex === -1) {
        return [chat, ...localChats];
      }

      return localChats.map((existingChat, index) =>
        index === existingIndex
          ? mergeChatHistoryEntry(
              existingChat,
              chat,
              replaceExistingTitle
            )
          : existingChat
      );
    }
  );

  queryClient.setQueryData<InfiniteData<ChatHistory, string | null>>(
    queryKey,
    (historyData) => {
      const existingPages = historyData?.pages ?? [];
      let foundExistingChat = false;

      const pages = existingPages.map((page) => ({
        ...page,
        chats: page.chats.map((existingChat) => {
          if (existingChat.id !== chat.id) {
            return existingChat;
          }

          foundExistingChat = true;
          return mergeChatHistoryEntry(
            existingChat,
            chat,
            replaceExistingTitle
          );
        }),
      }));

      if (foundExistingChat) {
        return {
          pageParams: historyData?.pageParams ?? [null],
          pages,
        };
      }

      if (pages.length === 0) {
        return {
          pageParams: [null],
          pages: [{ chats: [chat], hasMore: false }],
        };
      }

      return {
        pageParams: historyData?.pageParams ?? [null],
        pages: [
          {
            ...pages[0],
            chats: [chat, ...pages[0].chats],
          },
          ...pages.slice(1),
        ],
      };
    }
  );
}
