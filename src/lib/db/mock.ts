import { randomUUID } from "node:crypto";
import type { ArtifactKind } from "@/components/chat/artifact";
import type { VisibilityType } from "@/components/chat/visibilitySelector";
import type { Chat, DBMessage, User } from "./schema";

const users = new Map<string, User>();
const chats = new Map<string, Chat>();
const messages = new Map<string, DBMessage[]>();

function now() {
  return new Date();
}

export function mockGetUser(email: string) {
  const found = [...users.values()].filter((item) => item.email === email);
  return Promise.resolve(found);
}

export function mockCreateUser(email: string, password: string) {
  const item: User = {
    createdAt: now(),
    email,
    emailVerified: false,
    id: randomUUID(),
    image: null,
    isAnonymous: false,
    name: null,
    password,
    updatedAt: now(),
  };
  users.set(item.id, item);
  return Promise.resolve([item]);
}

export function mockCreateGuestUser() {
  return mockCreateUser(`guest-${Date.now()}`, randomUUID());
}

export function mockSaveChat(input: {
  id: string;
  userId: string;
  title: string;
  visibility: VisibilityType;
  workspaceId: string;
}) {
  const item: Chat = { ...input, createdAt: now() };
  chats.set(item.id, item);
  messages.set(item.id, []);
  return Promise.resolve([item]);
}

export function mockGetChatById(id: string) {
  return Promise.resolve(chats.get(id) ?? null);
}

export function mockGetChatsByUserId({
  id,
  limit,
}: {
  id: string;
  limit: number;
  startingAfter: string | null;
  endingBefore: string | null;
}) {
  const result = [...chats.values()]
    .filter((item) => item.userId === id)
    .sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())
    .slice(0, limit);
  return Promise.resolve({ chats: result, hasMore: false });
}

export function mockDeleteAllChatsByUserId(userId: string) {
  let deletedCount = 0;
  for (const [id, item] of chats) {
    if (item.userId === userId) {
      chats.delete(id);
      messages.delete(id);
      deletedCount += 1;
    }
  }
  return Promise.resolve({ deletedCount });
}

export function mockSaveMessages(items: DBMessage[]) {
  for (const item of items) {
    const current = messages.get(item.chatId) ?? [];
    const index = current.findIndex((existing) => existing.id === item.id);
    if (index >= 0) {
      current[index] = item;
    } else {
      current.push(item);
    }
    messages.set(item.chatId, current);
  }
  return Promise.resolve(items);
}

export function mockUpdateMessage(id: string, parts: DBMessage["parts"]) {
  for (const items of messages.values()) {
    const item = items.find((message) => message.id === id);
    if (item) {
      item.parts = parts;
    }
  }
  return Promise.resolve();
}

export function mockGetMessagesByChatId(id: string) {
  return Promise.resolve(messages.get(id) ?? []);
}

export function mockGetMessageById(id: string) {
  for (const items of messages.values()) {
    const item = items.find((message) => message.id === id);
    if (item) {
      return Promise.resolve([item]);
    }
  }
  return Promise.resolve([] as DBMessage[]);
}

export function mockDeleteMessagesAfterTimestamp(
  chatId: string,
  timestamp: Date
) {
  const remaining = (messages.get(chatId) ?? []).filter(
    (item) => item.createdAt < timestamp
  );
  messages.set(chatId, remaining);
  return Promise.resolve();
}

export function mockUpdateChatVisibility(
  chatId: string,
  visibility: VisibilityType
) {
  const item = chats.get(chatId);
  if (item) {
    item.visibility = visibility;
  }
  return Promise.resolve();
}

export function mockUpdateChatTitle(chatId: string, title: string) {
  const item = chats.get(chatId);
  if (item) {
    item.title = title;
  }
  return Promise.resolve();
}

export function mockGetMessageCountByUserId(id: string) {
  let count = 0;
  for (const chat of chats.values()) {
    if (chat.userId !== id) {
      continue;
    }
    count += (messages.get(chat.id) ?? []).filter(
      (item) => item.role === "user"
    ).length;
  }
  return Promise.resolve(count);
}

export function mockDeleteChatById(id: string) {
  chats.delete(id);
  messages.delete(id);
  return Promise.resolve();
}

export function mockCreateStreamId() {
  return Promise.resolve();
}

export function mockGetStreamIdsByChatId() {
  return Promise.resolve([] as string[]);
}

export function mockSaveDocument() {
  return Promise.resolve();
}

export function mockDocumentFallback(_input: {
  id: string;
  title: string;
  kind: ArtifactKind;
  content: string;
  userId: string;
}) {
  return Promise.resolve();
}
