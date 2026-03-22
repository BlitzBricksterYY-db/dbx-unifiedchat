import {
  Component,
  type ComponentProps,
  type ErrorInfo,
  type ReactNode,
  lazy,
  memo,
  Suspense,
  useCallback,
  useMemo,
  useState,
} from 'react';
import { DatabricksMessageCitationStreamdownIntegration } from '../databricks-message-citation';
import { Streamdown } from 'streamdown';

const InteractiveChart = lazy(() =>
  import('./interactive-chart').then((m) => ({ default: m.InteractiveChart })),
);

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

function EChartsCodeBlock(props: { className?: string; children?: string }) {
  const { className, children } = props;

  if (className === 'language-echarts-chart' && children) {
    try {
      const spec = JSON.parse(children);
      return (
        <ChartErrorBoundary>
          <Suspense fallback={<div className="h-[400px] animate-pulse rounded bg-zinc-100 dark:bg-zinc-800" />}>
            <InteractiveChart spec={spec} />
          </Suspense>
        </ChartErrorBoundary>
      );
    } catch {
      // fall through to default code block
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

type ResponseProps = ComponentProps<typeof Streamdown>;

export const Response = memo(
  (props: ResponseProps) => {
    const raw =
      typeof props.children === 'string' ? props.children : '';

    const processed = useMemo(() => {
      if (typeof props.children !== 'string') return props.children;
      try {
        let text = props.children;

        // Auto-collapse the Processing Steps <details open> when summary content follows.
        // Use indexOf (first </details>) — the Processing Steps block — not lastIndexOf
        // which would find the SQL <details> block at the end (nothing follows it).
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

        return text;
      } catch (e) {
        console.error('Response processing error:', e);
        return props.children;
      }
    }, [props.children]);

    return (
      <StreamdownErrorBoundary fallbackText={raw}>
        <Streamdown
          components={{
            a: DatabricksMessageCitationStreamdownIntegration,
            code: EChartsCodeBlock,
          }}
          className="flex flex-col gap-4"
          {...props}
          children={processed}
        />
      </StreamdownErrorBoundary>
    );
  },
  (prevProps, nextProps) => prevProps.children === nextProps.children,
);

Response.displayName = 'Response';
