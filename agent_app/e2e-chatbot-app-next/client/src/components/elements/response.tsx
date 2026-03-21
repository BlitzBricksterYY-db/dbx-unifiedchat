import {
  Component,
  type ComponentProps,
  type ErrorInfo,
  type ReactNode,
  lazy,
  memo,
  Suspense,
  useMemo,
} from 'react';
import { DatabricksMessageCitationStreamdownIntegration } from '../databricks-message-citation';
import { Streamdown } from 'streamdown';

const InteractiveChart = lazy(() =>
  import('./interactive-chart').then((m) => ({ default: m.InteractiveChart })),
);

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

        // Extract and apply enriched table replacement (sent as a separate text part,
        // joined here by joinMessagePartSegments)
        const ENRICHED_SENTINEL = 'ENRICHED_TABLE_REPLACE\n';
        const sentinelIdx = text.indexOf(ENRICHED_SENTINEL);
        if (sentinelIdx !== -1) {
          const enrichedTable = text.substring(
            sentinelIdx + ENRICHED_SENTINEL.length,
          );
          text = text.substring(0, sentinelIdx).trimEnd();
          // Replace the first markdown table in the summary with the enriched one
          const tableRegex = /\|[^\n]*\|\n\|[-| :]+\|\n(?:\|[^\n]*\|\n)*/;
          const tableMatch = text.match(tableRegex);
          if (tableMatch && tableMatch.index !== undefined) {
            text =
              text.substring(0, tableMatch.index) +
              enrichedTable +
              '\n' +
              text.substring(tableMatch.index + tableMatch[0].length);
          } else {
            text = text + '\n\n' + enrichedTable;
          }
        }

        // Auto-collapse <details open> when there is content after it (summary started)
        const closeTag = '</details>';
        const lastClose = text.lastIndexOf(closeTag);
        if (lastClose !== -1) {
          const afterDetails = text
            .substring(lastClose + closeTag.length)
            .trim();
          if (afterDetails.length > 0) {
            text = text.replace(/<details open>/g, '<details>');
            const before = text.substring(0, lastClose);
            const after = text.substring(lastClose + closeTag.length);
            text = before + closeTag + '\n\n---\n\n' + after;
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
