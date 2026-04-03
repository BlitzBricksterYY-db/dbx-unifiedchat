import { Button } from './ui/button';
import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from 'react';
import { Textarea } from './ui/textarea';
import { toast } from 'sonner';
import { updateMessage } from '@/lib/actions';
import type { UseChatHelpers } from '@ai-sdk/react';
import type { ChatMessage } from '@chat-template/core';
import { getTextFromMessage } from '@/lib/utils';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './ui/alert-dialog';

type MessageEditorProps = {
  message: ChatMessage;
  setMode: Dispatch<SetStateAction<'view' | 'edit'>>;
  trailingMessageCount: number;
  setMessages: UseChatHelpers<ChatMessage>['setMessages'];
  regenerate: UseChatHelpers<ChatMessage>['regenerate'];
};

function replaceMessageText(message: ChatMessage, text: string): ChatMessage {
  let insertedText = false;
  const parts: ChatMessage['parts'] = [];

  for (const part of message.parts) {
    if (part.type !== 'text') {
      parts.push(part);
      continue;
    }

    if (insertedText) {
      continue;
    }

    insertedText = true;
    parts.push({ type: 'text', text });
  }

  if (!insertedText) {
    parts.unshift({ type: 'text', text });
  }

  return {
    ...message,
    parts,
  };
}

export function MessageEditor({
  message,
  setMode,
  trailingMessageCount,
  setMessages,
  regenerate,
}: MessageEditorProps) {
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);

  const originalText = getTextFromMessage(message);
  const [draftContent, setDraftContent] = useState<string>(originalText);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      adjustHeight();
    }
  }, []);

  const adjustHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight + 2}px`;
    }
  };

  const handleInput = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDraftContent(event.target.value);
    adjustHeight();
  };

  const handleSubmit = async () => {
    const nextText = draftContent;

    setIsSubmitting(true);

    try {
      await updateMessage({
        messageId: message.id,
        text: nextText,
      });

      setMessages((messages) => {
        const index = messages.findIndex((m) => m.id === message.id);

        if (index === -1) {
          return messages;
        }

        const currentMessage = messages[index];

        return [
          ...messages.slice(0, index),
          replaceMessageText(currentMessage, nextText),
        ];
      });

      setMode('view');
      regenerate();
      return true;
    } catch (error) {
      console.error('Failed to update message:', error);
      toast.error('Failed to update the message. Please try again.');
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePrimaryAction = async () => {
    const trimmedText = draftContent.trim();

    if (trimmedText.length === 0) {
      return;
    }

    if (draftContent === originalText) {
      setMode('view');
      return;
    }

    if (trailingMessageCount > 0) {
      setShowConfirmDialog(true);
      return;
    }

    await handleSubmit();
  };

  return (
    <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
      <div className="flex w-full flex-col gap-2">
        <Textarea
          data-testid="message-editor"
          ref={textareaRef}
          className="w-full resize-none overflow-hidden rounded-xl bg-transparent text-base! outline-hidden"
          value={draftContent}
          onChange={handleInput}
        />

        <p className="text-sm text-muted-foreground">
          {trailingMessageCount > 0
            ? 'This will replace this message and remove later messages before rerunning.'
            : 'This will replace this message.'}
        </p>

        <div className="flex flex-row justify-end gap-2">
          <Button
            variant="outline"
            className="h-fit px-3 py-2"
            onClick={() => {
              setMode('view');
            }}
          >
            Cancel
          </Button>
          <Button
            data-testid="message-editor-send-button"
            variant="default"
            className="h-fit px-3 py-2"
            disabled={isSubmitting || draftContent.trim().length === 0}
            onClick={handlePrimaryAction}
          >
            {isSubmitting
              ? 'Updating...'
              : trailingMessageCount > 0
                ? 'Update and rerun'
                : 'Update'}
          </Button>
        </div>
      </div>

      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Update and rerun from here?</AlertDialogTitle>
          <AlertDialogDescription>
            This will replace the selected message and permanently remove later
            messages from this chat before rerunning the assistant.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isSubmitting}>Keep current chat</AlertDialogCancel>
          <AlertDialogAction
            disabled={isSubmitting}
            onClick={async (event) => {
              event.preventDefault();
              const didSucceed = await handleSubmit();
              if (didSucceed) {
                setShowConfirmDialog(false);
              }
            }}
          >
            {isSubmitting ? 'Updating...' : 'Update and rerun'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
