import type { Chat } from '@chat-template/db';
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from './ui/sidebar';
import { Link, useSearchParams } from 'react-router-dom';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useChatVisibility } from '@/hooks/use-chat-visibility';
import { useChatData } from '@/hooks/useChatData';
import {
  CircleCheck,
  ChevronDownIcon,
  GlobeIcon,
  LoaderIcon,
  LockIcon,
  MoreHorizontalIcon,
  ShareIcon,
  TrashIcon,
} from 'lucide-react';
import type { ChatMessage } from '@chat-template/core';
import {
  CHAT_ACTIVE_TURN_EVENT,
  type ChatActiveTurnDetail,
} from '@/lib/chat-turn-sync';

function getTurnLabel(message: ChatMessage, index: number) {
  const text = message.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ');

  if (!text) {
    return `Turn ${index + 1}`;
  }

  return text.length > 48 ? `${text.slice(0, 45)}...` : text;
}

const PureChatItem = ({
  chat,
  isActive,
  onDelete,
  setOpenMobile,
}: {
  chat: Chat;
  isActive: boolean;
  onDelete: (chatId: string) => void;
  setOpenMobile: (open: boolean) => void;
}) => {
  const { visibilityType, setVisibilityType } = useChatVisibility({
    chatId: chat.id,
    initialVisibilityType: chat.visibility,
  });
  const [searchParams] = useSearchParams();
  const [isExpanded, setIsExpanded] = useState(isActive);
  const [highlightedTurnId, setHighlightedTurnId] = useState<string | null>(null);
  const turnLinkRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  // Lazy-load: only fetch when active or when user has expanded this item
  const { chatData, isLoading } = useChatData(chat.id, isActive || isExpanded);
  const turnMessages = useMemo(
    () =>
      (chatData?.messages ?? []).filter((message) => message.role === 'user'),
    [chatData?.messages],
  );

  useEffect(() => {
    if (isActive) {
      setIsExpanded(true);
    }
  }, [isActive]);

  useEffect(() => {
    if (!isActive) {
      setHighlightedTurnId(null);
      return;
    }

    setHighlightedTurnId(searchParams.get('turn'));
  }, [isActive, searchParams]);

  useEffect(() => {
    if (!isActive) return;

    const handleActiveTurnChange = (event: Event) => {
      const { detail } = event as CustomEvent<ChatActiveTurnDetail>;
      if (detail.chatId !== chat.id) return;
      setHighlightedTurnId(detail.turnId);
    };

    window.addEventListener(CHAT_ACTIVE_TURN_EVENT, handleActiveTurnChange);
    return () => {
      window.removeEventListener(CHAT_ACTIVE_TURN_EVENT, handleActiveTurnChange);
    };
  }, [chat.id, isActive]);

  useEffect(() => {
    if (!isActive || !highlightedTurnId) return;

    turnLinkRefs.current[highlightedTurnId]?.scrollIntoView({
      block: 'nearest',
    });
  }, [highlightedTurnId, isActive]);

  const hasTurnData = isLoading || turnMessages.length > 0;
  const handleChatClick = () => {
    setOpenMobile(false);

    if (isActive) {
      window.dispatchEvent(new CustomEvent('chat-scroll-to-head'));
    }
  };

  const chatRow = (
    <SidebarMenuItem data-testid="chat-history-item">
      <SidebarMenuButton asChild isActive={isActive}>
        <Link to={`/chat/${chat.id}`} onClick={handleChatClick}>
          <ChevronDownIcon
            className={`size-3 shrink-0 text-sidebar-foreground/50 transition-transform ${isExpanded ? '' : '-rotate-90'}`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setIsExpanded((v) => !v);
            }}
          />
          <span>{chat.title}</span>
        </Link>
      </SidebarMenuButton>

      <DropdownMenu modal={true}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuAction
            data-testid="chat-options"
            className="mr-0.5 data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            showOnHover={!isActive}
          >
            <MoreHorizontalIcon />
            <span className="sr-only">More</span>
          </SidebarMenuAction>
        </DropdownMenuTrigger>

        <DropdownMenuContent side="bottom" align="end">
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="cursor-pointer">
              <ShareIcon />
              <span>Share</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent>
                <DropdownMenuItem
                  className="cursor-pointer flex-row justify-between"
                  onClick={() => {
                    setVisibilityType('private');
                  }}
                >
                  <div className="flex flex-row items-center gap-2">
                    <LockIcon size={12} />
                    <span>Private</span>
                  </div>
                  {visibilityType === 'private' ? <CircleCheck /> : null}
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="cursor-pointer flex-row justify-between"
                  onClick={() => {
                    setVisibilityType('public');
                  }}
                >
                  <div className="flex flex-row items-center gap-2">
                    <GlobeIcon />
                    <span>Public</span>
                  </div>
                  {visibilityType === 'public' ? <CircleCheck /> : null}
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>

          <DropdownMenuItem
            className="cursor-pointer text-destructive focus:bg-destructive/15 focus:text-destructive dark:text-red-500"
            onSelect={() => onDelete(chat.id)}
          >
            <TrashIcon />
            <span>Delete</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {isExpanded && (
        <div className="mt-1 ml-3 border-sidebar-border/60 border-l pl-2">
          {isLoading ? (
            <div className="flex items-center gap-2 px-2 py-1 text-sidebar-foreground/60 text-xs">
              <LoaderIcon className="size-3 animate-spin" />
              <span>Loading turns...</span>
            </div>
          ) : hasTurnData ? (
            turnMessages.map((message, index) => (
              <Link
                key={message.id}
                ref={(el) => {
                  turnLinkRefs.current[message.id] = el;
                }}
                to={`/chat/${chat.id}?turn=${message.id}`}
                onClick={() => setOpenMobile(false)}
                className={`flex w-full rounded-md px-2 py-1 text-left text-xs transition-colors ${
                  highlightedTurnId === message.id
                    ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                    : 'text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
                }`}
              >
                <span className="truncate">
                  {index + 1}. {getTurnLabel(message, index)}
                </span>
              </Link>
            ))
          ) : (
            <div className="px-2 py-1 text-sidebar-foreground/40 text-xs">
              No turns yet
            </div>
          )}
        </div>
      )}
    </SidebarMenuItem>
  );

  return chatRow;
};

export const ChatItem = memo(PureChatItem, (prevProps, nextProps) => {
  if (prevProps.isActive !== nextProps.isActive) return false;
  if (prevProps.chat.title !== nextProps.chat.title) return false;
  if (prevProps.chat.visibility !== nextProps.chat.visibility) return false;
  return true;
});
