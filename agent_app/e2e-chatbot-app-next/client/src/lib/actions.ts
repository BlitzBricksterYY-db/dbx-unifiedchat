import { fetchWithErrorHandlers } from './utils';
import type { VisibilityType } from '@chat-template/core';

export async function updateChatVisibility({
  chatId,
  visibility,
}: {
  chatId: string;
  visibility: VisibilityType;
}) {
  const response = await fetchWithErrorHandlers(
    `/api/chat/${chatId}/visibility`,
    {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({ visibility }),
    },
  );

  return response.json();
}

export async function updateMessage({
  messageId,
  text,
}: {
  messageId: string;
  text: string;
}) {
  const response = await fetchWithErrorHandlers(
    `/api/messages/${messageId}`,
    {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({ text }),
    },
  );

  if (response.status === 204) {
    return null;
  }

  return response.json();
}
