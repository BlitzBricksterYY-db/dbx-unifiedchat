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

function splitNoteParts(value: string | null): string[] {
  if (!value) return [];
  return value
    .split(/[•\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function normalizeNote(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isGenericRowGrainGuardrailNote(value: string): boolean {
  return normalizeNote(value) === 'row grain guardrails applied';
}

function hasDetailedRowGrainNote(notes: string[]): boolean {
  return notes.some((note) => {
    const normalized = normalizeNote(note);
    return !isGenericRowGrainGuardrailNote(note)
      && (
        normalized.includes('row grain')
        || normalized.includes('patient level')
        || normalized.includes('diagnosis level')
        || normalized.includes('claim level')
        || normalized.includes('member level')
      );
  });
}

function buildHeaderNote(
  spec: ChartSpec,
  fallbackApplied: boolean,
  hasNormalizationNotes: boolean,
): string | null {
  const source = readMetaString(spec, 'source');
  const rationale = readMetaString(spec, 'rationale');
  const previewLimited = readMetaBoolean(spec, 'previewLimited');

  const rawNotes = [
    ...(source === 'manual' ? [] : splitNoteParts(rationale)),
    ...(previewLimited ? ['Preview-limited view; full results available in CSV.'] : []),
    ...(fallbackApplied && !hasNormalizationNotes ? ['Best-effort chart fallback applied.'] : []),
  ];

  const detailedRowGrainNotePresent = hasDetailedRowGrainNote(rawNotes);
  const seen = new Set<string>();
  const notes = rawNotes.filter((note) => {
    if (detailedRowGrainNotePresent && isGenericRowGrainGuardrailNote(note)) {
      return false;
    }

    const normalized = normalizeNote(note);
    if (!normalized || seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });

  if (notes.length === 0) return null;
  return notes.join(' • ');
}

type InteractiveChartProps = {
  spec: ChartSpec;
  onOpenPrompt?: () => void;
  onAskAboutSelection?: (prompt: string) => void;
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

type ChartSelection = {
  xValue: string;
  groupValue?: string;
  yValue?: string;
  zValue?: string;
  seriesName?: string;
  left: number;
  top: number;
};

function parseGroupFromSeriesName(seriesName?: string) {
  if (!seriesName) return undefined;
  const match = /^(.*) \((.*)\)$/.exec(seriesName);
  return match?.[2] || undefined;
}

type ChartClickParams = {
  componentType?: string;
  name?: string;
  seriesName?: string;
  value?: unknown;
  data?: unknown;
  event?: { event?: MouseEvent };
};

function readEventDataRecord(data: unknown): Record<string, unknown> | null {
  return data && typeof data === 'object' && !Array.isArray(data)
    ? (data as Record<string, unknown>)
    : null;
}

export function matchesSelection(
  row: Record<string, unknown>,
  spec: ChartSpec,
  selection: ChartSelection | null,
) {
  if (!selection) return true;
  const chartType = spec.config.chartType ?? '';
  const xField = spec.config.xAxisField ?? '';
  const transform = spec.config.transform as Record<string, unknown> | null | undefined;
  if (xField && String(row[xField] ?? '') !== selection.xValue) {
    const transformType = String(transform?.type ?? '');
    if (transformType === 'timeBucket') {
      const sourceField = String(transform?.field ?? xField);
      const bucket = String(transform?.bucket ?? '');
      if (bucketValue(row[sourceField], bucket) !== selection.xValue) return false;
    } else if (transformType === 'histogram') {
      const sourceField = String(transform?.field ?? xField);
      const range = parseNumericBucketRange(selection.xValue);
      const rawValue = Number(row[sourceField]);
      if (!range || !Number.isFinite(rawValue) || rawValue < range.start || rawValue > range.end) return false;
    } else {
      return false;
    }
  }
  const groupField = spec.config.groupByField ?? '';
  if (selection.groupValue && groupField && String(row[groupField] ?? '') !== selection.groupValue) return false;
  const yField = spec.config.series[0]?.field ?? '';
  if (chartType === 'scatter' && selection.yValue && yField && String(row[yField] ?? '') !== selection.yValue) return false;
  const zField = spec.config.zAxisField ?? '';
  if (chartType === 'scatter' && selection.zValue && zField && String(row[zField] ?? '') !== selection.zValue) return false;
  return true;
}

function parseNumericBucketRange(label: string): { start: number; end: number } | null {
  const match = label.trim().match(/^(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  return Number.isFinite(start) && Number.isFinite(end) ? { start, end } : null;
}

function bucketValue(value: unknown, bucket: string): string | null {
  const date = toDate(value);
  if (!date) return null;
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth() + 1;
  const day = date.getUTCDate();
  if (bucket === 'day') return `${year}-${pad(month)}-${pad(day)}`;
  if (bucket === 'week') {
    const start = new Date(Date.UTC(year, date.getUTCMonth(), day));
    const firstDay = start.getUTCDay() || 7;
    start.setUTCDate(start.getUTCDate() - firstDay + 1);
    return `${start.getUTCFullYear()}-W${pad(getIsoWeek(start))}`;
  }
  if (bucket === 'month') return `${year}-${pad(month)}`;
  if (bucket === 'quarter') return `${year}-Q${Math.floor((month - 1) / 3) + 1}`;
  if (bucket === 'year') return `${year}`;
  return null;
}

function toDate(value: unknown): Date | null {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value;
  const date = new Date(String(value ?? ''));
  return Number.isNaN(date.getTime()) ? null : date;
}

function pad(value: number) {
  return String(value).padStart(2, '0');
}

function getIsoWeek(date: Date) {
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNumber = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - dayNumber);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  return Math.ceil((((target.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
}

export function extractSelectionFromClick(
  spec: ChartSpec,
  params: ChartClickParams,
  left: number,
  top: number,
): ChartSelection | null {
  if (params.componentType !== 'series') return null;
  const data = readEventDataRecord(params.data);
  const point = Array.isArray(params.value) ? params.value : [];
  const xValue = spec.config.chartType === 'rankingSlope' && params.seriesName
    ? params.seriesName
    : typeof data?.xValue === 'string'
      ? data.xValue
      : String(params.name ?? point[0] ?? '');
  if (!xValue) return null;
  const groupValue = typeof data?.groupValue === 'string'
    ? data.groupValue
    : parseGroupFromSeriesName(params.seriesName);
  const yValue = typeof data?.yValue === 'string'
    ? data.yValue
    : spec.config.chartType === 'scatter' && point.length > 1
      ? String(point[1] ?? '')
      : undefined;
  const zValue = typeof data?.zValue === 'string'
    ? data.zValue
    : spec.config.chartType === 'scatter' && point.length > 2
      ? String(point[2] ?? '')
      : undefined;

  return {
    xValue,
    groupValue,
    yValue,
    zValue,
    seriesName: params.seriesName,
    left,
    top,
  };
}

function buildSelectionPrompt(spec: ChartSpec, selection: ChartSelection) {
  const parts = [
    `Explain the business meaning of ${selection.xValue}`,
    selection.groupValue ? `for ${selection.groupValue}` : '',
    `in the chart "${spec.config.title || 'Chart'}".`,
  ].filter(Boolean);
  return `${parts.join(' ')} Focus on what stands out, likely drivers, and any recommended follow-up breakdown.`;
}

export function InteractiveChart({
  spec,
  onOpenPrompt,
  onAskAboutSelection,
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
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const chartType = spec.config.chartType ?? 'bar';
  const [contextSelection, setContextSelection] = useState<ChartSelection | null>(null);
  const [activeFilter, setActiveFilter] = useState<ChartSelection | null>(null);
  const [showRows, setShowRows] = useState(false);
  const normalizationNotes = useMemo(
    () => readMetaStringArray(spec, 'normalizationNotes'),
    [spec],
  );
  const fallbackApplied = useMemo(
    () => readMetaBoolean(spec, 'fallbackApplied'),
    [spec],
  );
  const headerNoteFull = useMemo(
    () => buildHeaderNote(spec, fallbackApplied, normalizationNotes.length > 0),
    [fallbackApplied, normalizationNotes, spec],
  );
  const headerNotePreview = useMemo(
    () => (headerNoteFull ? truncateText(headerNoteFull.replace(/\s+/g, ' '), 140) : null),
    [headerNoteFull],
  );
  const source = useMemo(() => readMetaString(spec, 'source'), [spec]);
  const businessInsightFull = useMemo(
    () => readMetaString(spec, 'businessInsight'),
    [spec],
  );
  const businessInsightPreview = useMemo(
    () => (businessInsightFull ? truncateText(businessInsightFull.replace(/\s+/g, ' '), 140) : null),
    [businessInsightFull],
  );
  const filteredChartData = useMemo(
    () => (activeFilter ? spec.chartData.filter((row) => matchesSelection(row, spec, activeFilter)) : spec.chartData),
    [activeFilter, spec],
  );
  const filteredDownloadData = useMemo(() => {
    const sourceRows = spec.downloadData ?? spec.chartData;
    return activeFilter ? sourceRows.filter((row) => matchesSelection(row, spec, activeFilter)) : sourceRows;
  }, [activeFilter, spec]);
  const visibleDescription = useMemo(
    () => (businessInsightPreview ? businessInsightPreview : source === 'manual' ? spec.config.description : undefined),
    [businessInsightPreview, source, spec.config.description],
  );
  const displaySpec = useMemo(() => ({
    ...spec,
    chartData: filteredChartData,
    downloadData: filteredDownloadData,
    totalRows: activeFilter ? filteredDownloadData.length : spec.totalRows,
    config: {
      ...spec.config,
      description: visibleDescription,
      style: {
        ...spec.config.style,
        showDescription: Boolean(visibleDescription),
      },
    },
  }), [activeFilter, filteredChartData, filteredDownloadData, spec, visibleDescription]);
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
    const data = filteredDownloadData;
    const csv = toCsv(data);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'results.csv';
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredDownloadData]);

  const handleFilterSelection = useCallback(() => {
    if (!contextSelection) return;
    setActiveFilter(contextSelection);
    setShowRows(false);
    setContextSelection(null);
  }, [contextSelection]);

  const handleAskSelection = useCallback(() => {
    if (!contextSelection) return;
    onAskAboutSelection?.(buildSelectionPrompt(spec, contextSelection));
    setContextSelection(null);
  }, [contextSelection, onAskAboutSelection, spec]);

  const handleShowRows = useCallback(() => {
    if (!contextSelection) return;
    setActiveFilter(contextSelection);
    setShowRows(true);
    setContextSelection(null);
  }, [contextSelection]);

  useEffect(() => {
    if (!contextSelection) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target)) return;
      setContextSelection(null);
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => window.removeEventListener('mousedown', onPointerDown);
  }, [contextSelection]);

  const chartEvents = useMemo(() => ({
    click: (params: ChartClickParams) => {
      const rect = containerRef.current?.getBoundingClientRect();
      const nativeEvent = params.event?.event;
      const left = rect && nativeEvent ? nativeEvent.clientX - rect.left : 16;
      const top = rect && nativeEvent ? nativeEvent.clientY - rect.top : 16;
      const selection = extractSelectionFromClick(spec, params, left, top);
      if (selection) setContextSelection(selection);
    },
  }), [spec]);

  return (
    <div ref={containerRef} className="my-4 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
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

      {activeFilter && (
        <div className="mb-3 flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
          <span className="rounded bg-zinc-100 px-2 py-1 dark:bg-zinc-800">
            Filtered to {activeFilter.xValue}{activeFilter.groupValue ? ` / ${activeFilter.groupValue}` : ''}
          </span>
          <Button type="button" variant="ghost" size="sm" onClick={() => { setActiveFilter(null); setShowRows(false); }}>
            Clear
          </Button>
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
          onEvents={chartEvents}
          style={{ height: 400, width: '100%' }}
          opts={{ renderer: 'svg' }}
          notMerge
        />
        {contextSelection && (
          <div
            ref={menuRef}
            className="absolute z-20 min-w-44 rounded-md border border-zinc-200 bg-white p-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
            style={{
              left: Math.min(contextSelection.left, Math.max(16, (containerRef.current?.clientWidth ?? 260) - 210)),
              top: Math.min(contextSelection.top, 320),
            }}
          >
            <div className="px-2 py-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              {contextSelection.xValue}{contextSelection.groupValue ? ` • ${contextSelection.groupValue}` : ''}
            </div>
            <button type="button" className="flex w-full rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800" onClick={handleFilterSelection}>
              Filter to this
            </button>
            <button type="button" className="flex w-full rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800" onClick={handleAskSelection}>
              Ask about this
            </button>
            <button type="button" className="flex w-full rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800" onClick={handleShowRows}>
              Show rows
            </button>
          </div>
        )}
      </div>

      {showRows && (
        <div className="mt-3 rounded-md border border-zinc-200 dark:border-zinc-700">
          <div className="border-b border-zinc-200 px-3 py-2 text-xs font-medium text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
            Underlying rows ({filteredDownloadData.length})
          </div>
          <div className="max-h-56 overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900">
                <tr>
                  {Object.keys(filteredDownloadData[0] ?? {}).map((column) => (
                    <th key={column} className="px-3 py-2 text-left font-medium text-zinc-600 dark:text-zinc-300">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredDownloadData.slice(0, 12).map((row, index) => (
                  <tr key={index} className="border-t border-zinc-100 dark:border-zinc-800">
                    {Object.keys(filteredDownloadData[0] ?? {}).map((column) => (
                      <td key={column} className="px-3 py-2 text-zinc-700 dark:text-zinc-200">
                        {String(row[column] ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
