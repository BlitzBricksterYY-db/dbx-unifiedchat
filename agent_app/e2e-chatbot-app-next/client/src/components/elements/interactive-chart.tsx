import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import _ReactEChartsCore from 'echarts-for-react/lib/core';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ReactEChartsCore: typeof _ReactEChartsCore = ((_ReactEChartsCore as any).default ?? _ReactEChartsCore) as typeof _ReactEChartsCore;
import * as echarts from 'echarts/core';
import {
  BarChart,
  BoxplotChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
} from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import {
  Sparkles,
  Settings2,
  Copy,
  Trash2,
  Undo2,
  Redo2,
} from 'lucide-react';
import { SVGRenderer } from 'echarts/renderers';
import { LegacyGridContainLabel } from 'echarts/features';

import { buildOption, getSelectableChartTypes, type ChartSpec } from './chart-spec';
import { Button } from '@/components/ui/button';

echarts.use([
  BarChart,
  BoxplotChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  TitleComponent,
  VisualMapComponent,
  MarkLineComponent,
  SVGRenderer,
  LegacyGridContainLabel,
]);

function toCsv(data: Record<string, unknown>[]): string {
  if (!data.length) return '';
  const cols = Object.keys(data[0]);
  const escape = (v: unknown) => {
    const s = v == null ? '' : String(v);
    return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = [cols.map(escape).join(',')];
  for (const row of data) {
    rows.push(cols.map((c) => escape(row[c])).join(','));
  }
  return rows.join('\n');
}

type InteractiveChartProps = {
  spec: ChartSpec;
  onOpenPrompt?: () => void;
  onOpenCustomizer?: () => void;
  onChangeChartType?: (chartType: string) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onReset?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  onDuplicate?: () => void;
  onRemove?: () => void;
  canRemove?: boolean;
};

export function InteractiveChart({
  spec,
  onOpenPrompt,
  onOpenCustomizer,
  onChangeChartType,
  onUndo,
  onRedo,
  onReset,
  canUndo = false,
  canRedo = false,
  onDuplicate,
  onRemove,
  canRemove = false,
}: InteractiveChartProps) {
  const availableChartTypes = useMemo(() => getSelectableChartTypes(spec), [spec]);
  const chartRef = useRef<any>(null);
  const chartType = spec.config.chartType ?? 'bar';
  const option = useMemo(() => buildOption(spec, chartType), [spec, chartType]);

  const handleReset = useCallback(() => {
    onReset?.();
    chartRef.current?.getEchartsInstance()?.dispatchAction({ type: 'restore' });
  }, [onReset]);

  const handleDownloadCsv = useCallback(() => {
    const data = spec.downloadData ?? spec.chartData;
    const csv = toCsv(data);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'results.csv';
    a.click();
    URL.revokeObjectURL(url);
  }, [spec]);

  return (
    <div className="my-4 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
      <div className="mb-3 flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {spec.config.title || 'Chart'}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {onOpenPrompt && (
            <Button type="button" variant="outline" size="sm" onClick={onOpenPrompt}>
              <Sparkles className="h-4 w-4" />
              Ask
            </Button>
          )}
          {onOpenCustomizer && (
            <Button type="button" variant="outline" size="sm" onClick={onOpenCustomizer}>
              <Settings2 className="h-4 w-4" />
              Customize
            </Button>
          )}
          {onDuplicate && (
            <Button type="button" variant="ghost" size="sm" onClick={onDuplicate}>
              <Copy className="h-4 w-4" />
              Duplicate
            </Button>
          )}
          {onRemove && canRemove && (
            <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
              <Trash2 className="h-4 w-4" />
              Remove
            </Button>
          )}
        </div>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-2">
        {availableChartTypes.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onChangeChartType?.(t)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              chartType === t
                ? 'bg-blue-600 text-white'
                : 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
            }`}
          >
            {t.replace(/([A-Z])/g, ' $1').replace(/^./, (char) => char.toUpperCase())}
          </button>
        ))}
        <button
          type="button"
          onClick={onUndo}
          disabled={!canUndo}
          className="rounded px-2.5 py-1 text-xs font-medium text-zinc-500 hover:text-zinc-800 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:text-zinc-200"
        >
          <span className="inline-flex items-center gap-1">
            <Undo2 className="h-3.5 w-3.5" />
            Revert
          </span>
        </button>
        <button
          type="button"
          onClick={onRedo}
          disabled={!canRedo}
          className="rounded px-2.5 py-1 text-xs font-medium text-zinc-500 hover:text-zinc-800 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:text-zinc-200"
        >
          <span className="inline-flex items-center gap-1">
            <Redo2 className="h-3.5 w-3.5" />
            Redo
          </span>
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="rounded px-2.5 py-1 text-xs font-medium text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
        >
          Reset
        </button>
        <button
          type="button"
          onClick={handleDownloadCsv}
          className="ml-auto rounded bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700"
        >
          Download CSV
        </button>
      </div>

      <ReactEChartsCore
        ref={chartRef}
        echarts={echarts}
        option={option}
        style={{ height: 400, width: '100%' }}
        opts={{ renderer: 'svg' }}
        notMerge
      />

      {spec.aggregated && spec.aggregationNote && (
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
          {spec.aggregationNote}
          {spec.totalRows && spec.downloadData
            ? ` — CSV contains ${Math.min(spec.downloadData.length, spec.totalRows)} of ${spec.totalRows} rows`
            : ''}
        </p>
      )}
    </div>
  );
}
