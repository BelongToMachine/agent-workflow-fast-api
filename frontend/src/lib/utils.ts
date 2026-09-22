import type {
  UIMessage,
  UIMessagePart,
} from 'ai';
import { type ClassValue, clsx } from 'clsx';
import { formatISO } from 'date-fns';
import { twMerge } from 'tailwind-merge';
import { apiFetch } from './backend/directClient';
import type { DBMessage, Document } from '@/lib/db/schema';
import { ChatbotError, type ErrorCode } from './errors';
import type { ChatMessage, ChatTools, CustomUIDataTypes } from './types';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const fetcher = async (url: string) => {
  const response = await apiFetch(url);

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      cause?: string;
      code?: string;
      detail?: string;
      message?: string;
      requestId?: string;
    } | null;
    const error = new ChatbotError(
      (payload?.code ?? 'offline:chat') as ErrorCode,
      payload?.cause ?? payload?.message ?? payload?.detail
    );
    error.requestId = payload?.requestId;
    throw error;
  }

  return response.json();
};

export async function fetchWithErrorHandlers(
  input: RequestInfo | URL,
  init?: RequestInit,
) {
  try {
    const response = await apiFetch(input, init);

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as {
        cause?: string;
        code?: string;
        detail?: string;
        message?: string;
        requestId?: string;
      } | null;
      const error = new ChatbotError(
        (payload?.code ?? 'offline:chat') as ErrorCode,
        payload?.cause ?? payload?.message ?? payload?.detail
      );
      error.requestId = payload?.requestId;
      throw error;
    }

    return response;
  } catch (error: unknown) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      throw new ChatbotError('offline:chat');
    }

    throw error;
  }
}

export function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function getNewChatPath(): string {
  return `/?new=${generateUUID()}`;
}

export function getDocumentTimestampByIndex(
  documents: Document[],
  index: number,
) {
  if (!documents) { return new Date(); }
  if (index > documents.length) { return new Date(); }

  return documents[index].createdAt;
}

export function sanitizeText(text: string) {
  return text
    .replace('<has_function_call>', '')
    .replace(
      /\\?<｜｜DSML｜｜tool_calls>[\s\S]*?(?:\\?<\/｜｜DSML｜｜tool_calls>|$)/gu,
      '',
    )
    .replace(
      /\\?<｜｜DSML｜｜invoke[^>]*>[\s\S]*?(?:\\?<\/｜｜DSML｜｜invoke>|$)/gu,
      '',
    );
}

export function hasToolControlSyntax(text: string) {
  return text.includes('<｜｜DSML｜｜') || text.includes('</｜｜DSML｜｜');
}

export function convertToUIMessages(messages: DBMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role as 'user' | 'assistant' | 'system',
    parts: message.parts as UIMessagePart<CustomUIDataTypes, ChatTools>[],
    metadata: {
      createdAt: formatISO(message.createdAt),
    },
  }));
}

export function getTextFromMessage(message: ChatMessage | UIMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => (part as { type: 'text'; text: string}).text)
    .join('');
}
