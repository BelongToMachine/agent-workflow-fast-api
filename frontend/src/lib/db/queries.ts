import "server-only";

import {
  and,
  asc,
  count,
  desc,
  eq,
  gt,
  gte,
  inArray,
  lt,
  type SQL,
} from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import type { ArtifactKind } from "@/components/chat/artifact";
import type { VisibilityType } from "@/components/chat/visibilitySelector";
import { isMockDatabase } from "../constants";
import { ChatbotError } from "../errors";
import { generateUUID } from "../utils";
import {
  mockCreateGuestUser,
  mockCreateUser,
  mockDeleteAllChatsByUserId,
  mockDeleteChatById,
  mockDeleteMessagesAfterTimestamp,
  mockGetChatById,
  mockGetChatsByUserId,
  mockGetMessageById,
  mockGetMessageCountByUserId,
  mockGetMessagesByChatId,
  mockGetStreamIdsByChatId,
  mockGetUser,
  mockSaveChat,
  mockSaveMessages,
  mockUpdateChatTitle,
  mockUpdateChatVisibility,
  mockUpdateMessage,
} from "./mock";
import {
  type Chat,
  chat,
  type DBMessage,
  document,
  message,
  type Suggestion,
  stream,
  suggestion,
  type User,
  user,
} from "./schema";
import { generateHashedPassword } from "./utils";
import { ensureDefaultWorkspaceMembership } from "./workspaceQueries";

// Keep the real PostgreSQL client out of the module initialization path in
// mock mode. This allows the app to run without POSTGRES_URL.
const db = isMockDatabase
  ? (undefined as never)
  : drizzle(postgres(process.env.POSTGRES_URL ?? ""));

export async function getUser(email: string): Promise<User[]> {
  if (isMockDatabase) {
    return mockGetUser(email);
  }
  try {
    return await db.select().from(user).where(eq(user.email, email));
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function createUser(email: string, password: string) {
  if (isMockDatabase) {
    return mockCreateUser(email, generateHashedPassword(password));
  }
  const hashedPassword = generateHashedPassword(password);

  try {
    const [createdUser] = await db
      .insert(user)
      .values({ email, password: hashedPassword })
      .returning();

    if (createdUser) {
      await ensureDefaultWorkspaceMembership(createdUser.id, "editor");
    }

    return createdUser;
  } catch (error) {
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function createGuestUser() {
  if (isMockDatabase) {
    return mockCreateGuestUser();
  }
  const email = `guest-${Date.now()}`;
  const password = generateHashedPassword(generateUUID());

  try {
    const [createdUser] = await db
      .insert(user)
      .values({ email, isAnonymous: true, password })
      .returning({
        email: user.email,
        id: user.id,
      });

    if (createdUser) {
      await ensureDefaultWorkspaceMembership(createdUser.id, "viewer");
    }

    return createdUser ? [createdUser] : [];
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function saveChat({
  id,
  userId,
  title,
  visibility,
  workspaceId,
}: {
  id: string;
  userId: string;
  title: string;
  visibility: VisibilityType;
  workspaceId: string;
}) {
  if (isMockDatabase) {
    return mockSaveChat({ id, title, userId, visibility, workspaceId });
  }
  try {
    return await db.insert(chat).values({
      createdAt: new Date(),
      id,
      title,
      userId,
      visibility,
      workspaceId,
    });
  } catch (error) {
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function deleteChatById({ id }: { id: string }) {
  if (isMockDatabase) {
    return mockDeleteChatById(id);
  }
  try {
    await db.delete(message).where(eq(message.chatId, id));
    await db.delete(stream).where(eq(stream.chatId, id));

    const [chatsDeleted] = await db
      .delete(chat)
      .where(eq(chat.id, id))
      .returning();
    return chatsDeleted;
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function deleteAllChatsByUserId({
  userId,
  workspaceId,
}: {
  userId: string;
  workspaceId: string;
}) {
  if (isMockDatabase) {
    return mockDeleteAllChatsByUserId(userId);
  }
  try {
    const userChats = await db
      .select({ id: chat.id })
      .from(chat)
      .where(
        and(eq(chat.userId, userId), eq(chat.workspaceId, workspaceId))
      );

    if (userChats.length === 0) {
      return { deletedCount: 0 };
    }

    const chatIds = userChats.map((c) => c.id);

    await db.delete(message).where(inArray(message.chatId, chatIds));
    await db.delete(stream).where(inArray(stream.chatId, chatIds));

    const deletedChats = await db
      .delete(chat)
      .where(
        and(eq(chat.userId, userId), eq(chat.workspaceId, workspaceId))
      )
      .returning();

    return { deletedCount: deletedChats.length };
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function getChatsByUserId({
  id,
  limit,
  startingAfter,
  endingBefore,
  workspaceId,
}: {
  id: string;
  limit: number;
  startingAfter: string | null;
  endingBefore: string | null;
  workspaceId: string;
}) {
  if (isMockDatabase) {
    return mockGetChatsByUserId({ endingBefore, id, limit, startingAfter });
  }
  try {
    const extendedLimit = limit + 1;

    const query = (whereCondition?: SQL<unknown>) =>
      db
        .select()
        .from(chat)
        .where(
          whereCondition
            ? and(
                whereCondition,
                eq(chat.userId, id),
                eq(chat.workspaceId, workspaceId)
              )
            : and(eq(chat.userId, id), eq(chat.workspaceId, workspaceId))
        )
        .orderBy(desc(chat.createdAt))
        .limit(extendedLimit);

    let filteredChats: Chat[] = [];

    if (startingAfter) {
      const [selectedChat] = await db
        .select()
        .from(chat)
        .where(
          and(
            eq(chat.id, startingAfter),
            eq(chat.userId, id),
            eq(chat.workspaceId, workspaceId)
          )
        )
        .limit(1);

      if (!selectedChat) {
        throw new ChatbotError(
          "not_found:database",
          `Chat with id ${startingAfter} not found`
        );
      }

      filteredChats = await query(gt(chat.createdAt, selectedChat.createdAt));
    } else if (endingBefore) {
      const [selectedChat] = await db
        .select()
        .from(chat)
        .where(
          and(
            eq(chat.id, endingBefore),
            eq(chat.userId, id),
            eq(chat.workspaceId, workspaceId)
          )
        )
        .limit(1);

      if (!selectedChat) {
        throw new ChatbotError(
          "not_found:database",
          `Chat with id ${endingBefore} not found`
        );
      }

      filteredChats = await query(lt(chat.createdAt, selectedChat.createdAt));
    } else {
      filteredChats = await query();
    }

    const hasMore = filteredChats.length > limit;

    return {
      chats: hasMore ? filteredChats.slice(0, limit) : filteredChats,
      hasMore,
    };
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function getChatById({ id }: { id: string }) {
  if (isMockDatabase) {
    return mockGetChatById(id);
  }
  try {
    const [selectedChat] = await db.select().from(chat).where(eq(chat.id, id));
    if (!selectedChat) {
      return null;
    }

    return selectedChat;
  } catch (error) {
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function saveMessages({ messages }: { messages: DBMessage[] }) {
  if (isMockDatabase) {
    return mockSaveMessages(messages);
  }
  try {
    return await db.insert(message).values(messages);
  } catch (error) {
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function updateMessage({
  id,
  parts,
}: {
  id: string;
  parts: DBMessage["parts"];
}) {
  if (isMockDatabase) {
    return mockUpdateMessage(id, parts);
  }
  try {
    return await db.update(message).set({ parts }).where(eq(message.id, id));
  } catch (error) {
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function getMessagesByChatId({ id }: { id: string }) {
  if (isMockDatabase) {
    return mockGetMessagesByChatId(id);
  }
  try {
    return await db
      .select()
      .from(message)
      .where(eq(message.chatId, id))
      .orderBy(asc(message.createdAt));
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function saveDocument({
  id,
  title,
  kind,
  content,
  userId,
  workspaceId,
}: {
  id: string;
  title: string;
  kind: ArtifactKind;
  content: string;
  userId: string;
  workspaceId: string;
}) {
  try {
    return await db
      .insert(document)
      .values({
        content,
        createdAt: new Date(),
        id,
        kind,
        title,
        userId,
        workspaceId,
      })
      .returning();
  } catch (error) {
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function updateDocumentContent({
  id,
  content,
  userId,
}: {
  id: string;
  content: string;
  userId: string;
}) {
  try {
    const docs = await db
      .select()
      .from(document)
      .where(and(eq(document.id, id), eq(document.userId, userId)))
      .orderBy(desc(document.createdAt))
      .limit(1);

    const [latest] = docs;
    if (!latest) {
      throw new ChatbotError("not_found:database", "Document not found");
    }

    return await db
      .update(document)
      .set({ content })
      .where(
        and(
          eq(document.id, id),
          eq(document.createdAt, latest.createdAt),
          eq(document.userId, userId)
        )
      )
      .returning();
  } catch (error) {
    if (error instanceof ChatbotError) {
      throw error;
    }
    throw new ChatbotError("bad_request:database", {
      cause: error,
    });
  }
}

export async function getDocumentsById({
  id,
  userId,
}: {
  id: string;
  userId?: string;
}) {
  try {
    const documents = await db
      .select()
      .from(document)
      .where(
        and(
          eq(document.id, id),
          userId ? eq(document.userId, userId) : undefined
        )
      )
      .orderBy(asc(document.createdAt));

    return documents;
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function getDocumentById({ id }: { id: string }) {
  try {
    const [selectedDocument] = await db
      .select()
      .from(document)
      .where(eq(document.id, id))
      .orderBy(desc(document.createdAt));

    return selectedDocument;
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function deleteDocumentsByIdAfterTimestamp({
  id,
  timestamp,
  userId,
}: {
  id: string;
  timestamp: Date;
  userId: string;
}) {
  try {
    await db
      .delete(suggestion)
      .where(
        and(
          eq(suggestion.documentId, id),
          gt(suggestion.documentCreatedAt, timestamp)
        )
      );

    return await db
      .delete(document)
      .where(
        and(
          eq(document.id, id),
          eq(document.userId, userId),
          gt(document.createdAt, timestamp)
        )
      )
      .returning();
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function saveSuggestions({
  suggestions,
}: {
  suggestions: Suggestion[];
}) {
  try {
    return await db.insert(suggestion).values(suggestions);
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function getSuggestionsByDocumentId({
  documentId,
}: {
  documentId: string;
}) {
  try {
    return await db
      .select()
      .from(suggestion)
      .where(eq(suggestion.documentId, documentId));
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function getMessageById({ id }: { id: string }) {
  if (isMockDatabase) {
    return mockGetMessageById(id);
  }
  try {
    return await db.select().from(message).where(eq(message.id, id));
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function deleteMessagesByChatIdAfterTimestamp({
  chatId,
  timestamp,
}: {
  chatId: string;
  timestamp: Date;
}) {
  if (isMockDatabase) {
    return mockDeleteMessagesAfterTimestamp(chatId, timestamp);
  }
  try {
    const messagesToDelete = await db
      .select({ id: message.id })
      .from(message)
      .where(
        and(eq(message.chatId, chatId), gte(message.createdAt, timestamp))
      );

    const messageIds = messagesToDelete.map(
      (currentMessage) => currentMessage.id
    );

    if (messageIds.length > 0) {
      return await db
        .delete(message)
        .where(
          and(eq(message.chatId, chatId), inArray(message.id, messageIds))
        );
    }
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function updateChatVisibilityById({
  chatId,
  visibility,
}: {
  chatId: string;
  visibility: "private" | "public";
}) {
  if (isMockDatabase) {
    return mockUpdateChatVisibility(chatId, visibility);
  }
  try {
    return await db.update(chat).set({ visibility }).where(eq(chat.id, chatId));
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function updateChatTitleById({
  chatId,
  title,
}: {
  chatId: string;
  title: string;
}) {
  if (isMockDatabase) {
    return mockUpdateChatTitle(chatId, title);
  }
  try {
    return await db.update(chat).set({ title }).where(eq(chat.id, chatId));
  } catch {
    // Best effort title update.
  }
}

export async function getMessageCountByUserId({
  id,
  differenceInHours,
}: {
  id: string;
  differenceInHours: number;
}) {
  if (isMockDatabase) {
    return mockGetMessageCountByUserId(id);
  }
  try {
    const cutoffTime = new Date(
      Date.now() - differenceInHours * 60 * 60 * 1000
    );

    const [stats] = await db
      .select({ count: count(message.id) })
      .from(message)
      .innerJoin(chat, eq(message.chatId, chat.id))
      .where(
        and(
          eq(chat.userId, id),
          gte(message.createdAt, cutoffTime),
          eq(message.role, "user")
        )
      )
      .execute();

    return stats?.count ?? 0;
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function createStreamId({
  streamId,
  chatId,
}: {
  streamId: string;
  chatId: string;
}) {
  try {
    await db
      .insert(stream)
      .values({ chatId, createdAt: new Date(), id: streamId });
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}

export async function getStreamIdsByChatId({ chatId }: { chatId: string }) {
  if (isMockDatabase) {
    return mockGetStreamIdsByChatId();
  }
  try {
    const streamIds = await db
      .select({ id: stream.id })
      .from(stream)
      .where(eq(stream.chatId, chatId))
      .orderBy(asc(stream.createdAt))
      .execute();

    return streamIds.map(({ id }) => id);
  } catch (error) {
    throw new ChatbotError("bad_request:database", { cause: error });
  }
}
