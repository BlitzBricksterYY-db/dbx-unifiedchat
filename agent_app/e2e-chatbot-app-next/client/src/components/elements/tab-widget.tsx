'use client';

import { memo, useCallback, useState } from 'react';
import { Streamdown } from 'streamdown';
import type { ComponentType } from 'react';
import { CheckIcon, CopyIcon } from 'lucide-react';

type Tab = { title: string; content: string };

type TabWidgetProps = {
  tabs: Tab[];
  components?: Record<string, ComponentType<any>>;
};

function ChevronDown() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

function ChevronUp() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 10l4-4 4 4" />
    </svg>
  );
}

export const TabWidget = memo(function TabWidget({ tabs, components }: TabWidgetProps) {
  const [expanded, setExpanded] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const [copied, setCopied] = useState(false);

  const activeTab = tabs[activeIdx];

  const handleCopy = useCallback(async () => {
    if (!activeTab?.content) return;
    await navigator.clipboard.writeText(activeTab.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [activeTab]);

  if (tabs.length === 0) return null;

  const toggleBar = useCallback(() => setExpanded((v) => !v), []);

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={toggleBar}
        className="mt-3 flex w-full items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 cursor-pointer dark:border-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-400 dark:hover:bg-zinc-700"
      >
        <ChevronDown />
        <span>Show details</span>
        <span className="text-xs font-normal text-zinc-400 dark:text-zinc-500">
          {tabs.map((t) => t.title).join(' · ')}
        </span>
      </button>
    );
  }

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-zinc-200 shadow-sm dark:border-zinc-700">
      <div
        role="toolbar"
        onClick={toggleBar}
        className="flex cursor-pointer items-center border-b border-zinc-200 bg-zinc-50 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden dark:border-zinc-700 dark:bg-zinc-800/60"
      >
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); toggleBar(); }}
          className="shrink-0 px-3 py-2.5 text-zinc-500 transition-colors cursor-pointer hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
          title="Hide details"
        >
          <ChevronUp />
        </button>
        {tabs.map((tab, i) => (
          <button
            key={i}
            type="button"
            onClick={(e) => { e.stopPropagation(); setActiveIdx(i); }}
            className={[
              'shrink-0 px-4 py-2.5 text-sm font-medium transition-all duration-150',
              'border-b-2 -mb-px outline-none cursor-pointer',
              i === activeIdx
                ? 'border-blue-500 text-blue-600 bg-white dark:text-blue-400 dark:bg-zinc-900'
                : 'border-transparent text-zinc-500 hover:text-zinc-700 hover:border-zinc-300 dark:text-zinc-400 dark:hover:text-zinc-300 dark:hover:border-zinc-600',
            ].join(' ')}
          >
            {tab.title}
          </button>
        ))}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); handleCopy(); }}
          className="ml-auto shrink-0 px-3 py-2.5 text-zinc-500 transition-colors cursor-pointer hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
          title={`Copy ${activeTab?.title ?? 'details'}`}
        >
          <span className="inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide">
            {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
            {copied ? 'Copied' : 'Copy'}
          </span>
        </button>
      </div>
      <div className="bg-white p-4 dark:bg-zinc-900">
        <Streamdown
          key={activeIdx}
          components={components}
          className="markdown-content flex flex-col gap-4"
        >
          {tabs[activeIdx].content}
        </Streamdown>
      </div>
    </div>
  );
});
