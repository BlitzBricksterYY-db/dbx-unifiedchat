import { useState, useCallback } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { CheckIcon, CopyIcon, X } from 'lucide-react';
import type { UseChatHelpers } from '@ai-sdk/react';
import type { ChatMessage } from '@chat-template/core';
import { toast } from './toast';

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

  const handleCopyOption = useCallback(async (option: string) => {
    try {
      await navigator.clipboard.writeText(option);
      toast({
        type: 'success',
        description: 'Option copied to clipboard.',
      });
    } catch (error) {
      console.error('Failed to copy clarification option:', error);
      toast({
        type: 'error',
        description: 'Unable to copy option.',
      });
    }
  }, []);

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
                <div key={option} className="group relative">
                  {selectedOption === option && (
                    <div className="pointer-events-none absolute top-2.5 left-3 z-10 inline-flex items-center gap-1 rounded-full bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground shadow-sm">
                      <CheckIcon className="size-3.5" />
                      Selected
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => handleOptionSelect(option)}
                    className={cn(
                      'w-full cursor-pointer rounded-xl border px-4 pb-4 text-left text-sm leading-relaxed shadow-sm transition-all',
                      selectedOption === option ? 'pt-12' : 'pt-4',
                      selectedOption === option
                        ? 'border-primary bg-primary/10 text-foreground shadow-[0_0_0_1px_hsl(var(--primary)/0.25),0_10px_30px_-12px_hsl(var(--primary)/0.35)]'
                        : 'border-border/70 bg-background text-foreground hover:border-primary/30 hover:bg-muted/40 hover:shadow-md',
                    )}
                  >
                    {option}
                  </button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="invisible absolute top-2 right-2.5 z-10 h-8 rounded-full border border-border/60 bg-background/90 px-2.5 text-muted-foreground opacity-0 shadow-sm backdrop-blur-sm transition-all duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 hover:bg-accent hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleCopyOption(option);
                    }}
                    aria-label={`Copy option: ${option}`}
                  >
                    <CopyIcon />
                    Copy
                  </Button>
                </div>
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
