export const CHAT_ACTIVE_TURN_EVENT = 'chat-active-turn-change';

export type ChatActiveTurnDetail = {
  chatId: string;
  turnId: string | null;
};

export function dispatchActiveTurnChange(detail: ChatActiveTurnDetail): void {
  window.dispatchEvent(
    new CustomEvent<ChatActiveTurnDetail>(CHAT_ACTIVE_TURN_EVENT, { detail }),
  );
}
