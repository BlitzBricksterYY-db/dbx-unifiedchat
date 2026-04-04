import type { EChartsOption } from 'echarts';
import { z } from 'zod';

export const chartTypes = [
  'bar',
  'line',
  'scatter',
  'pie',
  'stackedBar',
  'normalizedStackedBar',
  'area',
  'stackedArea',
  'heatmap',
  'boxplot',
  'dualAxis',
  'rankingSlope',
  'deltaComparison',
] as const;

const chartFormats = ['currency', 'number', 'percent'] as const;
const fieldKinds = ['numeric', 'date', 'text'] as const;
const fieldRoles = ['dimension', 'measure', 'time', 'id', 'currency', 'percent', 'unknown'] as const;
const chartFormatSchema = z.enum(chartFormats).optional();
const seriesChartTypeSchema = z.enum(['bar', 'line', 'area']).optional().nullable();
const seriesAxisSchema = z.enum(['primary', 'secondary']).optional().nullable();
const fieldKindSchema = z.enum(fieldKinds);
const fieldRoleSchema = z.enum(fieldRoles);

const referenceLineSchema = z.object({
  value: z.number(),
  label: z.string().optional().default(''),
  axis: z.enum(['primary', 'secondary']).optional().default('primary'),
});

const transformSchema = z
  .object({
    type: z
      .enum([
        'topN',
        'frequency',
        'timeBucket',
        'histogram',
        'percentOfTotal',
        'heatmap',
        'boxplot',
        'rankingSlope',
        'deltaComparison',
      ])
      .optional(),
    compareLabels: z.array(z.string()).optional().nullable(),
  })
  .passthrough()
  .optional()
  .nullable();

const chartStyleSchema = z
  .object({
    palette: z.string().optional(),
    color: z.string().optional(),
    showLegend: z.boolean().optional(),
    showLabels: z.boolean().optional(),
    showGridLines: z.boolean().optional(),
    showTitle: z.boolean().optional(),
    showDescription: z.boolean().optional(),
    smoothLines: z.boolean().optional(),
    xAxisLabelRotation: z.number().min(0).max(90).optional(),
    yAxisLabelRotation: z.number().min(0).max(90).optional(),
  })
  .optional()
  .nullable();

const seriesSchema = z.object({
  field: z.string().min(1),
  name: z.string().min(1),
  format: chartFormatSchema,
  chartType: seriesChartTypeSchema,
  axis: seriesAxisSchema,
});

const chartMetaSchema = z
  .object({
    chartId: z.string().optional(),
    sourceTableId: z.string().optional(),
    source: z.enum(['auto', 'manual', 'natural-language']).optional(),
    rationale: z.string().optional().nullable(),
    confidence: z.number().min(0).max(1).optional().nullable(),
    previewLimited: z.boolean().optional(),
    sourceRowCount: z.number().optional(),
  })
  .passthrough()
  .optional()
  .nullable();

const chartConfigSchema = z
  .object({
    chartType: z.enum(chartTypes),
    title: z.string().optional(),
    description: z.string().optional().nullable(),
    xAxisField: z.string().optional().nullable(),
    yAxisField: z.string().optional().nullable(),
    zAxisField: z.string().optional().nullable(),
    groupByField: z.string().optional().nullable(),
    layout: z.enum(['grouped', 'stacked', 'normalized']).optional().nullable(),
    series: z.array(seriesSchema).min(1).max(3),
    toolbox: z.boolean().optional(),
    supportedChartTypes: z.array(z.enum(chartTypes)).optional(),
    referenceLines: z.array(referenceLineSchema).optional(),
    compareLabels: z.array(z.string()).optional().nullable(),
    transform: transformSchema,
    style: chartStyleSchema,
  })
  .passthrough();

export const chartSpecSchema = z
  .object({
    config: chartConfigSchema,
    chartData: z.array(z.record(z.string(), z.unknown())).max(400),
    downloadData: z.array(z.record(z.string(), z.unknown())).optional(),
    totalRows: z.number().optional(),
    aggregated: z.boolean().optional(),
    aggregationNote: z.string().nullable().optional(),
    meta: chartMetaSchema,
  })
  .passthrough();

const tableDownloadPayloadSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.unknown())),
  totalRows: z.number().optional(),
  previewRowCount: z.number().optional(),
  isPreview: z.boolean().optional(),
  filename: z.string().optional(),
  title: z.string().optional(),
  sql: z.string().optional(),
  sqlFilename: z.string().optional(),
});

const workspaceFieldSchema = z.object({
  name: z.string(),
  label: z.string(),
  kind: fieldKindSchema,
  role: fieldRoleSchema,
  format: chartFormatSchema,
  uniqueCount: z.number().int().nonnegative(),
  uniqueRatio: z.number().min(0).max(1),
});

export const chartWorkspaceSchema = z.object({
  workspaceId: z.string(),
  title: z.string(),
  description: z.string().optional().nullable(),
  table: tableDownloadPayloadSchema,
  charts: z.array(chartSpecSchema).min(1),
  fields: z.array(workspaceFieldSchema).optional(),
  sourceMeta: z
    .object({
      queryIndex: z.number().optional(),
      label: z.string().optional().nullable(),
      sqlExplanation: z.string().optional().nullable(),
      rowGrainHint: z.string().optional().nullable(),
      previewLimited: z.boolean().optional(),
      totalRows: z.number().optional(),
      dataCacheKey: z.string().optional().nullable(),
    })
    .optional()
    .nullable(),
});

export type ChartSpec = z.infer<typeof chartSpecSchema>;
export type ChartWorkspace = z.infer<typeof chartWorkspaceSchema>;
export type ChartField = z.infer<typeof workspaceFieldSchema>;
export type ChartType = (typeof chartTypes)[number];
export type ChartFormat = (typeof chartFormats)[number];

export type ChartBuilderState = {
  mode: 'replace' | 'add';
  title: string;
  description: string;
  chartType: ChartType;
  xAxisField: string;
  yAxisField: string;
  secondaryYAxisField: string;
  groupByField: string;
  zAxisField: string;
  aggregation: 'sum' | 'avg' | 'count' | 'min' | 'max';
  timeBucket: 'none' | 'day' | 'week' | 'month' | 'quarter' | 'year';
  topN: number | null;
  sortDirection: 'asc' | 'desc';
  palette: string;
  color: string;
  showLegend: boolean;
  showLabels: boolean;
  showGridLines: boolean;
  smoothLines: boolean;
  xAxisLabelRotation: number;
  yAxisLabelRotation: number;
  showTitle: boolean;
  showDescription: boolean;
};

const PALETTE_MAP: Record<string, string[]> = {
  default: ['#2563eb', '#14b8a6', '#9333ea', '#f59e0b', '#ef4444', '#6366f1'],
  cool: ['#0ea5e9', '#14b8a6', '#22c55e', '#8b5cf6', '#6366f1'],
  warm: ['#f97316', '#f59e0b', '#ef4444', '#ec4899', '#a855f7'],
  neutral: ['#2563eb', '#6b7280', '#14b8a6', '#a3a3a3', '#374151'],
};

export function parseChartSpec(raw: unknown): ChartSpec | null {
  const parsed = typeof raw === 'string' ? safeParseJson(raw) : raw;
  if (!parsed) return null;
  const result = chartSpecSchema.safeParse(parsed);
  return result.success ? result.data : null;
}

export function parseChartWorkspace(raw: unknown): ChartWorkspace | null {
  const parsed = typeof raw === 'string' ? safeParseJson(raw) : raw;
  if (!parsed) return null;
  const result = chartWorkspaceSchema.safeParse(parsed);
  return result.success ? result.data : null;
}

export function getSelectableChartTypes(spec: ChartSpec): string[] {
  const supported = spec.config.supportedChartTypes?.filter(Boolean);
  return supported && supported.length > 0 ? supported : ['bar', 'line', 'scatter', 'pie'];
}

export function getWorkspaceFields(workspace: ChartWorkspace): ChartField[] {
  return workspace.fields?.length
    ? workspace.fields
    : inferFieldsFromTable(workspace.table.columns, workspace.table.rows);
}

export function createBuilderStateFromChart(
  chart: ChartSpec,
  workspace: ChartWorkspace,
  mode: 'replace' | 'add' = 'replace',
): ChartBuilderState {
  const fields = getWorkspaceFields(workspace);
  const numericFields = fields.filter((field) => field.kind === 'numeric' && field.role !== 'id');
  const defaultX = chart.config.xAxisField ?? pickDefaultXField(fields);
  const primarySeries = chart.config.series[0];
  const secondarySeries = chart.config.series.find((series) => series.axis === 'secondary');
  return {
    mode,
    title: chart.config.title ?? workspace.title,
    description: chart.config.description ?? '',
    chartType: chart.config.chartType,
    xAxisField: defaultX ?? '',
    yAxisField: primarySeries?.field ?? numericFields[0]?.name ?? '',
    secondaryYAxisField: secondarySeries?.field ?? '',
    groupByField: chart.config.groupByField ?? '',
    zAxisField: chart.config.zAxisField ?? '',
    aggregation: resolveAggregation(chart.config.transform),
    timeBucket: resolveTimeBucket(chart.config.transform),
    topN: resolveTopN(chart.config.transform),
    sortDirection: resolveSortDirection(chart.config.transform, chart.config.chartType),
    palette: chart.config.style?.palette ?? 'default',
    color: chart.config.style?.color ?? '',
    showLegend: chart.config.style?.showLegend ?? true,
    showLabels: chart.config.style?.showLabels ?? false,
    showGridLines: chart.config.style?.showGridLines ?? true,
    smoothLines: chart.config.style?.smoothLines ?? true,
    xAxisLabelRotation: chart.config.style?.xAxisLabelRotation ?? 0,
    yAxisLabelRotation: chart.config.style?.yAxisLabelRotation ?? 0,
    showTitle: chart.config.style?.showTitle ?? true,
    showDescription: chart.config.style?.showDescription ?? true,
  };
}

export function validateBuilderState(
  state: ChartBuilderState,
  workspace: ChartWorkspace,
): { valid: boolean; issues: string[] } {
  const fields = getWorkspaceFields(workspace);
  const fieldByName = new Map(fields.map((field) => [field.name, field]));
  const issues: string[] = [];

  if (!state.xAxisField) issues.push('Choose an X axis field.');
  if (!state.yAxisField && state.chartType !== 'pie' && state.chartType !== 'rankingSlope' && state.chartType !== 'deltaComparison') {
    issues.push('Choose a primary Y axis field.');
  }

  const xField = fieldByName.get(state.xAxisField);
  const yField = fieldByName.get(state.yAxisField);
  const groupField = fieldByName.get(state.groupByField);

  if (state.chartType === 'scatter') {
    if (xField?.kind !== 'numeric') issues.push('Scatter charts require a numeric X axis.');
    if (yField?.kind !== 'numeric') issues.push('Scatter charts require a numeric Y axis.');
  }

  if (state.chartType === 'pie' && groupField) {
    issues.push('Pie charts use a single category field and do not support grouping.');
  }

  if (state.groupByField && groupField?.uniqueCount && groupField.uniqueCount > 12) {
    issues.push('Breakdown fields with many categories are hard to read; choose a lower-cardinality field or use Top N.');
  }

  if ((state.chartType === 'line' || state.chartType === 'area' || state.chartType === 'stackedArea') && xField?.kind === 'text' && xField.uniqueCount > 20) {
    issues.push('Long trend charts are easier to read with a time field or fewer categories.');
  }

  if (state.chartType === 'pie' && xField?.uniqueCount && xField.uniqueCount > 6) {
    issues.push('Pie charts are limited to about six categories. Use Top N or choose a different chart type.');
  }

  return { valid: issues.length === 0, issues };
}

export function materializeChartSpecFromBuilder(
  workspace: ChartWorkspace,
  builder: ChartBuilderState,
  existing?: ChartSpec,
  source: 'manual' | 'natural-language' = 'manual',
): ChartSpec {
  const fields = getWorkspaceFields(workspace);
  const rows = workspace.table.rows;
  const fieldByName = new Map(fields.map((field) => [field.name, field]));
  const xField = builder.xAxisField || pickDefaultXField(fields);
  const yField = builder.yAxisField || pickDefaultYField(fields);
  const secondaryField = builder.secondaryYAxisField || '';
  const groupField = builder.groupByField || '';
  const zField = builder.zAxisField || '';
  const chartType = builder.chartType;
  const xMeta = fieldByName.get(xField);
  const yMeta = fieldByName.get(yField);
  const series = buildSeriesConfig(builder, fieldByName, yField, secondaryField);

  let chartData: Record<string, unknown>[] = [];
  let aggregated = false;
  let aggregationNote: string | null = null;
  let transform: Record<string, unknown> | null = null;
  let layout: ChartSpec['config']['layout'] = normalizeLayoutFromBuilder(builder);

  if (chartType === 'scatter') {
    chartData = buildScatterChartData(rows, xField, yField, groupField, zField);
  } else if (chartType === 'heatmap') {
    chartData = buildHeatmapChartData(rows, xField, groupField, yField, builder.aggregation);
    aggregated = true;
    aggregationNote = `Aggregated ${prettifyLabel(yField)} by ${prettifyLabel(xField)} and ${prettifyLabel(groupField)}`;
    transform = { type: 'heatmap' };
  } else if (chartType === 'boxplot') {
    chartData = buildBoxplotChartData(rows, xField, yField);
    aggregated = true;
    aggregationNote = `Summarized ${prettifyLabel(yField)} into boxplot statistics`;
    transform = { type: 'boxplot', field: yField };
  } else if (chartType === 'pie') {
    chartData = buildAggregatedChartData(rows, xField, yField, '', builder);
    chartData = applyTopN(chartData, xField, yField, Math.min(builder.topN ?? 6, 6));
    aggregated = true;
    aggregationNote = `Aggregated ${prettifyLabel(yField)} by ${prettifyLabel(xField)}`;
  } else {
    const bucket = shouldBucketTime(builder, xMeta) ? builder.timeBucket : 'none';
    chartData = buildAggregatedChartData(rows, xField, yField, groupField, builder, secondaryField, bucket);
    aggregated = chartData.length > 0;
    if (groupField && layout === 'normalized') {
      chartData = normalizeGroupedPercent(chartData, xField, groupField, [yField, secondaryField].filter(Boolean));
      aggregationNote = `Converted grouped values to percent-of-total within each ${prettifyLabel(xField)}`;
    } else if (bucket !== 'none') {
      aggregationNote = `Bucketed ${prettifyLabel(yField)} by ${bucket}`;
      transform = { type: 'timeBucket', field: xField, bucket, metric: yField, function: builder.aggregation };
    } else {
      aggregationNote = `Aggregated ${prettifyLabel(yField)} by ${prettifyLabel(xField)}`;
    }
    if (builder.topN && xMeta?.kind === 'text' && chartData.length > builder.topN) {
      chartData = applyTopN(chartData, xField, yField, builder.topN, groupField, secondaryField || undefined);
      aggregationNote = `${aggregationNote} • Top ${builder.topN} categories`;
      transform = { ...(transform ?? {}), type: 'topN', metric: yField, n: builder.topN };
    }
  }

  const description = builder.description.trim()
    || [
      builder.groupByField ? `Break down by ${prettifyLabel(builder.groupByField)}` : '',
      workspace.sourceMeta?.previewLimited ? 'Preview-limited rows' : '',
    ]
      .filter(Boolean)
      .join(' • ');

  const supportedChartTypes = getSupportedTypesFromBuilder(builder, xMeta?.kind);

  return {
    config: {
      chartType,
      title: builder.title.trim() || workspace.title,
      description: description || undefined,
      xAxisField: xField,
      yAxisField: chartType === 'heatmap' ? yField : null,
      zAxisField: zField || null,
      groupByField: groupField || null,
      layout,
      series,
      toolbox: true,
      supportedChartTypes,
      referenceLines: existing?.config.referenceLines ?? [],
      compareLabels: existing?.config.compareLabels ?? null,
      transform,
      style: {
        palette: builder.palette,
        color: builder.color || undefined,
        showLegend: builder.showLegend,
        showLabels: builder.showLabels,
        showGridLines: builder.showGridLines,
        showTitle: builder.showTitle,
        showDescription: builder.showDescription,
        smoothLines: builder.smoothLines,
        xAxisLabelRotation: builder.xAxisLabelRotation,
        yAxisLabelRotation: builder.yAxisLabelRotation,
      },
    },
    chartData: chartData.slice(0, 400),
    downloadData: workspace.table.rows,
    totalRows: workspace.table.totalRows ?? workspace.table.rows.length,
    aggregated,
    aggregationNote,
    meta: {
      chartId: existing?.meta?.chartId ?? `${workspace.workspaceId}-${cryptoSafeId()}`,
      sourceTableId: workspace.workspaceId,
      source,
      rationale: source === 'manual' ? 'Customized from manual chart builder controls.' : 'Generated from a natural-language chart request.',
      confidence: source === 'manual' ? 1 : 0.72,
      previewLimited: workspace.table.isPreview ?? workspace.sourceMeta?.previewLimited,
      sourceRowCount: workspace.table.totalRows ?? workspace.table.rows.length,
    },
  };
}

export function inferFieldsFromTable(
  columns: string[],
  rows: Array<Record<string, unknown>>,
): ChartField[] {
  const sampleSize = Math.min(rows.length, 50);
  return columns.map((column) => {
    const values = rows.slice(0, sampleSize).map((row) => row[column]).filter((value) => value != null);
    const uniqueCount = new Set(values.map((value) => String(value))).size;
    const uniqueRatio = sampleSize > 0 ? uniqueCount / sampleSize : 0;
    const kind = inferFieldKind(values);
    const format = inferFieldFormat(column);
    const role = inferFieldRole(column, kind, uniqueRatio, format);
    return {
      name: column,
      label: prettifyLabel(column),
      kind,
      role,
      format,
      uniqueCount,
      uniqueRatio,
    };
  });
}

export function buildOption(spec: ChartSpec, overrideType?: string): EChartsOption {
  const config = spec.config;
  const requestedType = overrideType && chartTypes.includes(overrideType as ChartType)
    ? overrideType
    : undefined;
  const type = (requestedType ?? config.chartType) as ChartType;

  if (type === 'heatmap') return buildHeatmapOption(spec);
  if (type === 'boxplot') return buildBoxplotOption(spec);
  if (type === 'rankingSlope') return buildRankingSlopeOption(spec);
  if (type === 'deltaComparison') return buildDeltaComparisonOption(spec);
  if (type === 'pie') return buildPieOption(spec);
  if (type === 'scatter') return buildScatterOption(spec);
  return buildCartesianOption(spec, type);
}

function safeParseJson(raw: string): unknown | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function buildPieOption(spec: ChartSpec): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const firstSeries = spec.config.series[0];
  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll', show: spec.config.style?.showLegend ?? true },
    series: [
      {
        type: 'pie',
        radius: ['30%', '65%'],
        label: { show: spec.config.style?.showLabels ?? false },
        itemStyle: spec.config.style?.color ? { color: spec.config.style.color } : undefined,
        data: spec.chartData.map((row) => ({
          name: String(row[xField] ?? ''),
          value: Number(row[firstSeries?.field ?? ''] ?? 0),
        })),
      },
    ],
  };
}

function buildHeatmapOption(spec: ChartSpec): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const yField = spec.config.yAxisField ?? spec.config.groupByField ?? '';
  const valueField = spec.config.series[0]?.field ?? 'value';
  const xValues = uniqueStrings(spec.chartData.map((row) => String(row[xField] ?? '')));
  const yValues = uniqueStrings(spec.chartData.map((row) => String(row[yField] ?? '')));
  const values = spec.chartData.map((row) => [
    xValues.indexOf(String(row[xField] ?? '')),
    yValues.indexOf(String(row[yField] ?? '')),
    Number(row[valueField] ?? 0),
  ]);
  const maxValue = Math.max(0, ...values.map((item) => Number(item[2])));

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      formatter: (params: any) => {
        const value = Array.isArray(params.value) ? params.value[2] : 0;
        return `${xValues[params.value[0]]} / ${yValues[params.value[1]]}: ${formatValue(value, spec.config.series[0]?.format)}`;
      },
    },
    grid: { left: '8%', right: '8%', top: titleTop(spec), bottom: '18%', containLabel: true },
    xAxis: { type: 'category', data: xValues, splitArea: { show: true } },
    yAxis: { type: 'category', data: yValues, splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: maxValue,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
    },
    series: [
      {
        type: 'heatmap',
        data: values,
        label: { show: spec.config.style?.showLabels ?? false },
        emphasis: { itemStyle: { shadowBlur: 8 } },
      },
    ],
  };
}

function buildBoxplotOption(spec: ChartSpec): EChartsOption {
  const xField = spec.config.xAxisField ?? 'label';
  const labels = spec.chartData.map((row) => String(row[xField] ?? ''));
  const data = spec.chartData.map((row) => [
    Number(row.min ?? 0),
    Number(row.q1 ?? 0),
    Number(row.median ?? 0),
    Number(row.q3 ?? 0),
    Number(row.max ?? 0),
  ]);
  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const values = Array.isArray((params as { data?: unknown }).data)
          ? ((params as { data: number[] }).data)
          : [0, 0, 0, 0, 0];
        return `${(params as { name?: string }).name ?? ''}<br/>Min: ${formatValue(values[0], spec.config.series[0]?.format)}<br/>Q1: ${formatValue(values[1], spec.config.series[0]?.format)}<br/>Median: ${formatValue(values[2], spec.config.series[0]?.format)}<br/>Q3: ${formatValue(values[3], spec.config.series[0]?.format)}<br/>Max: ${formatValue(values[4], spec.config.series[0]?.format)}`;
      },
    },
    legend: { show: false },
    grid: { left: '6%', right: '4%', top: titleTop(spec), bottom: '16%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: {
        interval: 0,
        rotate: spec.config.style?.xAxisLabelRotation ?? (labels.length > 8 ? 30 : 0),
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: axisLabelFormatter(spec.config.series[0]?.format),
    },
    series: [{ type: 'boxplot', data }],
  };
}

function buildRankingSlopeOption(spec: ChartSpec): EChartsOption {
  const labels =
    spec.config.compareLabels ??
    spec.config.transform?.compareLabels ??
    uniqueStrings(
      spec.chartData.flatMap((row) => [String(row.startLabel ?? ''), String(row.endLabel ?? '')]),
    ).filter(Boolean);

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, type: 'scroll', show: spec.config.style?.showLegend ?? true },
    grid: { left: '4%', right: '4%', top: titleTop(spec), bottom: '18%', containLabel: true },
    xAxis: { type: 'category', data: labels.length === 2 ? labels : ['Start', 'End'] },
    yAxis: { type: 'value', inverse: true, minInterval: 1 },
    series: spec.chartData.map((row) => ({
      type: 'line',
      name: String(row[spec.config.xAxisField ?? 'entity'] ?? ''),
      smooth: spec.config.style?.smoothLines ?? true,
      data: [Number(row.startRank ?? 0), Number(row.endRank ?? 0)],
      label: {
        show: spec.config.style?.showLabels ?? true,
        formatter: ({ dataIndex }: { dataIndex: number }) =>
          dataIndex === 0 ? String(row[spec.config.xAxisField ?? 'entity'] ?? '') : '',
      },
      emphasis: { focus: 'series' as const },
    })),
  };
}

function buildDeltaComparisonOption(spec: ChartSpec): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const values = spec.chartData.map((row) => Number(row.delta ?? 0));
  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => formatValue(Number(value), spec.config.series[0]?.format),
    },
    grid: { left: '5%', right: '4%', top: titleTop(spec), bottom: '18%', containLabel: true },
    xAxis: {
      type: 'category',
      data: spec.chartData.map((row) => String(row[xField] ?? '')),
      axisLabel: {
        interval: 0,
        rotate: spec.config.style?.xAxisLabelRotation ?? (spec.chartData.length > 8 ? 30 : 0),
      },
    },
    yAxis: { type: 'value', axisLabel: axisLabelFormatter(spec.config.series[0]?.format) },
    series: [
      {
        type: 'bar',
        label: { show: spec.config.style?.showLabels ?? false },
        data: values,
        itemStyle: {
          color: (params) =>
            spec.config.style?.color
              ? spec.config.style.color
              : Number(params.value) >= 0
                ? '#2563eb'
                : '#dc2626',
        },
      },
    ],
  };
}

function buildScatterOption(spec: ChartSpec): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const yField = spec.config.series[0]?.field ?? '';
  const sizeField = spec.config.zAxisField ?? '';
  const groupField = spec.config.groupByField ?? '';
  const groups = groupField
    ? uniqueStrings(spec.chartData.map((row) => String(row[groupField] ?? ''))).filter(Boolean)
    : ['All rows'];

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        const point = Array.isArray(params.value) ? params.value : [];
        return [
          params.seriesName,
          `${prettifyLabel(xField)}: ${formatValue(Number(point[0] ?? 0), 'number')}`,
          `${prettifyLabel(yField)}: ${formatValue(Number(point[1] ?? 0), spec.config.series[0]?.format)}`,
          sizeField ? `${prettifyLabel(sizeField)}: ${formatValue(Number(point[2] ?? 0), 'number')}` : '',
        ]
          .filter(Boolean)
          .join('<br/>');
      },
    },
    legend: { bottom: 0, type: 'scroll', show: groups.length > 1 && (spec.config.style?.showLegend ?? true) },
    grid: { left: '6%', right: '4%', top: titleTop(spec), bottom: '18%', containLabel: true },
    xAxis: {
      type: 'value',
      name: prettifyLabel(xField),
      axisLabel: axisLabelFormatter('number'),
      splitLine: { show: spec.config.style?.showGridLines ?? true },
    },
    yAxis: {
      type: 'value',
      name: prettifyLabel(yField),
      axisLabel: axisLabelFormatter(spec.config.series[0]?.format),
      splitLine: { show: spec.config.style?.showGridLines ?? true },
    },
    series: groups.map((group) => {
      const groupRows = groupField
        ? spec.chartData.filter((row) => String(row[groupField] ?? '') === group)
        : spec.chartData;
      const sizeValues = groupRows.map((row) => Number(row[sizeField] ?? 0));
      const maxSize = Math.max(...sizeValues, 1);
      return {
        type: 'scatter',
        name: group,
        symbolSize: (value: number[]) => {
          if (!sizeField) return 10;
          const numericSize = Number(value[2] ?? 0);
          return Math.max(8, Math.min(28, (numericSize / maxSize) * 24));
        },
        label: { show: spec.config.style?.showLabels ?? false },
        itemStyle: spec.config.style?.color ? { color: spec.config.style.color } : undefined,
        data: groupRows.map((row) => [
          Number(row[xField] ?? 0),
          Number(row[yField] ?? 0),
          Number(row[sizeField] ?? 0),
        ]),
      };
    }),
  };
}

function buildCartesianOption(spec: ChartSpec, chartType: string): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const xValues = uniqueStrings(spec.chartData.map((row) => String(row[xField] ?? '')));
  const groupedSeries = spec.config.groupByField
    ? buildGroupedSeries(spec, chartType, xValues)
    : buildUngroupedSeries(spec, chartType, xValues);
  const hasSecondaryAxis = groupedSeries.some((series) => series.yAxisIndex === 1);
  const primarySeries = spec.config.series.find((series) => (series.axis ?? 'primary') !== 'secondary');
  const secondarySeries = spec.config.series.find((series) => series.axis === 'secondary');
  const primaryFormat = spec.config.series.find((series) => (series.axis ?? 'primary') !== 'secondary')?.format;
  const secondaryFormat = spec.config.series.find((series) => series.axis === 'secondary')?.format;
  const isPercentScale =
    spec.config.layout === 'normalized' ||
    spec.config.series.some((series) => series.format === 'percent') ||
    spec.config.chartType === 'normalizedStackedBar';

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: chartType.includes('line') || chartType.includes('area') ? 'line' : 'shadow' },
      valueFormatter: (value) => formatValue(Number(value), inferTooltipFormat(spec, Number(value))),
    },
    legend: { bottom: 0, type: 'scroll', show: spec.config.style?.showLegend ?? true },
    grid: { left: '4%', right: hasSecondaryAxis ? '8%' : '4%', bottom: '18%', top: titleTop(spec), containLabel: true },
    xAxis: {
      type: 'category',
      data: xValues,
      name: chartType === 'dualAxis' ? prettifyLabel(xField) : undefined,
      nameLocation: chartType === 'dualAxis' ? 'middle' : undefined,
      nameGap: chartType === 'dualAxis' ? 44 : undefined,
      nameTextStyle: chartType === 'dualAxis' ? axisNameTextStyle() : undefined,
      axisLabel: {
        color: '#a1a1aa',
        rotate: spec.config.style?.xAxisLabelRotation ?? (xValues.length > 8 ? 30 : 0),
        interval: 0,
      },
      axisLine: chartType === 'dualAxis' ? axisLineStyle() : undefined,
      axisTick: chartType === 'dualAxis' ? axisTickStyle() : undefined,
      splitLine: { show: false },
    },
    yAxis: buildYAxes(
      primaryFormat,
      secondaryFormat,
      isPercentScale,
      hasSecondaryAxis,
      spec.config.style?.showGridLines ?? true,
      chartType === 'dualAxis' ? primarySeries?.name ?? prettifyLabel(primarySeries?.field ?? '') : undefined,
      chartType === 'dualAxis' ? secondarySeries?.name ?? prettifyLabel(secondarySeries?.field ?? '') : undefined,
    ),
    dataZoom: spec.chartData.length > 15 ? [{ type: 'slider', bottom: 28 }] : undefined,
    toolbox: spec.config.toolbox ? { feature: { saveAsImage: {}, restore: {}, dataView: { readOnly: true } } } : undefined,
    series: groupedSeries as any,
  };
}

function buildGroupedSeries(spec: ChartSpec, chartType: string, xValues: string[]) {
  const groupField = spec.config.groupByField ?? '';
  const groups = uniqueStrings(spec.chartData.map((row) => String(row[groupField] ?? '')));
  const groupedRows = new Map<string, Map<string, Record<string, unknown>>>();
  for (const row of spec.chartData) {
    const xValue = String(row[spec.config.xAxisField ?? ''] ?? '');
    const groupValue = String(row[groupField] ?? '');
    if (!groupedRows.has(groupValue)) groupedRows.set(groupValue, new Map());
    groupedRows.get(groupValue)?.set(xValue, row);
  }

  return spec.config.series.flatMap((seriesSpec) =>
    groups.map((group) => {
      const renderType = resolveSeriesType(chartType, seriesSpec.chartType);
      return {
        name: `${seriesSpec.name} (${group})`,
        type: renderType === 'area' ? 'line' : renderType,
        smooth: renderType === 'line' || renderType === 'area' ? (spec.config.style?.smoothLines ?? true) : undefined,
        stack: shouldStack(spec.config.layout, chartType) ? `stack-${seriesSpec.field}` : undefined,
        areaStyle: renderType === 'area' || chartType === 'area' || chartType === 'stackedArea' ? {} : undefined,
        yAxisIndex: seriesSpec.axis === 'secondary' ? 1 : 0,
        markLine: buildMarkLine(spec.config.referenceLines, seriesSpec.axis ?? 'primary'),
        label: { show: spec.config.style?.showLabels ?? false },
        itemStyle: spec.config.style?.color ? { color: spec.config.style.color } : undefined,
        data: xValues.map((xValue) => Number(groupedRows.get(group)?.get(xValue)?.[seriesSpec.field] ?? 0)),
        emphasis: { focus: 'series' as const },
      };
    }),
  );
}

function buildUngroupedSeries(spec: ChartSpec, chartType: string, xValues: string[]) {
  const rowByX = new Map<string, Record<string, unknown>>();
  for (const row of spec.chartData) {
    rowByX.set(String(row[spec.config.xAxisField ?? ''] ?? ''), row);
  }

  return spec.config.series.map((seriesSpec) => {
    const renderType = resolveSeriesType(chartType, seriesSpec.chartType);
    return {
      name: seriesSpec.name,
      type: renderType === 'area' ? 'line' : renderType,
      smooth: renderType === 'line' || renderType === 'area' ? (spec.config.style?.smoothLines ?? true) : undefined,
      stack: shouldStack(spec.config.layout, chartType) ? `stack-${seriesSpec.axis ?? 'primary'}` : undefined,
      areaStyle: renderType === 'area' || chartType === 'area' || chartType === 'stackedArea' ? {} : undefined,
      yAxisIndex: chartType === 'dualAxis' && seriesSpec.axis === 'secondary' ? 1 : 0,
      markLine: buildMarkLine(spec.config.referenceLines, seriesSpec.axis ?? 'primary'),
      label: { show: spec.config.style?.showLabels ?? false },
      itemStyle: spec.config.style?.color ? { color: spec.config.style.color } : undefined,
      data: xValues.map((xValue) => Number(rowByX.get(xValue)?.[seriesSpec.field] ?? 0)),
      emphasis: { focus: 'series' as const },
    };
  });
}

function buildYAxes(
  primaryFormat: ChartSpec['config']['series'][number]['format'],
  secondaryFormat: ChartSpec['config']['series'][number]['format'],
  isPercentScale: boolean,
  hasSecondaryAxis: boolean,
  showGridLines: boolean,
  primaryName?: string,
  secondaryName?: string,
) {
  const axes: EChartsOption['yAxis'] = [
    {
      type: 'value',
      max: isPercentScale ? 100 : undefined,
      name: primaryName,
      nameLocation: 'middle',
      nameGap: 56,
      nameRotate: 90,
      nameTextStyle: primaryName ? axisNameTextStyle() : undefined,
      axisLabel: axisLabelFormatter(isPercentScale ? 'percent' : primaryFormat),
      axisLine: primaryName ? axisLineStyle() : undefined,
      axisTick: primaryName ? axisTickStyle() : undefined,
      splitLine: { show: showGridLines },
    },
  ];
  if (hasSecondaryAxis) {
    axes.push({
      type: 'value',
      max: secondaryFormat === 'percent' ? 100 : undefined,
      name: secondaryName,
      nameLocation: 'middle',
      nameGap: 56,
      nameRotate: -90,
      nameTextStyle: secondaryName ? axisNameTextStyle() : undefined,
      axisLabel: axisLabelFormatter(secondaryFormat),
      axisLine: secondaryName ? axisLineStyle() : undefined,
      axisTick: secondaryName ? axisTickStyle() : undefined,
      splitLine: { show: false },
    });
  }
  return axes;
}

function buildMarkLine(
  referenceLines: ChartSpec['config']['referenceLines'] | undefined,
  axis: 'primary' | 'secondary',
) {
  const lines = (referenceLines ?? []).filter((line) => (line.axis ?? 'primary') === axis);
  if (lines.length === 0) return undefined;
  return {
    symbol: 'none',
    label: {
      formatter: ({ data }: { data?: { name?: string; yAxis?: number } }) =>
        data?.name ?? `${data?.yAxis ?? ''}`,
    },
    data: lines.map((line) => ({ name: line.label ?? '', yAxis: line.value })),
  };
}

function shouldStack(layout: ChartSpec['config']['layout'], chartType: string) {
  return layout === 'stacked' || layout === 'normalized' || chartType === 'stackedBar' || chartType === 'stackedArea';
}

function resolveSeriesType(chartType: string, seriesType: ChartSpec['config']['series'][number]['chartType']) {
  if (seriesType && seriesType !== 'bar') return seriesType;
  if (chartType === 'area' || chartType === 'stackedArea') return 'area';
  if (chartType === 'line') return 'line';
  if (chartType === 'scatter') return 'scatter';
  return 'bar';
}

function inferTooltipFormat(spec: ChartSpec, value: number) {
  if (spec.config.layout === 'normalized' || spec.config.chartType === 'normalizedStackedBar') return 'percent';
  const matched = spec.config.series.find((series) => series.axis !== 'secondary')?.format;
  return matched ?? (Math.abs(value) <= 1 && value !== 0 ? 'percent' : 'number');
}

function axisLabelFormatter(format: ChartSpec['config']['series'][number]['format']) {
  if (format === 'currency') {
    return { color: '#a1a1aa', formatter: (value: number) => fmtCurrencyAxis(value) };
  }
  if (format === 'percent') {
    return { color: '#a1a1aa', formatter: (value: number) => `${Number(value).toFixed(0)}%` };
  }
  return { color: '#a1a1aa' };
}

function axisLineStyle() {
  return { lineStyle: { color: '#71717a', width: 1 } };
}

function axisTickStyle() {
  return { show: true, lineStyle: { color: '#71717a' } };
}

function axisNameTextStyle() {
  return { color: '#d4d4d8', fontWeight: 500 };
}

export function formatValue(value: number, format?: ChartSpec['config']['series'][number]['format']) {
  if (format === 'currency') {
    return value.toLocaleString('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    });
  }
  if (format === 'percent') return `${value.toFixed(1)}%`;
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function fmtCurrencyAxis(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value}`;
}

function resolvePalette(spec: ChartSpec): string[] | undefined {
  if (spec.config.style?.color) return [spec.config.style.color];
  return PALETTE_MAP[spec.config.style?.palette ?? 'default'] ?? PALETTE_MAP.default;
}

function buildTitleConfig(spec: ChartSpec) {
  if (spec.config.style?.showTitle === false) return { show: false };
  const text = spec.config.title?.trim();
  const subtext = spec.config.style?.showDescription === false
    ? undefined
    : spec.config.description?.trim() || undefined;
  if (!text && !subtext) return { show: false };
  return {
    text,
    subtext,
    left: 'center',
    textStyle: { fontSize: 14 },
    subtextStyle: { fontSize: 11, color: '#6b7280' },
  };
}

function titleTop(spec: ChartSpec) {
  if (spec.config.style?.showTitle === false) return '8%';
  const hasText = Boolean(spec.config.title?.trim());
  const hasSubtext = spec.config.style?.showDescription === false
    ? false
    : Boolean(spec.config.description?.trim());
  return hasText || hasSubtext ? '16%' : '8%';
}

function uniqueStrings(values: string[]) {
  return [...new Set(values)];
}

function inferFieldKind(values: unknown[]): ChartField['kind'] {
  if (values.length === 0) return 'text';
  if (values.every((value) => isNumericLike(value))) return 'numeric';
  if (values.every((value) => isDateLike(value))) return 'date';
  return 'text';
}

function inferFieldFormat(field: string): ChartField['format'] {
  const lowered = field.toLowerCase();
  if (/(amount|cost|paid|charge|price|spend|revenue|sales|allowed)/.test(lowered)) return 'currency';
  if (/(percent|pct|ratio|share|rate)/.test(lowered)) return 'percent';
  return 'number';
}

function inferFieldRole(
  field: string,
  kind: ChartField['kind'],
  uniqueRatio: number,
  format: ChartField['format'],
): ChartField['role'] {
  const lowered = field.toLowerCase();
  if (kind === 'date') return 'time';
  if (/(^id$|_id$|uuid|identifier|member_id|patient_id|claim_id)/.test(lowered)) return 'id';
  if (kind === 'numeric') {
    if (format === 'currency') return 'currency';
    if (format === 'percent') return 'percent';
    return uniqueRatio > 0.95 && !/(age|year|month|day|week|quarter|bin|bucket)/.test(lowered)
      ? 'id'
      : 'measure';
  }
  return 'dimension';
}

function pickDefaultXField(fields: ChartField[]): string {
  return (
    fields.find((field) => field.role === 'time')?.name
    ?? fields.find((field) => field.role === 'dimension' && field.uniqueRatio < 0.8)?.name
    ?? fields.find((field) => field.kind === 'text')?.name
    ?? fields[0]?.name
    ?? ''
  );
}

function pickDefaultYField(fields: ChartField[]): string {
  return (
    fields.find((field) => ['measure', 'currency', 'percent'].includes(field.role))?.name
    ?? fields.find((field) => field.kind === 'numeric' && field.role !== 'id')?.name
    ?? ''
  );
}

function buildSeriesConfig(
  builder: ChartBuilderState,
  fieldByName: Map<string, ChartField>,
  yField: string,
  secondaryField: string,
) {
  const primary = fieldByName.get(yField);
  const secondary = fieldByName.get(secondaryField);
  const series = [];
  if (yField) {
    series.push({
      field: yField,
      name: primary?.label ?? prettifyLabel(yField),
      format: primary?.format ?? 'number',
      chartType: builder.chartType === 'dualAxis' ? 'bar' : null,
      axis: 'primary' as const,
    });
  }
  if (secondaryField) {
    series.push({
      field: secondaryField,
      name: secondary?.label ?? prettifyLabel(secondaryField),
      format: secondary?.format ?? 'number',
      chartType: 'line',
      axis: 'secondary' as const,
    });
  }
  return series.length ? series : [{ field: yField, name: prettifyLabel(yField), format: 'number', chartType: null, axis: 'primary' as const }];
}

function buildScatterChartData(
  rows: Array<Record<string, unknown>>,
  xField: string,
  yField: string,
  groupField: string,
  zField: string,
) {
  return rows
    .map((row) => ({
      [xField]: numeric(row[xField]),
      [yField]: numeric(row[yField]),
      ...(groupField ? { [groupField]: String(row[groupField] ?? '') } : {}),
      ...(zField ? { [zField]: numeric(row[zField]) } : {}),
    }))
    .filter((row) => !Number.isNaN(Number(row[xField])) && !Number.isNaN(Number(row[yField])));
}

function buildAggregatedChartData(
  rows: Array<Record<string, unknown>>,
  xField: string,
  yField: string,
  groupField: string,
  builder: ChartBuilderState,
  secondaryField = '',
  bucket: ChartBuilderState['timeBucket'] = 'none',
) {
  const groups = new Map<string, { xValue: string; groupValue: string; yValues: number[]; secondaryValues: number[] }>();
  for (const row of rows) {
    const rawX = row[xField];
    const xValue = bucket !== 'none' ? bucketValue(rawX, bucket) : String(rawX ?? '');
    const groupedValue = groupField ? String(row[groupField] ?? '') : '';
    const key = `${xValue}:::${groupedValue}`;
    if (!groups.has(key)) {
      groups.set(key, { xValue, groupValue: groupedValue, yValues: [], secondaryValues: [] });
    }
    const bucketRef = groups.get(key)!;
    bucketRef.yValues.push(numeric(row[yField]));
    if (secondaryField) bucketRef.secondaryValues.push(numeric(row[secondaryField]));
  }

  const chartData = Array.from(groups.values()).map((entry) => ({
    [xField]: entry.xValue,
    ...(groupField ? { [groupField]: entry.groupValue } : {}),
    [yField]: aggregate(entry.yValues, builder.aggregation),
    ...(secondaryField ? { [secondaryField]: aggregate(entry.secondaryValues, builder.aggregation) } : {}),
  }));

  chartData.sort((left, right) => compareAxisValues(left[xField], right[xField], builder.sortDirection));
  return chartData;
}

function buildHeatmapChartData(
  rows: Array<Record<string, unknown>>,
  xField: string,
  groupField: string,
  yField: string,
  aggregation: ChartBuilderState['aggregation'],
) {
  const grouped = new Map<string, { xValue: string; groupValue: string; values: number[] }>();
  for (const row of rows) {
    const xValue = String(row[xField] ?? '');
    const groupValue = String(row[groupField] ?? '');
    const key = `${xValue}:::${groupValue}`;
    if (!grouped.has(key)) grouped.set(key, { xValue, groupValue, values: [] });
    grouped.get(key)?.values.push(numeric(row[yField]));
  }
  return Array.from(grouped.values()).map((entry) => ({
    [xField]: entry.xValue,
    [groupField]: entry.groupValue,
    [yField]: aggregate(entry.values, aggregation),
  }));
}

function buildBoxplotChartData(
  rows: Array<Record<string, unknown>>,
  xField: string,
  yField: string,
) {
  const grouped = new Map<string, number[]>();
  for (const row of rows) {
    const key = String(row[xField] ?? '');
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)?.push(numeric(row[yField]));
  }
  return Array.from(grouped.entries()).map(([label, values]) => {
    const sorted = values.filter((value) => !Number.isNaN(value)).sort((a, b) => a - b);
    return {
      [xField]: label,
      min: sorted[0] ?? 0,
      q1: quantile(sorted, 0.25),
      median: quantile(sorted, 0.5),
      q3: quantile(sorted, 0.75),
      max: sorted[sorted.length - 1] ?? 0,
    };
  });
}

function normalizeGroupedPercent(
  rows: Array<Record<string, unknown>>,
  xField: string,
  groupField: string,
  fields: string[],
) {
  const totals = new Map<string, Record<string, number>>();
  for (const row of rows) {
    const xValue = String(row[xField] ?? '');
    const current = totals.get(xValue) ?? {};
    for (const field of fields) {
      current[field] = (current[field] ?? 0) + numeric(row[field]);
    }
    totals.set(xValue, current);
  }
  return rows.map((row) => {
    const xValue = String(row[xField] ?? '');
    const currentTotals = totals.get(xValue) ?? {};
    const nextRow: Record<string, unknown> = {
      [xField]: row[xField],
      [groupField]: row[groupField],
    };
    for (const field of fields) {
      const denominator = currentTotals[field] || 1;
      nextRow[field] = (numeric(row[field]) / denominator) * 100;
    }
    return nextRow;
  });
}

function applyTopN(
  rows: Array<Record<string, unknown>>,
  xField: string,
  yField: string,
  limit: number,
  groupField = '',
  secondaryField?: string,
) {
  if (rows.length <= limit) return rows;
  const sorted = [...rows].sort((left, right) => numeric(right[yField]) - numeric(left[yField]));
  const topRows = sorted.slice(0, limit);
  const restRows = sorted.slice(limit);
  if (!groupField) {
    const rolled = {
      [xField]: 'Other',
      [yField]: restRows.reduce((sum, row) => sum + numeric(row[yField]), 0),
      ...(secondaryField
        ? {
            [secondaryField]: restRows.reduce((sum, row) => sum + numeric(row[secondaryField]), 0),
          }
        : {}),
    };
    return [...topRows, rolled];
  }

  const otherByGroup = new Map<string, Record<string, unknown>>();
  for (const row of restRows) {
    const group = String(row[groupField] ?? '');
    if (!otherByGroup.has(group)) {
      otherByGroup.set(group, { [xField]: 'Other', [groupField]: group, [yField]: 0, ...(secondaryField ? { [secondaryField]: 0 } : {}) });
    }
    const current = otherByGroup.get(group)!;
    current[yField] = numeric(current[yField]) + numeric(row[yField]);
    if (secondaryField) current[secondaryField] = numeric(current[secondaryField]) + numeric(row[secondaryField]);
  }
  return [...topRows, ...Array.from(otherByGroup.values())];
}

function resolveAggregation(transform: ChartSpec['config']['transform']): ChartBuilderState['aggregation'] {
  const fn = String(transform?.function ?? '').toLowerCase();
  return ['sum', 'avg', 'count', 'min', 'max'].includes(fn) ? (fn as ChartBuilderState['aggregation']) : 'sum';
}

function resolveTimeBucket(transform: ChartSpec['config']['transform']): ChartBuilderState['timeBucket'] {
  const bucket = String(transform?.bucket ?? '').toLowerCase();
  return ['day', 'week', 'month', 'quarter', 'year'].includes(bucket)
    ? (bucket as ChartBuilderState['timeBucket'])
    : 'none';
}

function resolveTopN(transform: ChartSpec['config']['transform']) {
  const value = Number(transform?.n ?? transform?.topN ?? 0);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function resolveSortDirection(
  transform: ChartSpec['config']['transform'],
  chartType: ChartType,
): ChartBuilderState['sortDirection'] {
  if (chartType === 'line' || chartType === 'area' || chartType === 'stackedArea') return 'asc';
  if (transform?.type === 'topN') return 'desc';
  return 'desc';
}

function normalizeLayoutFromBuilder(builder: ChartBuilderState): ChartSpec['config']['layout'] {
  if (builder.chartType === 'stackedBar' || builder.chartType === 'stackedArea') return 'stacked';
  if (builder.chartType === 'normalizedStackedBar') return 'normalized';
  return builder.groupByField ? 'grouped' : null;
}

function getSupportedTypesFromBuilder(
  builder: ChartBuilderState,
  xKind?: ChartField['kind'],
) {
  if (xKind === 'date') return ['line', 'area', 'stackedArea', 'bar'];
  if (builder.groupByField) return ['bar', 'line', 'area', 'stackedBar', 'normalizedStackedBar'];
  return ['bar', 'line', 'scatter', 'pie', 'heatmap', 'boxplot'];
}

function shouldBucketTime(builder: ChartBuilderState, field?: ChartField) {
  return field?.kind === 'date' && builder.timeBucket !== 'none';
}

function aggregate(values: number[], method: ChartBuilderState['aggregation']) {
  if (values.length === 0) return 0;
  if (method === 'count') return values.length;
  if (method === 'avg') return values.reduce((sum, value) => sum + value, 0) / values.length;
  if (method === 'min') return Math.min(...values);
  if (method === 'max') return Math.max(...values);
  return values.reduce((sum, value) => sum + value, 0);
}

function compareAxisValues(left: unknown, right: unknown, direction: 'asc' | 'desc') {
  const multiplier = direction === 'asc' ? 1 : -1;
  const leftDate = Date.parse(String(left));
  const rightDate = Date.parse(String(right));
  if (!Number.isNaN(leftDate) && !Number.isNaN(rightDate)) return (leftDate - rightDate) * multiplier;
  const leftNumeric = Number(left);
  const rightNumeric = Number(right);
  if (!Number.isNaN(leftNumeric) && !Number.isNaN(rightNumeric)) return (leftNumeric - rightNumeric) * multiplier;
  return String(left ?? '').localeCompare(String(right ?? '')) * multiplier;
}

function bucketValue(value: unknown, bucket: Exclude<ChartBuilderState['timeBucket'], 'none'>) {
  const date = toDate(value);
  if (!date) return String(value ?? '');
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
  return `${year}`;
}

function quantile(values: number[], percentile: number) {
  if (values.length === 0) return 0;
  const index = (values.length - 1) * percentile;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return values[lower];
  const weight = index - lower;
  return values[lower] * (1 - weight) + values[upper] * weight;
}

function numeric(value: unknown) {
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function isNumericLike(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string' && value.trim()) return Number.isFinite(Number(value));
  return false;
}

function isDateLike(value: unknown) {
  if (value instanceof Date) return true;
  if (typeof value !== 'string') return false;
  return !Number.isNaN(Date.parse(value));
}

function toDate(value: unknown) {
  if (value instanceof Date) return value;
  if (typeof value === 'string' || typeof value === 'number') {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  return null;
}

function getIsoWeek(date: Date) {
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNr = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNr + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const diff = target.getTime() - firstThursday.getTime();
  return 1 + Math.round(diff / 604800000);
}

function pad(value: number) {
  return String(value).padStart(2, '0');
}

function prettifyLabel(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function cryptoSafeId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return Math.random().toString(36).slice(2, 10);
}
