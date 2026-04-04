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

function truncateText(value: string, maxLength = 120): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trimEnd()}…`;
}

function readMetaString(spec: ChartSpec, key: string): string | null {
  const value = spec.meta && typeof spec.meta === 'object'
    ? (spec.meta as Record<string, unknown>)[key]
    : undefined;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function readMetaBoolean(spec: ChartSpec, key: string): boolean {
  const value = spec.meta && typeof spec.meta === 'object'
    ? (spec.meta as Record<string, unknown>)[key]
    : undefined;
  return value === true;
}

function readMetaStringArray(spec: ChartSpec, key: string): string[] {
  const value = spec.meta && typeof spec.meta === 'object'
    ? (spec.meta as Record<string, unknown>)[key]
    : undefined;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

function buildHeaderNote(spec: ChartSpec, fallbackApplied: boolean): string | null {
  const source = readMetaString(spec, 'source');
  const rationale = readMetaString(spec, 'rationale');
  const description = readMetaString(spec, 'description');
  const previewLimited = readMetaBoolean(spec, 'previewLimited');

  const notes = [
    source === 'manual' ? null : rationale,
    previewLimited ? 'Preview-limited view; full results available in CSV.' : null,
    fallbackApplied ? 'Best-effort chart fallback applied.' : null,
    source !== 'manual' && description ? description : null,
  ].filter((note): note is string => Boolean(note));

  if (notes.length === 0) return null;
  return notes.join(' ');
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
  const normalizationNotes = useMemo(
    () => readMetaStringArray(spec, 'normalizationNotes'),
    [spec],
  );
  const fallbackApplied = useMemo(
    () => readMetaBoolean(spec, 'fallbackApplied'),
    [spec],
  );
  const headerNoteFull = useMemo(
    () => buildHeaderNote(spec, fallbackApplied),
    [fallbackApplied, spec],
  );
  const headerNotePreview = useMemo(
    () => (headerNoteFull ? truncateText(headerNoteFull.replace(/\s+/g, ' '), 140) : null),
    [headerNoteFull],
  );
  const businessInsightFull = useMemo(
    () => readMetaString(spec, 'businessInsight'),
    [spec],
  );
  const businessInsightPreview = useMemo(
    () => (businessInsightFull ? truncateText(businessInsightFull.replace(/\s+/g, ' '), 140) : null),
    [businessInsightFull],
  );
  const displaySpec = useMemo(() => ({
    ...spec,
    config: {
      ...spec.config,
      description: businessInsightPreview ?? spec.config.description ?? undefined,
      style: {
        ...spec.config.style,
        showDescription: Boolean(businessInsightPreview ?? spec.config.description),
      },
    },
  }), [businessInsightPreview, spec]);
  const option = useMemo(() => buildOption(displaySpec, chartType), [chartType, displaySpec]);
  const fallbackPreview = useMemo(
    () => truncateText(normalizationNotes.join(' • '), 180),
    [normalizationNotes],
  );

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
          {headerNotePreview && (
            <p
              className="mt-1 truncate text-xs text-zinc-500 dark:text-zinc-400"
              title={headerNoteFull ?? undefined}
            >
              {headerNotePreview}
            </p>
          )}
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

      {fallbackApplied && normalizationNotes.length > 0 && (
        <div
          className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200"
          title={normalizationNotes.join('\n')}
        >
          Best-effort chart fallback applied: {fallbackPreview}
        </div>
      )}

      <div className="relative">
        {businessInsightFull && (
          <div
            className="absolute left-1/2 top-10 z-10 h-5 w-[72%] -translate-x-1/2"
            title={businessInsightFull}
          />
        )}
        <ReactEChartsCore
          ref={chartRef}
          echarts={echarts}
          option={option}
          style={{ height: 400, width: '100%' }}
          opts={{ renderer: 'svg' }}
          notMerge
        />
      </div>

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
