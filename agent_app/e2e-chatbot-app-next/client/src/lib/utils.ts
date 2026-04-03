import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import type { ChatMessage } from '@chat-template/core';
import { ChatSDKError, type ErrorCode } from '@chat-template/core/errors';
import type { DBMessage } from '@chat-template/db';
import { formatISO } from 'date-fns';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function convertToUIMessages(messages: DBMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role as 'user' | 'assistant' | 'system',
    parts: message.parts as ChatMessage['parts'],
    metadata: {
      createdAt: formatISO(message.createdAt),
    },
  }));
}

export async function fetcher<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    credentials: 'include',
  });

  if (!response.ok) {
    const parsedResponse = await response.json();
    const { code, cause } = parsedResponse;
    throw new ChatSDKError(code as ErrorCode, cause);
  }

  if (response.status === 204) {
    return { chats: [], hasMore: false } as T;
  }

  return response.json() as Promise<T>;
}

export async function fetchWithErrorHandlers(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  try {
    const response = await fetch(input, {
      credentials: 'include',
      ...init,
    });

    if (!response.ok) {
      const parsedResponse = await response.json();
      const { code, cause } = parsedResponse;
      throw new ChatSDKError(code as ErrorCode, cause);
    }

    return response;
  } catch (error: unknown) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      throw new ChatSDKError('offline:chat');
    }

    throw error;
  }
}

export function getTextFromMessage(message: ChatMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join('');
}

export function sanitizeText(text: string): string {
  return text.replace('<has_function_call>', '').replace(/\u0000/g, '');
}
