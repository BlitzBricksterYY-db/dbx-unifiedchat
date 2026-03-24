import { PreviewMessage, AwaitingResponseMessage } from './message';
import { Greeting } from './greeting';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import equal from 'fast-deep-equal';
import type { UseChatHelpers } from '@ai-sdk/react';
import { useMessages } from '@/hooks/use-messages';
import type { ChatMessage, FeedbackMap } from '@chat-template/core';
import { useDataStream } from './data-stream-provider';
import { Conversation, ConversationContent } from './elements/conversation';
import { ArrowDownIcon, ArrowUpIcon, ChevronsUpIcon, ChevronsDownIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface MessagesProps {
  status: UseChatHelpers<ChatMessage>['status'];
  messages: ChatMessage[];
  selectedTurnId?: string | null;
  setMessages: UseChatHelpers<ChatMessage>['setMessages'];
  addToolApprovalResponse: UseChatHelpers<ChatMessage>['addToolApprovalResponse'];
  sendMessage: UseChatHelpers<ChatMessage>['sendMessage'];
  regenerate: UseChatHelpers<ChatMessage>['regenerate'];
  isReadonly: boolean;
  selectedModelId: string;
  feedback?: FeedbackMap;
}

function PureMessages({
  status,
  messages,
  selectedTurnId,
  setMessages,
  addToolApprovalResponse,
  sendMessage,
  regenerate,
  isReadonly,
  selectedModelId,
  feedback = {},
}: MessagesProps) {
  const {
    containerRef: messagesContainerRef,
    endRef: messagesEndRef,
    isAtBottom,
    scrollToBottom,
    hasSentMessage,
  } = useMessages({
    status,
  });

  useDataStream();

  // ── Turn navigation state ──
  const turnRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [activeTurnIndex, setActiveTurnIndex] = useState(-1);
  const userTurns = useMemo(
    () => messages.filter((m) => m.role === 'user'),
    [messages],
  );
  const hasTurns = userTurns.length > 1;

  // Stable navigation target — only updated by button clicks or when scroll settles
  const navTargetRef = useRef(-1);

  // ── Scroll-idle detection: hide controls while scrolling, fade in after 500ms ──
  const [isScrollIdle, setIsScrollIdle] = useState(true);
  const scrollIdleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isAtTop = useRef(true);
  const [atTop, setAtTop] = useState(true);
  const [canScroll, setCanScroll] = useState(false);

  const syncScrollMeta = useCallback(() => {
    const el = messagesContainerRef.current;
    if (!el) return;

    setCanScroll(el.scrollHeight > el.clientHeight + 1);
    const nowAtTop = el.scrollTop <= 10;
    isAtTop.current = nowAtTop;
    setAtTop(nowAtTop);

    // Track which turn is in view
    if (userTurns.length === 0) {
      setActiveTurnIndex(-1);
      return;
    }
    const activationLine = el.getBoundingClientRect().top + 60;
    let idx = 0;
    for (let i = 0; i < userTurns.length; i++) {
      const ref = turnRefs.current[userTurns[i].id];
      if (ref && ref.getBoundingClientRect().top <= activationLine) {
        idx = i;
      }
    }
    setActiveTurnIndex(idx);
  }, [messagesContainerRef, userTurns]);

  // Scroll handler: mark as scrolling, reset idle timer
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;

    const onScroll = () => {
      setIsScrollIdle(false);
      if (scrollIdleTimer.current) clearTimeout(scrollIdleTimer.current);
      scrollIdleTimer.current = setTimeout(() => {
        setIsScrollIdle(true);
      }, 500);
      syncScrollMeta();
    };

    el.addEventListener('scroll', onScroll, { passive: true });

    // Also watch resize for canScroll changes
    const ro = new ResizeObserver(() => syncScrollMeta());
    ro.observe(el);

    syncScrollMeta();
    // Start as idle
    setIsScrollIdle(true);

    return () => {
      el.removeEventListener('scroll', onScroll);
      ro.disconnect();
      if (scrollIdleTimer.current) clearTimeout(scrollIdleTimer.current);
    };
  }, [messagesContainerRef, syncScrollMeta]);

  // Re-sync when messages or status change (new content may affect canScroll)
  useEffect(() => {
    requestAnimationFrame(syncScrollMeta);
  }, [messages, status, syncScrollMeta]);

  // When scroll settles, sync nav target to the detected position
  useEffect(() => {
    if (isScrollIdle && activeTurnIndex >= 0) {
      navTargetRef.current = activeTurnIndex;
    }
  }, [isScrollIdle, activeTurnIndex]);

  // ── Navigation helpers ──
  const scrollToTop = useCallback(
    (behavior: ScrollBehavior = 'smooth') => {
      messagesContainerRef.current?.scrollTo({ top: 0, behavior });
    },
    [messagesContainerRef],
  );

  const scrollToTurn = useCallback(
    (turnId: string, behavior: ScrollBehavior = 'smooth') => {
      const container = messagesContainerRef.current;
      const turnEl = turnRefs.current[turnId];
      if (!container || !turnEl) return;

      const cRect = container.getBoundingClientRect();
      const tRect = turnEl.getBoundingClientRect();
      container.scrollTo({
        top: Math.max(0, container.scrollTop + tRect.top - cRect.top - 16),
        behavior,
      });

      const idx = userTurns.findIndex((t) => t.id === turnId);
      if (idx >= 0) {
        navTargetRef.current = idx;
        setActiveTurnIndex(idx);
      }
    },
    [messagesContainerRef, userTurns],
  );

  const isAtCurrentTurnHead = useCallback(() => {
    const container = messagesContainerRef.current;
    const cur =
      navTargetRef.current >= 0
        ? navTargetRef.current
        : Math.max(activeTurnIndex, 0);
    const turnEl = turnRefs.current[userTurns[cur]?.id];
    if (!container || !turnEl) return true;

    const cTop = container.getBoundingClientRect().top;
    const tTop = turnEl.getBoundingClientRect().top;
    // "At the head" if the turn element is within 40px of the container top
    return Math.abs(tTop - cTop) < 40;
  }, [activeTurnIndex, messagesContainerRef, userTurns]);

  const moveByTurn = useCallback(
    (dir: -1 | 1) => {
      if (userTurns.length === 0) return;
      const cur =
        navTargetRef.current >= 0
          ? navTargetRef.current
          : Math.max(activeTurnIndex, 0);

      if (dir === -1 && !isAtCurrentTurnHead()) {
        // Mid-turn: scroll back to the current turn's head first
        navTargetRef.current = cur;
        setActiveTurnIndex(cur);
        scrollToTurn(userTurns[cur].id);
        return;
      }

      const next = Math.max(0, Math.min(cur + dir, userTurns.length - 1));
      if (next === cur) return;
      navTargetRef.current = next;
      setActiveTurnIndex(next);
      scrollToTurn(userTurns[next].id);
    },
    [activeTurnIndex, isAtCurrentTurnHead, scrollToTurn, userTurns],
  );

  // Auto-scroll on submit
  useEffect(() => {
    if (status === 'submitted') {
      requestAnimationFrame(() => {
        messagesContainerRef.current?.scrollTo({
          top: messagesContainerRef.current.scrollHeight,
          behavior: 'smooth',
        });
      });
    }
  }, [status, messagesContainerRef]);

  // Deep-link: scroll to selected turn from sidebar
  useEffect(() => {
    if (!selectedTurnId) return;
    const raf = requestAnimationFrame(() => scrollToTurn(selectedTurnId));
    return () => cancelAnimationFrame(raf);
  }, [messages.length, scrollToTurn, selectedTurnId]);

  // Controls should be visible when idle AND there's enough content to scroll
  const showTopBottom = canScroll && isScrollIdle;
  const showTurnNav = hasTurns && isScrollIdle;
  const upDisabled = activeTurnIndex <= 0 && isAtCurrentTurnHead();

  return (
    <div className="relative flex-1 overflow-hidden">
      {/* Scrollable message area */}
      <div
        ref={messagesContainerRef}
        className="overscroll-behavior-contain -webkit-overflow-scrolling-touch absolute inset-0 touch-pan-y overflow-y-scroll"
        style={{ overflowAnchor: 'none' }}
      >
        <Conversation className="mx-auto flex min-w-0 max-w-7xl flex-col gap-4 md:gap-6">
          <ConversationContent className="flex flex-col gap-4 px-2 py-4 md:gap-6 md:px-4">
            {messages.length === 0 && <Greeting />}

            {messages.map((message, index) => (
              <div
                key={message.id}
                ref={(el) => {
                  if (message.role === 'user') {
                    turnRefs.current[message.id] = el;
                  }
                }}
                className={cn(message.role === 'user' && 'scroll-mt-20')}
                data-turn-id={message.role === 'user' ? message.id : undefined}
              >
                <PreviewMessage
                  message={message}
                  allMessages={messages}
                  isLoading={
                    status === 'streaming' && messages.length - 1 === index
                  }
                  setMessages={setMessages}
                  addToolApprovalResponse={addToolApprovalResponse}
                  sendMessage={sendMessage}
                  regenerate={regenerate}
                  isReadonly={isReadonly}
                  requiresScrollPadding={
                    hasSentMessage && index === messages.length - 1
                  }
                  initialFeedback={feedback[message.id]}
                />
              </div>
            ))}

            {status === 'submitted' &&
              messages.length > 0 &&
              messages[messages.length - 1].role === 'user' &&
              selectedModelId !== 'chat-model-reasoning' && (
                <AwaitingResponseMessage />
              )}

            <div
              ref={messagesEndRef}
              className="min-h-[24px] min-w-[24px] shrink-0"
            />
          </ConversationContent>
        </Conversation>
      </div>

      {/* ── Floating overlay: all navigation controls ── */}
      {/* onWheel: forward scroll events through to the container underneath */}
      <div
        className="pointer-events-none absolute inset-0 z-20 overflow-hidden"
        onWheel={(e) => {
          messagesContainerRef.current?.scrollBy({
            top: e.deltaY,
            left: e.deltaX,
          });
        }}
      >
        {/* Center-bottom: scroll to top / scroll to bottom */}
        <div
          className={cn(
            'absolute bottom-28 left-1/2 -translate-x-1/2 transition-all duration-300',
            showTopBottom && !isAtBottom && !atTop
              ? 'pointer-events-auto translate-y-0 opacity-100'
              : 'pointer-events-none translate-y-2 opacity-0',
          )}
        >
          <button
            className="rounded-full border bg-background/90 p-2 shadow-lg backdrop-blur-sm transition-colors hover:bg-muted"
            onClick={() => scrollToBottom('smooth')}
            type="button"
            aria-label="Scroll to bottom"
          >
            <ArrowDownIcon className="size-4" />
          </button>
        </div>

        <div
          className={cn(
            'absolute bottom-28 left-1/2 -translate-x-1/2 transition-all duration-300',
            showTopBottom && isAtBottom && !atTop
              ? 'pointer-events-auto translate-y-0 opacity-100'
              : 'pointer-events-none translate-y-2 opacity-0',
          )}
        >
          <button
            className="rounded-full border bg-background/90 p-2 shadow-lg backdrop-blur-sm transition-colors hover:bg-muted"
            onClick={() => scrollToTop('smooth')}
            type="button"
            aria-label="Scroll to top"
          >
            <ArrowUpIcon className="size-4" />
          </button>
        </div>

        {/* Right-side: turn prev / next */}
        <div
          className={cn(
            'absolute right-4 top-1/2 hidden -translate-y-1/2 flex-col gap-2 transition-all duration-300 md:flex',
            showTurnNav
              ? 'pointer-events-auto translate-x-0 opacity-100'
              : 'pointer-events-none translate-x-2 opacity-0',
          )}
        >
          <button
            className="pointer-events-auto rounded-full bg-blue-600 p-2 text-white shadow-lg ring-1 ring-white/20 transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => moveByTurn(-1)}
            type="button"
            aria-label="Go to previous turn"
            disabled={upDisabled}
          >
            <ChevronsUpIcon className="size-4" />
          </button>
          <button
            className="pointer-events-auto rounded-full bg-blue-600 p-2 text-white shadow-lg ring-1 ring-white/20 transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => moveByTurn(1)}
            type="button"
            aria-label="Go to next turn"
            disabled={
              activeTurnIndex < 0 || activeTurnIndex >= userTurns.length - 1
            }
          >
            <ChevronsDownIcon className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

export const Messages = memo(PureMessages, (prevProps, nextProps) => {
  // Always re-render during streaming to ensure incremental token display
  if (prevProps.status === 'streaming' || nextProps.status === 'streaming') {
    return false;
  }

  if (prevProps.selectedModelId !== nextProps.selectedModelId) return false;
  if (prevProps.selectedTurnId !== nextProps.selectedTurnId) return false;
  if (prevProps.messages.length !== nextProps.messages.length) return false;
  if (!equal(prevProps.messages, nextProps.messages)) return false;
  if (!equal(prevProps.feedback, nextProps.feedback)) return false;

  return true; // Props are equal, skip re-render
});
