export function softNavigateToChatId(
  chatId: string,
  chatHistoryEnabled: boolean,
): void {
  if (!chatHistoryEnabled) {
    return;
  }

  const nextPath = `/chat/${chatId}`;
  if (window.location.pathname === nextPath) {
    return;
  }

  window.history.pushState({}, '', nextPath);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
