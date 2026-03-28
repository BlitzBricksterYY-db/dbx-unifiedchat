import { useState, useCallback } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import type { UseChatHelpers } from '@ai-sdk/react';
import type { ChatMessage } from '@chat-template/core';

export interface ClarificationData {
  reason: string;
  options: string[];
}

interface ClarificationModalProps {
  data: ClarificationData;
  onClose: () => void;
  sendMessage: UseChatHelpers<ChatMessage>['sendMessage'];
}

export function ClarificationModal({
  data,
  onClose,
  sendMessage,
}: ClarificationModalProps) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [customInput, setCustomInput] = useState('');

  const confirmValue = selectedOption ?? customInput.trim();

  const handleOptionSelect = useCallback((option: string) => {
    setSelectedOption(option);
    setCustomInput('');
  }, []);

  const handleCustomInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setCustomInput(e.target.value);
      setSelectedOption(null);
    },
    [],
  );

  const handleConfirm = useCallback(() => {
    if (!confirmValue) return;
    sendMessage({
      role: 'user',
      parts: [{ type: 'text', text: confirmValue }],
    });
    onClose();
  }, [confirmValue, sendMessage, onClose]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && customInput.trim()) {
        e.preventDefault();
        handleConfirm();
      }
    },
    [customInput, handleConfirm],
  );

  return (
    <DialogPrimitive.Root open onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/60 data-[state=closed]:animate-out data-[state=open]:animate-in" />
        <DialogPrimitive.Content
          className="data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] fixed top-[50%] left-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-lg border bg-background p-6 shadow-lg duration-200 data-[state=closed]:animate-out data-[state=open]:animate-in"
        >
          <div className="flex items-start justify-between gap-4">
            <DialogPrimitive.Title className="font-semibold text-lg leading-none tracking-tight">
              Clarification Needed
            </DialogPrimitive.Title>
            <DialogPrimitive.Close
              className={cn(
                'rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
              )}
            >
              <X className="size-4" />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          </div>

          <DialogPrimitive.Description className="mt-3 text-muted-foreground text-sm leading-relaxed">
            {data.reason}
          </DialogPrimitive.Description>

          {data.options.length > 0 && (
            <div className="mt-4 flex flex-col gap-2">
              <p className="font-medium text-sm">Select an option:</p>
              {data.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => handleOptionSelect(option)}
                  className={cn(
                    'w-full cursor-pointer rounded-md border px-4 py-2.5 text-left text-sm transition-colors',
                    selectedOption === option
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border bg-background text-foreground hover:border-primary/50 hover:bg-muted',
                  )}
                >
                  {option}
                </button>
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-col gap-2">
            <p className="font-medium text-sm">
              {data.options.length > 0
                ? 'Or provide a custom response:'
                : 'Your response:'}
            </p>
            <textarea
              value={customInput}
              onChange={handleCustomInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Type your response..."
              rows={2}
              className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={handleConfirm} disabled={!confirmValue}>
              Confirm
            </Button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
