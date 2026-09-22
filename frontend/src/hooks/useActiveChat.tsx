import type { UseChatHelpers } from "@ai-sdk/react";
import { useChat } from "@ai-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import { DefaultChatTransport } from "ai";
import { useLocationSearch, usePathname } from "@/lib/router";
import {
createContext,
type Dispatch,
type ReactNode,
type SetStateAction,
useContext,
useCallback,
useEffect,
useMemo,
useRef,
useState,
} from "react";
import { useDataStream } from "@/components/chat/dataStreamProvider";
import { toast } from "@/components/chat/toast";
import type { VisibilityType } from "@/components/chat/visibilitySelector";
import { useAutoResume } from "@/hooks/useAutoResume";
import { getRequestIdFromError, serializeError } from "@/lib/ai/logger";
import { DEFAULT_CHAT_MODEL } from "@/lib/ai/models";
import { upsertChatHistory } from "@/lib/backend/chatHistoryCache";
import { isFastApiDirectMode } from "@/lib/backend/mode";
import {
  backendQueryKeys,
useBackendIdentity,
useBackendQuery,
} from "@/lib/backend/reactQuery";
import { ChatbotError } from "@/lib/errors";
import type { ChatMessage } from "@/lib/types";
import { fetchWithErrorHandlers, generateUUID } from "@/lib/utils";

const useFastApiChat =
process.env.NEXT_PUBLIC_USE_FASTAPI_BACKEND === "1" || isFastApiDirectMode;
const chatApi = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/chat`;

type ActiveChatContextValue = {
chatId: string;
selectedKnowledgeBaseId: string;
setSelectedKnowledgeBaseId: (id: string) => void;
messages: ChatMessage[];
setMessages: UseChatHelpers<ChatMessage>["setMessages"];
sendMessage: UseChatHelpers<ChatMessage>["sendMessage"];
status: UseChatHelpers<ChatMessage>["status"];
stop: UseChatHelpers<ChatMessage>["stop"];
regenerate: UseChatHelpers<ChatMessage>["regenerate"];
addToolApprovalResponse: UseChatHelpers<ChatMessage>["addToolApprovalResponse"];
input: string;
setInput: Dispatch<SetStateAction<string>>;
visibilityType: VisibilityType;
isReadonly: boolean;
isLoading: boolean;
currentModelId: string;
setCurrentModelId: (id: string) => void;
showCreditCardAlert: boolean;
setShowCreditCardAlert: Dispatch<SetStateAction<boolean>>;
};

type ChatMessagesResponse = {
isReadonly: boolean;
messages: ChatMessage[];
userId: string | null;
visibility: VisibilityType;
};

const ActiveChatContext = createContext<ActiveChatContextValue | null>(null);

function extractChatId(pathname: string): string | null {
const match = pathname.match(/\/chat\/([^/]+)/);
return match ? match[1] : null;
}

function readKnowledgeBaseSelection(chatId: string): string {
if (typeof window === "undefined") {
  return "";
}
try {
  return window.localStorage.getItem(`chat-knowledge-base:v1:${chatId}`) ?? "";
} catch {
  return "";
}
}

export function ActiveChatProvider({ children }: { children: ReactNode }) {
const pathname = usePathname();
const locationSearch = useLocationSearch();
const { setDataStream, setWaitingStatus } = useDataStream();
const queryClient = useQueryClient();
const identity = useBackendIdentity();

const chatIdFromUrl = extractChatId(pathname);
const isNewChat = !chatIdFromUrl;
const newChatIdRef = useRef(generateUUID());
const newChatRequestId = new URLSearchParams(locationSearch).get("new");
const navigationKey = isNewChat
? `new:${newChatRequestId ?? ""}`
: `chat:${chatIdFromUrl}`;
const previousNavigationKeyRef = useRef(navigationKey);

if (previousNavigationKeyRef.current !== navigationKey) {
previousNavigationKeyRef.current = navigationKey;
if (isNewChat) {
  newChatIdRef.current = generateUUID();
}
}

const chatId = chatIdFromUrl ?? newChatIdRef.current;
const [knowledgeBaseSelection, setKnowledgeBaseSelection] = useState(() => ({
chatId,
id: readKnowledgeBaseSelection(chatId),
}));
const selectedKnowledgeBaseId =
knowledgeBaseSelection.chatId === chatId
  ? knowledgeBaseSelection.id
  : readKnowledgeBaseSelection(chatId);
const selectedKnowledgeBaseIdRef = useRef({
chatId,
id: selectedKnowledgeBaseId,
});
if (selectedKnowledgeBaseIdRef.current.chatId !== chatId) {
selectedKnowledgeBaseIdRef.current = { chatId, id: selectedKnowledgeBaseId };
}
const updateSelectedKnowledgeBaseId = useCallback(
(id: string) => {
  selectedKnowledgeBaseIdRef.current = { chatId, id };
  setKnowledgeBaseSelection({ chatId, id });
  try {
    if (id) {
      window.localStorage.setItem(`chat-knowledge-base:v1:${chatId}`, id);
    } else {
      window.localStorage.removeItem(`chat-knowledge-base:v1:${chatId}`);
    }
  } catch {
    // The active chat can still use its in-memory selection when storage is unavailable.
  }
},
[chatId]
);
const locallyCreatedChatIdsRef = useRef(new Set<string>());
useEffect(() => {
if (isNewChat) {
  locallyCreatedChatIdsRef.current.add(chatId);
}
}, [chatId, isNewChat]);

const [currentModelId, setCurrentModelId] = useState(DEFAULT_CHAT_MODEL);
const currentModelIdRef = useRef(currentModelId);
useEffect(() => {
currentModelIdRef.current = currentModelId;
}, [currentModelId]);

const [input, setInput] = useState("");
const [showCreditCardAlert, setShowCreditCardAlert] = useState(false);

const { data: chatData, isLoading } = useBackendQuery<ChatMessagesResponse>({
enabled: !isNewChat,
path: `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/messages?chatId=${chatId}`,
queryKey: backendQueryKeys.chatMessages(identity, chatId),
});

const initialMessages: ChatMessage[] = isNewChat
? []
: (chatData?.messages ?? []);
const visibility: VisibilityType = isNewChat
? "private"
: (chatData?.visibility ?? "private");

const {
messages,
setMessages,
sendMessage,
status,
stop,
regenerate,
resumeStream,
addToolApprovalResponse,
} = useChat<ChatMessage>({
generateId: generateUUID,
id: chatId,
messages: initialMessages,
onData: (dataPart) => {
  if (dataPart.type === "data-waiting-status") {
    setWaitingStatus(dataPart.data);
    return;
  }
  setDataStream((ds) => (ds ? [...ds, dataPart] : []));
},
onError: (error) => {
  const requestId =
    (error instanceof ChatbotError ? error.requestId : undefined) ??
    getRequestIdFromError(error);
  if (process.env.NODE_ENV !== "production") {
    console.warn("[ai-agent] chat.client.error", {
      ...serializeError(error),
      requestId,
    });
  }

  const errorMessage = error.message || "Oops, an error occurred!";
  const reference =
    requestId && !errorMessage.includes(requestId)
      ? ` Reference: ${requestId}`
      : "";

  if (error.message?.includes("AI Gateway requires a valid credit card")) {
    setShowCreditCardAlert(true);
  } else if (error instanceof ChatbotError) {
    toast({
      description: `${error.message}${reference}`,
      type: "error",
    });
  } else {
    toast({
      description: `${errorMessage}${reference}`,
      type: "error",
    });
  }
},
onFinish: ({ messages: finishedMessages }) => {
  if (!locallyCreatedChatIdsRef.current.delete(chatId)) {
    return;
  }

  const firstUserMessage = finishedMessages.find(
    (message) => message.role === "user"
  );
  const title = firstUserMessage?.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("")
    .trim()
    .replace(/\n/g, " ")
    .slice(0, 80);

  upsertChatHistory(
    queryClient,
    backendQueryKeys.chatHistory(identity),
    {
      createdAt: new Date(),
      id: chatId,
      title: title || "New chat",
      userId: identity,
      visibility,
    }
  );
},
sendAutomaticallyWhen: ({ messages: currentMessages }) => {
  const lastMessage = currentMessages.at(-1);
  return (
    lastMessage?.parts?.some(
      (part) =>
        "state" in part &&
        part.state === "approval-responded" &&
        "approval" in part &&
        (part.approval as { approved?: boolean })?.approved === true
    ) ?? false
  );
},
transport: new DefaultChatTransport({
  api: chatApi,
  fetch: fetchWithErrorHandlers,
  prepareSendMessagesRequest(request) {
    const lastMessage = request.messages.at(-1);
    const isToolApprovalContinuation =
      lastMessage?.role !== "user" ||
      request.messages.some((msg) =>
        msg.parts?.some((part) => {
          const { state } = part as { state?: string };
          return (
            state === "approval-responded" || state === "output-denied"
          );
        })
      );

    return {
      body: {
        id: request.id,
        ...(useFastApiChat
          ? { messages: request.messages }
          : isToolApprovalContinuation
            ? { messages: request.messages }
            : { message: lastMessage }),
        selectedChatModel: currentModelIdRef.current,
        selectedKnowledgeBaseId: selectedKnowledgeBaseIdRef.current.id || null,
        selectedVisibilityType: visibility,
        ...request.body,
      },
    };
  },
}),
});

useEffect(() => {
if (status === "submitted" || status === "ready" || status === "error") {
  setWaitingStatus(undefined);
}
}, [status, setWaitingStatus]);

const loadedChatIds = useRef(new Set<string>());

if (isNewChat && !loadedChatIds.current.has(newChatIdRef.current)) {
loadedChatIds.current.add(newChatIdRef.current);
}

useEffect(() => {
if (loadedChatIds.current.has(chatId)) {
  return;
}
if (chatData?.messages) {
  loadedChatIds.current.add(chatId);
  setMessages(chatData.messages);
}
}, [chatId, chatData?.messages, setMessages]);

const prevChatIdRef = useRef(chatId);
useEffect(() => {
if (prevChatIdRef.current !== chatId) {
  prevChatIdRef.current = chatId;
  if (isNewChat) {
    setMessages([]);
  }
}
}, [chatId, isNewChat, setMessages]);

useEffect(() => {
if (chatData && !isNewChat) {
  const cookieModel = document.cookie
    .split("; ")
    .find((row) => row.startsWith("chat-model="))
    ?.split("=")[1];
  if (cookieModel) {
    setCurrentModelId(decodeURIComponent(cookieModel));
  }
}
}, [chatData, isNewChat]);

const hasAppendedQueryRef = useRef(false);
useEffect(() => {
const params = new URLSearchParams(window.location.search);
const query = params.get("query");
if (query && !hasAppendedQueryRef.current) {
  hasAppendedQueryRef.current = true;
  window.history.replaceState(
    {},
    "",
    `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/chat/${chatId}`
  );
  sendMessage({
    parts: [{ text: query, type: "text" }],
    role: "user" as const,
  });
}
}, [sendMessage, chatId]);

useAutoResume({
autoResume: !isNewChat && !!chatData,
initialMessages,
resumeStream,
setMessages,
});

const isReadonly = isNewChat ? false : (chatData?.isReadonly ?? false);

const value = useMemo<ActiveChatContextValue>(
() => ({
  addToolApprovalResponse,
  chatId,
  selectedKnowledgeBaseId,
  setSelectedKnowledgeBaseId: updateSelectedKnowledgeBaseId,
  currentModelId,
  input,
  isLoading: !isNewChat && isLoading,
  isReadonly,
  messages,
  regenerate,
  sendMessage,
  setCurrentModelId,
  setInput,
  setMessages,
  setShowCreditCardAlert,
  showCreditCardAlert,
  status,
  stop,
  visibilityType: visibility,
}),
[
  chatId,
  selectedKnowledgeBaseId,
  updateSelectedKnowledgeBaseId,
  messages,
  setMessages,
  sendMessage,
  status,
  stop,
  regenerate,
  addToolApprovalResponse,
  input,
  visibility,
  isReadonly,
  isNewChat,
  isLoading,
  currentModelId,
  showCreditCardAlert,
]
);

return (
<ActiveChatContext.Provider value={value}>
  {children}
</ActiveChatContext.Provider>
);
}

export function useActiveChat() {
const context = useContext(ActiveChatContext);
if (!context) {
throw new Error("useActiveChat must be used within ActiveChatProvider");
}
return context;
}
