import {
  Component,
  type ComponentProps,
  type ErrorInfo,
  type ReactNode,
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { DatabricksMessageCitationStreamdownIntegration } from '../databricks-message-citation';
import { Streamdown } from 'streamdown';
import { PaginatedTable } from './paginated-table';
import { TabWidget } from './tab-widget';
import { parseChartSpec } from './chart-spec';

const InteractiveChart = lazy(() =>
  import('./interactive-chart').then((m) => ({ default: m.InteractiveChart })),
);

function encodeTabsToBase64(tabs: Array<{ title: string; content: string }>): string {
  const json = JSON.stringify(tabs);
  return btoa(
    encodeURIComponent(json).replace(/%([0-9A-F]{2})/g, (_, p1) =>
      String.fromCharCode(parseInt(p1, 16)),
    ),
  );
}

function decodeTabsFromBase64(b64: string): Array<{ title: string; content: string }> | null {
  try {
    const json = decodeURIComponent(
      atob(b64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

type TableDownloadPayload = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  totalRows?: number;
  previewRowCount?: number;
  isPreview?: boolean;
  filename?: string;
  title?: string;
  sql?: string;
  sqlFilename?: string;
};

function decodeTableFromBase64(b64: string): TableDownloadPayload | null {
  try {
    const json = decodeURIComponent(
      atob(b64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    );
    const payload = JSON.parse(json) as TableDownloadPayload;
    if (!payload || !Array.isArray(payload.columns) || !Array.isArray(payload.rows)) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

function parseAccordionGroup(text: string): {
  before: string;
  tabs: Array<{ title: string; content: string }>;
  after: string;
} | null {
  const marker = '<div class="accordion-group">';
  const groupStart = text.indexOf(marker);
  if (groupStart === -1) return null;

  const inner = text.substring(groupStart + marker.length);

  const detailsOpens = inner.match(/<details[\s>]/g);
  if (!detailsOpens || detailsOpens.length === 0) return null;

  let searchPos = 0;
  for (let i = 0; i < detailsOpens.length; i++) {
    const idx = inner.indexOf('</details>', searchPos);
    if (idx === -1) return null;
    searchPos = idx + '</details>'.length;
  }

  const remaining = inner.substring(searchPos);
  const closingDiv = remaining.indexOf('</div>');
  if (closingDiv === -1) return null;

  const groupEnd =
    groupStart + marker.length + searchPos + closingDiv + '</div>'.length;
  const before = text.substring(0, groupStart);
  const after = text.substring(groupEnd);

  const tabs: Array<{ title: string; content: string }> = [];
  const detailsRe =
    /<details[^>]*>\s*<summary>([\s\S]*?)<\/summary>([\s\S]*?)<\/details>/g;
  let m;
  while ((m = detailsRe.exec(inner)) !== null) {
    const title = m[1].trim();
    let content = m[2].trim();

    const wrapperTag = '<div class="accordion-content">';
    const wrapIdx = content.indexOf(wrapperTag);
    if (wrapIdx !== -1) {
      content = content.substring(wrapIdx + wrapperTag.length);
      const lastDiv = content.lastIndexOf('</div>');
      if (lastDiv !== -1) {
        content = content.substring(0, lastDiv);
      }
    }
    content = content.trim();
    tabs.push({ title, content });
  }

  if (tabs.length === 0) return null;
  return { before, tabs, after };
}

function SqlCodeBlock({ sql, filename, b64 }: { sql: string; filename: string; b64: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(sql).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [sql]);

  return (
    <div className="my-1 overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700">
      <div className="flex items-center justify-between bg-zinc-100 px-3 py-1.5 dark:bg-zinc-800">
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">SQL</span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="rounded px-2 py-0.5 text-xs font-medium text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
          <a
            href={`data:text/sql;base64,${b64}`}
            download={filename}
            className="rounded px-2 py-0.5 text-xs font-medium text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            Download
          </a>
        </div>
      </div>
      <pre className="overflow-x-auto bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
        <code>{sql}</code>
      </pre>
    </div>
  );
}

function JsonCodeBlock({ json, filename, b64 }: { json: string; filename: string; b64: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(json).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [json]);

  return (
    <div className="my-1 overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700">
      <div className="flex items-center justify-between bg-zinc-100 px-3 py-1.5 dark:bg-zinc-800">
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">JSON</span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="rounded px-2 py-0.5 text-xs font-medium text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
          <a
            href={`data:application/json;base64,${b64}`}
            download={filename}
            className="rounded px-2 py-0.5 text-xs font-medium text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            Download
          </a>
        </div>
      </div>
      <pre className="overflow-x-auto bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
        <code>{json}</code>
      </pre>
    </div>
  );
}

function EChartsCodeBlock(props: Record<string, unknown>) {
  const { className } = props as { className?: string };
  const children = typeof props.children === 'string' ? props.children : undefined;

  if (className === 'language-echarts-chart' && children) {
    const spec = parseChartSpec(children);
    if (spec) {
      return (
        <ChartErrorBoundary>
          <Suspense fallback={<div className="h-[400px] animate-pulse rounded bg-zinc-100 dark:bg-zinc-800" />}>
            <InteractiveChart spec={spec} />
          </Suspense>
        </ChartErrorBoundary>
      );
    }
  }

  if (className?.startsWith('language-accordion-tabs:')) {
    const b64 = className.slice('language-accordion-tabs:'.length);
    const tabs = decodeTabsFromBase64(b64);
    if (tabs && tabs.length > 0) {
      return <TabWidget tabs={tabs} components={streamdownComponents} />;
    }
  }

  if (className?.startsWith('language-table-download:')) {
    const meta = className.slice('language-table-download:'.length);
    const colonIdx = meta.indexOf(':');
    if (colonIdx !== -1) {
      const b64 = meta.substring(colonIdx + 1);
      const payload = decodeTableFromBase64(b64);
      if (payload) {
        return (
          <PaginatedTable
            tableData={{
              columns: payload.columns,
              rows: payload.rows,
              totalRows: payload.totalRows,
              previewRowCount: payload.previewRowCount,
              isPreview: payload.isPreview,
              filename: payload.filename,
              title: payload.title,
              sql: payload.sql,
              sqlFilename: payload.sqlFilename,
            }}
          />
        );
      }
    }
  }

  // sql-download:<filename>:<base64> — render with copy + download buttons
  if (className?.startsWith('language-sql-download:') && children) {
    const meta = className.slice('language-sql-download:'.length);
    const colonIdx = meta.indexOf(':');
    if (colonIdx !== -1) {
      const filename = meta.substring(0, colonIdx);
      const b64 = meta.substring(colonIdx + 1);
      return <SqlCodeBlock sql={children} filename={filename} b64={b64} />;
    }
  }

  // json-download:<filename>:<base64> — render with copy + download buttons
  if (className?.startsWith('language-json-download:') && children) {
    const meta = className.slice('language-json-download:'.length);
    const colonIdx = meta.indexOf(':');
    if (colonIdx !== -1) {
      const filename = meta.substring(0, colonIdx);
      const b64 = meta.substring(colonIdx + 1);
      return <JsonCodeBlock json={children} filename={filename} b64={b64} />;
    }
  }

  return (
    <pre>
      <code className={className}>{children}</code>
    </pre>
  );
}

class StreamdownErrorBoundary extends Component<
  { children: ReactNode; fallbackText?: string },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode; fallbackText?: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Streamdown render crash:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="whitespace-pre-wrap text-sm">
          {this.props.fallbackText ?? ''}
        </div>
      );
    }
    return this.props.children;
  }
}

class ChartErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Chart render error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded bg-zinc-100 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          [Chart unavailable]
        </div>
      );
    }
    return this.props.children;
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const streamdownComponents: Record<string, any> = {
  a: DatabricksMessageCitationStreamdownIntegration,
  code: EChartsCodeBlock,
};

type ResponseProps = ComponentProps<typeof Streamdown>;
type BufferedResponseProps = ResponseProps & {
  isStreaming?: boolean;
};

const STREAMDOWN_BUFFER_MS = 180;

export const Response = memo(
  ({ isStreaming = false, ...props }: BufferedResponseProps) => {
    const [bufferedChildren, setBufferedChildren] = useState(props.children);
    const lastFlushAtRef = useRef(0);

    useEffect(() => {
      if (typeof props.children !== 'string') {
        setBufferedChildren(props.children);
        lastFlushAtRef.current = Date.now();
        return;
      }

      if (!isStreaming) {
        setBufferedChildren(props.children);
        lastFlushAtRef.current = Date.now();
        return;
      }

      const now = Date.now();
      const elapsed = now - lastFlushAtRef.current;

      if (elapsed >= STREAMDOWN_BUFFER_MS) {
        setBufferedChildren(props.children);
        lastFlushAtRef.current = now;
        return;
      }

      const timeoutId = window.setTimeout(() => {
        setBufferedChildren(props.children);
        lastFlushAtRef.current = Date.now();
      }, STREAMDOWN_BUFFER_MS - elapsed);

      return () => window.clearTimeout(timeoutId);
    }, [isStreaming, props.children]);

    const raw =
      typeof bufferedChildren === 'string' ? bufferedChildren : '';

    const processed = useMemo(() => {
      if (typeof bufferedChildren !== 'string') return bufferedChildren;
      try {
        let text = bufferedChildren;

        // Auto-collapse the Processing Steps <details open> when summary content follows.
        const processingStepsStart = text.indexOf('<summary>Processing Steps</summary>');
        if (processingStepsStart !== -1) {
          const closeTag = '</details>';
          const firstClose = text.indexOf(closeTag, processingStepsStart);
          if (firstClose !== -1) {
            const afterProcessingSteps = text
              .substring(firstClose + closeTag.length)
              .trim();
            if (afterProcessingSteps.length > 0) {
              text = text.replace(/<details open>/g, '<details>');
              const before = text.substring(0, firstClose + closeTag.length);
              const after = text.substring(firstClose + closeTag.length);
              text = before + '\n\n---\n\n' + after.trimStart();
            }
          }
        }

        // Transform accordion-group into a tab widget code fence.
        // Falls through gracefully during streaming (returns null if incomplete).
        const accordionResult = parseAccordionGroup(text);
        if (accordionResult) {
          const encoded = encodeTabsToBase64(accordionResult.tabs);
          text =
            accordionResult.before +
            '\n\n```accordion-tabs:' +
            encoded +
            '\ntabs\n```\n\n' +
            accordionResult.after;
        }

        return text;
      } catch (e) {
        console.error('Response processing error:', e);
        return bufferedChildren;
      }
    }, [bufferedChildren]);

    return (
      <StreamdownErrorBoundary fallbackText={raw}>
        <Streamdown
          components={streamdownComponents}
          className="markdown-content flex flex-col gap-4"
          {...props}
          children={processed}
        />
      </StreamdownErrorBoundary>
    );
  },
  (prevProps, nextProps) =>
    prevProps.children === nextProps.children &&
    prevProps.isStreaming === nextProps.isStreaming,
);

Response.displayName = 'Response';
