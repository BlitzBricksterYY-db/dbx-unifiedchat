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

/** Fired when the user clicks a sidebar turn link; use when `?turn=` is already that id so the router does not re-run scroll. */
export const CHAT_SCROLL_TO_TURN_EVENT = 'chat-scroll-to-turn';

export type ChatScrollToTurnDetail = {
  chatId: string;
  turnId: string;
};

export function dispatchScrollToTurn(detail: ChatScrollToTurnDetail): void {
  window.dispatchEvent(
    new CustomEvent<ChatScrollToTurnDetail>(CHAT_SCROLL_TO_TURN_EVENT, {
      detail,
    }),
  );
}
