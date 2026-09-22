import {
  type InfiniteData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";
import useSWR from "swr";
import type { VisibilityType } from "@/components/chat/visibilitySelector";
import type { ChatHistory } from "@/lib/backend/chatHistoryCache";
import {
  backendQueryKeys,
  useBackendIdentity,
} from "@/lib/backend/reactQuery";

export function useChatVisibility({
  chatId,
  initialVisibilityType,
}: {
  chatId: string;
  initialVisibilityType: VisibilityType;
}) {
  const queryClient = useQueryClient();
  const identity = useBackendIdentity();
  const { data: historyData } = useQuery<InfiniteData<ChatHistory>>({
    enabled: false,
    queryFn: () =>
      queryClient.getQueryData<InfiniteData<ChatHistory>>(
        backendQueryKeys.chatHistory(identity)
      ) ?? { pageParams: [], pages: [] },
    queryKey: backendQueryKeys.chatHistory(identity),
  });
  const history = useMemo(
    () =>
      historyData
        ? {
            chats: historyData.pages.flatMap((page) =>
              Array.isArray(page?.chats) ? page.chats : []
            ),
            hasMore: historyData.pages.at(-1)?.hasMore ?? false,
          }
        : undefined,
    [historyData]
  );

  const { data: localVisibility, mutate: setLocalVisibility } = useSWR(
    `${chatId}-visibility`,
    null,
    {
      fallbackData: initialVisibilityType,
    }
  );

  const visibilityType = useMemo(() => {
    if (!history) {
      return localVisibility;
    }
    const chat = history.chats.find((currentChat) => currentChat.id === chatId);
    if (!chat) {
      return "private";
    }
    return chat.visibility;
  }, [history, chatId, localVisibility]);

  const setVisibilityType = (updatedVisibilityType: VisibilityType) => {
    setLocalVisibility(updatedVisibilityType);
    void queryClient.invalidateQueries(
      {
        exact: true,
        queryKey: backendQueryKeys.chatHistory(identity),
      },
      { cancelRefetch: false },
    );

    void fetch(`/api/knowledge-bases/${encodeURIComponent(chatId)}`, {
      body: JSON.stringify({ visibility: updatedVisibilityType }),
      headers: { "content-type": "application/json" },
      method: "PATCH",
    });
  };

  return { setVisibilityType, visibilityType };
}
