import { type ComponentProps, lazy, memo, Suspense, useMemo } from 'react';
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
        <Suspense fallback={<div className="h-[400px] animate-pulse rounded bg-zinc-100 dark:bg-zinc-800" />}>
          <InteractiveChart spec={spec} />
        </Suspense>
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

type ResponseProps = ComponentProps<typeof Streamdown>;

export const Response = memo(
  (props: ResponseProps) => {
    const processed = useMemo(() => {
      if (typeof props.children !== 'string') return props.children;
      const text = props.children;
      const closeTag = '</details>';
      const lastClose = text.lastIndexOf(closeTag);
      if (lastClose === -1) return text;

      const afterDetails = text
        .substring(lastClose + closeTag.length)
        .trim();
      if (afterDetails.length > 0) {
        // Collapse the block and add a horizontal rule separator
        return text
          .replace(/<details open>/g, '<details>')
          .replace(
            new RegExp(`${closeTag}(?!.*${closeTag})`, 's'),
            `${closeTag}\n\n---\n\n`,
          );
      }
      return text;
    }, [props.children]);

    return (
      <Streamdown
        components={{
          a: DatabricksMessageCitationStreamdownIntegration,
          code: EChartsCodeBlock,
        }}
        className="flex flex-col gap-4"
        {...props}
        children={processed}
      />
    );
  },
  (prevProps, nextProps) => prevProps.children === nextProps.children,
);

Response.displayName = 'Response';
