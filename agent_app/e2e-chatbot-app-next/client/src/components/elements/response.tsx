import { type ComponentProps, type JSX, lazy, memo, Suspense, useMemo } from 'react';
import { DatabricksMessageCitationStreamdownIntegration } from '../databricks-message-citation';
import { Streamdown } from 'streamdown';

const InteractiveChart = lazy(() => import('./interactive-chart'));

type ResponseProps = ComponentProps<typeof Streamdown>;

function CustomCode(props: JSX.IntrinsicElements['code'] & { node?: unknown }) {
  const { className, children, node: _node, ...rest } = props;

  if (className === 'language-echarts-chart' && typeof children === 'string') {
    try {
      const spec = JSON.parse(children);
      if (spec?.config && spec?.chartData) {
        return (
          <Suspense fallback={<div className="p-4 text-sm text-gray-500">Loading chart...</div>}>
            <InteractiveChart spec={spec} />
          </Suspense>
        );
      }
    } catch {
      // JSON parse failed — fall through to default code block
    }
  }

  return <code className={className} {...rest}>{children}</code>;
}

export const Response = memo(
  (props: ResponseProps) => {
    const components = useMemo(
      () => ({
        a: DatabricksMessageCitationStreamdownIntegration,
        code: CustomCode,
      }),
      [],
    );

    return (
      <Streamdown
        components={components}
        className="flex flex-col gap-4"
        {...props}
      />
    );
  },
  (prevProps, nextProps) => prevProps.children === nextProps.children,
);

Response.displayName = 'Response';
