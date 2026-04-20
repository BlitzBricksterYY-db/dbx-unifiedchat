import type { EChartsOption } from 'echarts';
import { z } from 'zod';

export const chartTypes = [
  'bar',
  'line',
  'histogram',
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
const MAX_CHART_DATA_POINTS = 500;
const MAX_NUMERIC_BINS = 100;

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
    chartData: z.array(z.record(z.string(), z.unknown())).max(MAX_CHART_DATA_POINTS),
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
  xAxisBinCount: number | null;
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

export type ChartBuilderUiConfig = {
  xAxisKind: 'dimension' | 'numeric' | 'any';
  showYAxis: boolean;
  yAxisLabel: string;
  showSecondaryYAxis: boolean;
  showGroupBy: boolean;
  groupByLabel: string;
  showZAxis: boolean;
  zAxisLabel: string;
  showAggregation: boolean;
  showTimeBucket: boolean;
  showTopN: boolean;
  showSort: boolean;
  showSmoothLines: boolean;
};

export function getChartBuilderUiConfig(chartType: ChartType): ChartBuilderUiConfig {
  switch (chartType) {
    case 'histogram':
      return {
        xAxisKind: 'numeric',
        showYAxis: true,
        yAxisLabel: 'Value',
        showSecondaryYAxis: false,
        showGroupBy: false,
        groupByLabel: 'Breakdown / Color',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: true,
        showTimeBucket: false,
        showTopN: false,
        showSort: true,
        showSmoothLines: false,
      };
    case 'scatter':
      return {
        xAxisKind: 'numeric',
        showYAxis: true,
        yAxisLabel: 'Y axis',
        showSecondaryYAxis: false,
        showGroupBy: true,
        groupByLabel: 'Color',
        showZAxis: true,
        zAxisLabel: 'Size',
        showAggregation: false,
        showTimeBucket: false,
        showTopN: false,
        showSort: false,
        showSmoothLines: false,
      };
    case 'pie':
      return {
        xAxisKind: 'dimension',
        showYAxis: true,
        yAxisLabel: 'Value',
        showSecondaryYAxis: false,
        showGroupBy: false,
        groupByLabel: 'Breakdown / Color',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: true,
        showTimeBucket: false,
        showTopN: true,
        showSort: true,
        showSmoothLines: false,
      };
    case 'heatmap':
      return {
        xAxisKind: 'dimension',
        showYAxis: true,
        yAxisLabel: 'Cell value',
        showSecondaryYAxis: false,
        showGroupBy: true,
        groupByLabel: 'Y axis',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: true,
        showTimeBucket: false,
        showTopN: false,
        showSort: false,
        showSmoothLines: false,
      };
    case 'boxplot':
      return {
        xAxisKind: 'dimension',
        showYAxis: true,
        yAxisLabel: 'Distribution value',
        showSecondaryYAxis: false,
        showGroupBy: false,
        groupByLabel: 'Breakdown / Color',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: false,
        showTimeBucket: false,
        showTopN: false,
        showSort: false,
        showSmoothLines: false,
      };
    case 'dualAxis':
      return {
        xAxisKind: 'dimension',
        showYAxis: true,
        yAxisLabel: 'Primary Y axis',
        showSecondaryYAxis: true,
        showGroupBy: false,
        groupByLabel: 'Breakdown / Color',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: true,
        showTimeBucket: true,
        showTopN: true,
        showSort: true,
        showSmoothLines: true,
      };
    case 'line':
    case 'area':
    case 'stackedArea':
      return {
        xAxisKind: 'dimension',
        showYAxis: true,
        yAxisLabel: 'Y axis',
        showSecondaryYAxis: false,
        showGroupBy: true,
        groupByLabel: 'Breakdown / Color',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: true,
        showTimeBucket: true,
        showTopN: true,
        showSort: true,
        showSmoothLines: true,
      };
    default:
      return {
        xAxisKind: 'dimension',
        showYAxis: true,
        yAxisLabel: 'Y axis',
        showSecondaryYAxis: false,
        showGroupBy: true,
        groupByLabel: 'Breakdown / Color',
        showZAxis: false,
        zAxisLabel: 'Size',
        showAggregation: true,
        showTimeBucket: true,
        showTopN: true,
        showSort: true,
        showSmoothLines: false,
      };
  }
}

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

export function restoreSavedCharts(raw: unknown, fallback: ChartSpec[]): ChartSpec[] {
  const parsed = typeof raw === 'string' ? safeParseJson(raw) : raw;
  if (!Array.isArray(parsed) || parsed.length === 0) return fallback;
  const restored = parsed
    .map((item) => parseChartSpec(item))
    .filter((item): item is ChartSpec => item !== null);
  return restored.length === parsed.length && restored.length > 0 ? restored : fallback;
}

export function getSelectableChartTypes(spec: ChartSpec): string[] {
  const supported = spec.config.supportedChartTypes?.filter(Boolean) ?? [];
  const types = supported.length > 0 ? [...supported] : ['bar', 'line', 'scatter', 'pie'];
  if (canSelectHistogram(spec) && !types.includes('histogram')) {
    const barIndex = types.indexOf('bar');
    if (barIndex >= 0) types.splice(barIndex + 1, 0, 'histogram');
    else types.unshift('histogram');
  }
  return types;
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
  const defaultX = resolveBuilderXAxisField(chart.config.transform, chart.config.xAxisField, fields);
  const primarySeries = chart.config.series[0];
  const secondarySeries = chart.config.series.find((series) => series.axis === 'secondary');
  return {
    mode,
    title: chart.config.title ?? workspace.title,
    description: chart.config.description ?? '',
    chartType: chart.config.transform?.type === 'histogram' ? 'histogram' : chart.config.chartType,
    xAxisField: defaultX ?? '',
    xAxisBinCount: resolveXAxisBinCount(chart.config.transform, defaultX ?? '', chart.config.chartType),
    yAxisField: primarySeries?.field ?? numericFields[0]?.name ?? '',
    secondaryYAxisField: secondarySeries?.field ?? '',
    groupByField: chart.config.chartType === 'heatmap'
      ? (chart.config.yAxisField ?? chart.config.groupByField ?? '')
      : (chart.config.groupByField ?? ''),
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
  const zField = fieldByName.get(state.zAxisField);
  const numericBinningEnabled = shouldBucketNumeric(state, xField);

  if (
    state.xAxisBinCount !== null
    && (!Number.isInteger(state.xAxisBinCount) || state.xAxisBinCount < 2 || state.xAxisBinCount > MAX_NUMERIC_BINS)
  ) {
    issues.push(`Numeric bins must be an integer between 2 and ${MAX_NUMERIC_BINS}.`);
  }

  if (state.chartType === 'scatter') {
    if (xField?.kind !== 'numeric') issues.push('Scatter charts require a numeric X axis.');
    if (yField?.kind !== 'numeric') issues.push('Scatter charts require a numeric Y axis.');
    if (state.zAxisField && zField?.kind !== 'numeric') issues.push('Scatter bubble size must use a numeric field.');
  }

  if (state.chartType === 'histogram') {
    if (xField?.kind !== 'numeric') issues.push('Histograms require a numeric X axis.');
    if (!numericBinningEnabled) issues.push('Histograms require numeric bins.');
    if (yField?.kind !== 'numeric') issues.push('Histograms require a numeric value field.');
  }

  if (state.chartType === 'heatmap') {
    if (!state.groupByField) issues.push('Heatmaps require a Y-axis/category field.');
    if (yField?.kind !== 'numeric') issues.push('Heatmaps require a numeric cell value field.');
  }

  if (state.chartType === 'rankingSlope' || state.chartType === 'deltaComparison') {
    if (!state.groupByField) issues.push('Ranking and delta comparison charts require a period field.');
  }

  if (state.chartType === 'boxplot') {
    if (xField?.kind === 'numeric' && !numericBinningEnabled) issues.push('Boxplots need a category/time field on the X axis, or numeric bins.');
    if (yField?.kind !== 'numeric') issues.push('Boxplots require a numeric value field.');
  }

  if (state.chartType === 'pie' && groupField) {
    issues.push('Pie charts use a single category field and do not support grouping.');
  }

  if (state.chartType === 'dualAxis' && !state.secondaryYAxisField) {
    issues.push('Dual-axis charts require a secondary Y axis field.');
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

export function normalizeBuilderStateForChartType(
  state: ChartBuilderState,
  fields: ChartField[],
): ChartBuilderState {
  const ui = getChartBuilderUiConfig(state.chartType);
  const numericFields = fields.filter((field) => field.kind === 'numeric' && field.role !== 'id');
  const dimensionFields = fields.filter((field) => field.kind !== 'numeric' || field.role === 'time' || field.role === 'dimension');
  const isNumericField = (name: string) => numericFields.some((field) => field.name === name);
  const isDimensionField = (name: string) => dimensionFields.some((field) => field.name === name);
  const isAllowedDimensionXAxisField = (name: string) => isDimensionField(name) || isNumericField(name);
  const pickDimension = () => dimensionFields[0]?.name ?? pickDefaultXField(fields);
  const pickNumeric = () => numericFields[0]?.name ?? pickDefaultYField(fields);
  const pickAlternateNumeric = (exclude?: string) =>
    numericFields.find((field) => field.name !== exclude)?.name ?? '';
  const pickAlternateDimension = (exclude?: string) =>
    dimensionFields.find((field) => field.name !== exclude)?.name ?? '';

  const next = { ...state };

  if (ui.xAxisKind === 'numeric') {
    if (!isNumericField(next.xAxisField)) next.xAxisField = pickAlternateNumeric(next.yAxisField) || pickNumeric();
  } else if (ui.xAxisKind === 'dimension') {
    if (!isAllowedDimensionXAxisField(next.xAxisField)) next.xAxisField = pickDimension() || next.xAxisField;
  }

  if (ui.showYAxis) {
    if (!isNumericField(next.yAxisField)) next.yAxisField = pickNumeric();
  } else {
    next.yAxisField = '';
  }

  if (!ui.showSecondaryYAxis) {
    next.secondaryYAxisField = '';
  } else if (!isNumericField(next.secondaryYAxisField) || next.secondaryYAxisField === next.yAxisField) {
    next.secondaryYAxisField = pickAlternateNumeric(next.yAxisField);
  }

  if (!ui.showGroupBy) {
    next.groupByField = '';
  } else if (!isDimensionField(next.groupByField) || next.groupByField === next.xAxisField) {
    next.groupByField = pickAlternateDimension(next.xAxisField);
  }

  if (!ui.showZAxis) {
    next.zAxisField = '';
  } else if (!isNumericField(next.zAxisField) || next.zAxisField === next.yAxisField) {
    next.zAxisField = pickAlternateNumeric(next.yAxisField);
  }

  if (!ui.showTimeBucket) next.timeBucket = 'none';
  if (!ui.showTopN) next.topN = null;
  if (!ui.showSort) next.sortDirection = 'asc';
  if (state.chartType === 'histogram') {
    next.xAxisBinCount = Number.isInteger(next.xAxisBinCount) && Number(next.xAxisBinCount) > 1
      ? next.xAxisBinCount
      : 12;
  } else if (ui.xAxisKind === 'numeric' || !isNumericField(next.xAxisField)) {
    next.xAxisBinCount = null;
  }

  return next;
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
  const numericBinCount = resolveNumericBinCount(builder, xMeta);
  const effectiveNumericBinCount = numericBinCount && createNumericBinner(rows, xField, numericBinCount) ? numericBinCount : null;
  const existingConfig = (existing?.config ?? {}) as Record<string, unknown>;
  const existingMeta = (existing?.meta ?? {}) as Record<string, unknown>;

  let chartData: Record<string, unknown>[] = [];
  let aggregated = false;
  let aggregationNote: string | null = null;
  let transform: Record<string, unknown> | null = null;
  let compareLabels: string[] | null = existing?.config.compareLabels ?? null;
  let layout: ChartSpec['config']['layout'] = normalizeLayoutFromBuilder(builder);
  const existingSortBy = ((existing?.config as { sortBy?: { field?: string; order?: 'asc' | 'desc' } } | undefined)?.sortBy) ?? null;

  if (chartType === 'rankingSlope' || chartType === 'deltaComparison') {
    const comparisonTopN = typeof builder.topN === 'number' && builder.topN > 0 ? builder.topN : null;
    const comparison = buildPeriodComparisonChartData(
      rows,
      xField,
      groupField,
      yField,
      builder.aggregation,
      chartType,
      comparisonTopN,
      existingSortBy,
    );
    chartData = comparison.chartData;
    aggregated = true;
    aggregationNote = comparison.aggregationNote;
    compareLabels = comparison.compareLabels;
    transform = {
      type: chartType,
      entityField: xField,
      periodField: groupField,
      ...(yField && yField !== 'count' ? { metric: yField } : {}),
      function: builder.aggregation,
      ...(comparisonTopN ? { topN: comparisonTopN } : {}),
      compareLabels: comparison.compareLabels,
    };
  } else if (chartType === 'scatter') {
    chartData = buildScatterChartData(rows, xField, yField, groupField, zField);
  } else if (chartType === 'histogram') {
    chartData = buildAggregatedChartData(rows, xField, yField, '', builder, '', 'none', effectiveNumericBinCount);
    aggregated = true;
    aggregationNote = `Bucketed ${prettifyLabel(xField)} into ${effectiveNumericBinCount ?? numericBinCount ?? 12} bins and aggregated ${prettifyLabel(yField)}`;
    transform = { type: 'histogram', field: xField, bins: effectiveNumericBinCount ?? numericBinCount ?? 12, metric: yField, function: builder.aggregation };
  } else if (chartType === 'heatmap') {
    chartData = buildHeatmapChartData(rows, xField, groupField, yField, builder.aggregation, effectiveNumericBinCount);
    aggregated = true;
    aggregationNote = effectiveNumericBinCount
      ? `Bucketed ${prettifyLabel(xField)} into ${effectiveNumericBinCount} bins and aggregated ${prettifyLabel(yField)} by ${prettifyLabel(groupField)}`
      : `Aggregated ${prettifyLabel(yField)} by ${prettifyLabel(xField)} and ${prettifyLabel(groupField)}`;
    transform = effectiveNumericBinCount
      ? { type: 'histogram', field: xField, bins: effectiveNumericBinCount, metric: yField, function: builder.aggregation }
      : { type: 'heatmap', xField, yField: groupField, metric: yField, function: builder.aggregation };
  } else if (chartType === 'boxplot') {
    chartData = buildBoxplotChartData(rows, xField, yField, effectiveNumericBinCount);
    aggregated = true;
    aggregationNote = effectiveNumericBinCount
      ? `Bucketed ${prettifyLabel(xField)} into ${effectiveNumericBinCount} bins for boxplot statistics`
      : `Summarized ${prettifyLabel(yField)} into boxplot statistics`;
    transform = effectiveNumericBinCount
      ? { type: 'histogram', field: xField, bins: effectiveNumericBinCount, metric: yField, function: builder.aggregation }
      : { type: 'boxplot', field: yField };
  } else if (chartType === 'pie') {
    const pieTopN = typeof builder.topN === 'number' && builder.topN > 0
      ? Math.min(builder.topN, 6)
      : 6;
    chartData = buildAggregatedChartData(rows, xField, yField, '', builder, '', 'none', effectiveNumericBinCount);
    chartData = applyTopN(chartData, xField, yField, pieTopN);
    aggregated = true;
    aggregationNote = effectiveNumericBinCount
      ? `Bucketed ${prettifyLabel(xField)} into ${effectiveNumericBinCount} bins and aggregated ${prettifyLabel(yField)}`
      : `Aggregated ${prettifyLabel(yField)} by ${prettifyLabel(xField)}`;
    aggregationNote = `${aggregationNote} • Top ${pieTopN} categories`;
    transform = effectiveNumericBinCount
      ? { type: 'histogram', field: xField, bins: effectiveNumericBinCount, metric: yField, function: builder.aggregation, topN: pieTopN }
      : { type: 'topN', metric: yField, n: pieTopN };
  } else {
    const bucket = shouldBucketTime(builder, xMeta) ? builder.timeBucket : 'none';
    const shouldNormalizeGrouped = Boolean(groupField && layout === 'normalized');
    chartData = buildAggregatedChartData(rows, xField, yField, groupField, builder, secondaryField, bucket, effectiveNumericBinCount);
    aggregated = chartData.length > 0;
    if (bucket !== 'none') {
      aggregationNote = `Bucketed ${prettifyLabel(yField)} by ${bucket}`;
      transform = { type: 'timeBucket', field: xField, bucket, metric: yField, function: builder.aggregation };
    } else if (effectiveNumericBinCount) {
      aggregationNote = `Bucketed ${prettifyLabel(xField)} into ${effectiveNumericBinCount} bins and aggregated ${prettifyLabel(yField)}`;
      transform = { type: 'histogram', field: xField, bins: effectiveNumericBinCount, metric: yField, function: builder.aggregation };
    } else {
      aggregationNote = `Aggregated ${prettifyLabel(yField)} by ${prettifyLabel(xField)}`;
    }
    if (builder.topN && (xMeta?.kind !== 'numeric' || Boolean(effectiveNumericBinCount)) && chartData.length > builder.topN) {
      chartData = applyTopN(chartData, xField, yField, builder.topN, groupField, secondaryField || undefined);
      aggregationNote = `${aggregationNote} • Top ${builder.topN} categories`;
      transform = transform
        ? { ...transform, topN: builder.topN }
        : { type: 'topN', metric: yField, n: builder.topN };
    }
    if (shouldNormalizeGrouped) {
      chartData = normalizeGroupedPercent(chartData, xField, groupField, [yField, secondaryField].filter(Boolean));
      aggregationNote = `Converted grouped values to percent-of-total within each ${prettifyLabel(xField)}${builder.topN ? ` • Top ${builder.topN} categories` : ''}`;
    }
  }

  const description = builder.description.trim()
    || [
      builder.groupByField ? `Break down by ${prettifyLabel(builder.groupByField)}` : '',
      workspace.sourceMeta?.previewLimited ? 'Preview-limited rows' : '',
    ]
      .filter(Boolean)
      .join(' • ');

  const supportedChartTypes = getSupportedTypesFromBuilder(builder, xMeta?.kind, effectiveNumericBinCount);

  return {
    config: {
      ...existingConfig,
      chartType,
      title: builder.title.trim() || workspace.title,
      description: description || undefined,
      xAxisField: xField,
      yAxisField: chartType === 'heatmap' ? (groupField || null) : null,
      zAxisField: zField || null,
      groupByField: groupField || null,
      layout,
      series,
      toolbox: true,
      supportedChartTypes,
      referenceLines: existing?.config.referenceLines ?? [],
      compareLabels,
      sortBy: existingConfig.sortBy ?? null,
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
    chartData: chartData.slice(0, MAX_CHART_DATA_POINTS),
    downloadData: workspace.table.rows,
    totalRows: workspace.table.totalRows ?? workspace.table.rows.length,
    aggregated,
    aggregationNote,
    meta: {
      ...existingMeta,
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

  if (type === 'histogram') return buildCartesianOption(spec, 'bar');
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
  const numericValues = values.map((item) => Number(item[2])).filter((value) => Number.isFinite(value));
  const rawMin = numericValues.length > 0 ? Math.min(...numericValues) : 0;
  const rawMax = numericValues.length > 0 ? Math.max(...numericValues) : 0;
  const visualMin = rawMin < 0 ? rawMin : 0;
  const visualMax = rawMax > 0 ? rawMax : 0;

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      formatter: (params: any) => {
        const [xIndex, yIndex, cellValue] = Array.isArray(params.value) ? params.value : [-1, -1, 0];
        const xLabel = xValues[Number(xIndex)] ?? '';
        const yLabel = yValues[Number(yIndex)] ?? '';
        return `${xLabel} / ${yLabel}: ${formatValue(Number(cellValue ?? 0), spec.config.series[0]?.format)}`;
      },
    },
    grid: { left: '8%', right: '8%', top: titleTop(spec), bottom: '18%', containLabel: true },
    xAxis: { type: 'category', data: xValues, splitArea: { show: true } },
    yAxis: { type: 'category', data: yValues, splitArea: { show: true } },
    visualMap: {
      min: visualMin,
      max: visualMax,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
    },
    series: [
      {
        type: 'heatmap',
        data: spec.chartData.map((row) => ({
          value: [
            xValues.indexOf(String(row[xField] ?? '')),
            yValues.indexOf(String(row[yField] ?? '')),
            Number(row[valueField] ?? 0),
          ],
          name: `${String(row[xField] ?? '')} / ${String(row[yField] ?? '')}`,
          xValue: String(row[xField] ?? ''),
          groupValue: String(row[yField] ?? ''),
        })),
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
  const requestedGroups = groupField
    ? uniqueStrings(spec.chartData.map((row) => String(row[groupField] ?? ''))).filter(Boolean)
    : [];
  const groups = requestedGroups.length > 0 ? requestedGroups : ['All rows'];

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        const point = Array.isArray(params.value) ? params.value : [];
        return [
          escapeHtml(String(params.seriesName ?? '')),
          `${escapeHtml(prettifyLabel(xField))}: ${formatValue(Number(point[0] ?? 0), 'number')}`,
          `${escapeHtml(prettifyLabel(yField))}: ${formatValue(Number(point[1] ?? 0), spec.config.series[0]?.format)}`,
          sizeField ? `${escapeHtml(prettifyLabel(sizeField))}: ${formatValue(Number(point[2] ?? 0), 'number')}` : '',
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
      const groupRows = requestedGroups.length > 0 && groupField
        ? spec.chartData.filter((row) => String(row[groupField] ?? '') === group)
        : spec.chartData;
      const sizeValues = groupRows
        .map((row) => Number(row[sizeField] ?? 0))
        .filter((value) => Number.isFinite(value));
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
        data: groupRows.map((row) => ({
          value: sizeField
            ? [
                Number(row[xField] ?? 0),
                Number(row[yField] ?? 0),
                Number.isFinite(Number(row[sizeField] ?? 0)) ? Number(row[sizeField] ?? 0) : 0,
              ]
            : [
                Number(row[xField] ?? 0),
                Number(row[yField] ?? 0),
              ],
          name: String(row[xField] ?? ''),
          xValue: String(row[xField] ?? ''),
          yValue: String(row[yField] ?? ''),
          ...(sizeField ? { zValue: String(row[sizeField] ?? '') } : {}),
          ...(groupField ? { groupValue: String(row[groupField] ?? '') } : {}),
        })),
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
  const primaryIsPercent =
    spec.config.layout === 'normalized' ||
    spec.config.chartType === 'normalizedStackedBar' ||
    primaryFormat === 'percent';
  const secondaryIsPercent = secondaryFormat === 'percent';

  return {
    color: resolvePalette(spec),
    title: buildTitleConfig(spec),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: chartType.includes('line') || chartType.includes('area') ? 'line' : 'shadow' },
      formatter: (params) => formatCartesianTooltip(spec, params),
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
      primaryIsPercent,
      secondaryIsPercent,
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
  primaryIsPercent: boolean,
  secondaryIsPercent: boolean,
  hasSecondaryAxis: boolean,
  showGridLines: boolean,
  primaryName?: string,
  secondaryName?: string,
) {
  const axes: EChartsOption['yAxis'] = [
    {
      type: 'value',
      max: primaryIsPercent ? 100 : undefined,
      name: primaryName,
      nameLocation: 'middle',
      nameGap: 56,
      nameRotate: 90,
      nameTextStyle: primaryName ? axisNameTextStyle() : undefined,
      axisLabel: axisLabelFormatter(primaryIsPercent ? 'percent' : primaryFormat),
      axisLine: primaryName ? axisLineStyle() : undefined,
      axisTick: primaryName ? axisTickStyle() : undefined,
      splitLine: { show: showGridLines },
    },
  ];
  if (hasSecondaryAxis) {
    axes.push({
      type: 'value',
      max: secondaryIsPercent ? 100 : undefined,
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

function formatCartesianTooltip(spec: ChartSpec, rawParams: unknown) {
  const params = Array.isArray(rawParams) ? rawParams : [rawParams];
  const validParams = params.filter((item): item is {
    seriesName?: string;
    marker?: string;
    axisValueLabel?: string;
    name?: string;
    value?: unknown;
    data?: unknown;
  } => Boolean(item && typeof item === 'object'));

  if (validParams.length === 0) return '';

  const axisLabel = String(validParams[0].axisValueLabel ?? validParams[0].name ?? '');
  const groups = new Map<string, Array<{ label: string; value: number; marker: string; format?: ChartSpec['config']['series'][number]['format'] }>>();

  for (const item of validParams) {
    const seriesName = String(item.seriesName ?? '');
    const match = /^(.*) \((.*)\)$/.exec(seriesName);
    const metricLabel = match?.[1] ?? seriesName;
    const seriesLabel = match?.[2] ?? metricLabel;
    const format = spec.config.series.find((series) => series.name === metricLabel)?.format ?? inferTooltipFormat(spec, Number(item.value ?? item.data ?? 0));
    const value = tooltipNumber(item.value ?? item.data);
    if (!Number.isFinite(value)) continue;
    const existing = groups.get(metricLabel) ?? [];
    existing.push({
      label: seriesLabel,
      value,
      marker: String(item.marker ?? ''),
      format,
    });
    groups.set(metricLabel, existing);
  }

  const lines = [`<strong>${escapeHtml(axisLabel)}</strong>`];
  for (const [metricLabel, entries] of groups.entries()) {
    const sorted = entries.sort((left, right) => Math.abs(right.value) - Math.abs(left.value));
    const displayed = sorted.slice(0, 6);
    lines.push(`<br/><span style="opacity:.8">${escapeHtml(metricLabel)}</span>`);
    for (const entry of displayed) {
      lines.push(`<br/>${entry.marker}${escapeHtml(entry.label)}: ${formatValue(entry.value, entry.format)}`);
    }
    if (sorted.length > displayed.length) {
      lines.push(`<br/>... and ${sorted.length - displayed.length} more`);
    }
  }

  return lines.length > 1 ? lines.join('') : `<strong>${escapeHtml(axisLabel)}</strong>`;
}

function tooltipNumber(value: unknown) {
  if (Array.isArray(value)) return Number(value[value.length - 1] ?? 0);
  return Number(value ?? 0);
}

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
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
): ChartSpec['config']['series'] {
  const primary = fieldByName.get(yField);
  const secondary = fieldByName.get(secondaryField);
  const series: ChartSpec['config']['series'] = [];
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
  if (!series.length && (builder.chartType === 'rankingSlope' || builder.chartType === 'deltaComparison')) {
    return [{ field: 'count', name: 'Count', format: 'number', chartType: null, axis: 'primary' as const }];
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
  numericBinCount: number | null = null,
) {
  const numericBinner = numericBinCount ? createNumericBinner(rows, xField, numericBinCount) : null;
  const groups = new Map<string, { xValue: string; groupValue: string; yValues: number[]; secondaryValues: number[]; sortValue: unknown }>();
  for (const row of rows) {
    const rawX = row[xField];
    const xAxisValue = numericBinner
      ? numericBinner(rawX)
      : { label: bucket !== 'none' ? bucketValue(rawX, bucket) : String(rawX ?? ''), sortValue: rawX };
    const groupedValue = groupField ? String(row[groupField] ?? '') : '';
    const key = `${xAxisValue.label}:::${groupedValue}`;
    if (!groups.has(key)) {
      groups.set(key, { xValue: xAxisValue.label, groupValue: groupedValue, yValues: [], secondaryValues: [], sortValue: xAxisValue.sortValue });
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
    __sortValue: entry.sortValue,
  }));

  chartData.sort((left, right) => compareAxisValues(left.__sortValue, right.__sortValue, builder.sortDirection));
  return chartData.map(({ __sortValue, ...row }) => row);
}

function buildHeatmapChartData(
  rows: Array<Record<string, unknown>>,
  xField: string,
  groupField: string,
  yField: string,
  aggregation: ChartBuilderState['aggregation'],
  numericBinCount: number | null = null,
) {
  const numericBinner = numericBinCount ? createNumericBinner(rows, xField, numericBinCount) : null;
  const grouped = new Map<string, { xValue: string; groupValue: string; values: number[]; sortValue: unknown }>();
  for (const row of rows) {
    const xAxisValue = numericBinner
      ? numericBinner(row[xField])
      : { label: String(row[xField] ?? ''), sortValue: row[xField] };
    const groupValue = String(row[groupField] ?? '');
    const key = `${xAxisValue.label}:::${groupValue}`;
    if (!grouped.has(key)) grouped.set(key, { xValue: xAxisValue.label, groupValue, values: [], sortValue: xAxisValue.sortValue });
    grouped.get(key)?.values.push(numeric(row[yField]));
  }
  return Array.from(grouped.values())
    .sort((left, right) => compareAxisValues(left.sortValue, right.sortValue, 'asc'))
    .map((entry) => ({
      [xField]: entry.xValue,
      [groupField]: entry.groupValue,
      [yField]: aggregate(entry.values, aggregation),
    }));
}

function buildPeriodComparisonChartData(
  rows: Array<Record<string, unknown>>,
  entityField: string,
  periodField: string,
  metricField: string,
  aggregation: ChartBuilderState['aggregation'],
  chartType: 'rankingSlope' | 'deltaComparison',
  topN: number | null,
  sortBy?: { field?: string; order?: 'asc' | 'desc' } | null,
): { chartData: Record<string, unknown>[]; compareLabels: string[] | null; aggregationNote: string } {
  const orderedPeriods = uniqueStrings(rows.map((row) => String(row[periodField] ?? '')).filter(Boolean)).sort(comparePeriodValues);
  if (orderedPeriods.length < 2) {
    return {
      chartData: [],
      compareLabels: null,
      aggregationNote: `${chartType} skipped because fewer than two periods were available`,
    };
  }

  const compareLabels = orderedPeriods.slice(-2);
  const [startLabel, endLabel] = compareLabels;
  const grouped = new Map<string, Map<string, number[]>>();
  for (const row of rows) {
    const entity = String(row[entityField] ?? '');
    const period = String(row[periodField] ?? '');
    if (!entity || !period) continue;
    if (!grouped.has(entity)) grouped.set(entity, new Map());
    const byPeriod = grouped.get(entity)!;
    if (!byPeriod.has(period)) byPeriod.set(period, []);
    byPeriod.get(period)!.push(metricField && metricField !== 'count' ? numeric(row[metricField]) : 1);
  }

  const comparisonRows: Array<Record<string, unknown>> = [];
  let excludedEntities = 0;
  for (const [entity, byPeriod] of grouped.entries()) {
    const startValues = byPeriod.get(startLabel);
    const endValues = byPeriod.get(endLabel);
    if (!startValues?.length || !endValues?.length) {
      excludedEntities += 1;
      continue;
    }
    const method = metricField && metricField !== 'count' ? aggregation : 'count';
    const startValue = aggregate(startValues, method);
    const endValue = aggregate(endValues, method);
    comparisonRows.push({
      [entityField]: entity,
      startLabel,
      endLabel,
      startValue,
      endValue,
      delta: endValue - startValue,
    });
  }

  if (comparisonRows.length === 0) {
    return {
      chartData: [],
      compareLabels,
      aggregationNote: `${chartType} skipped because no entities had data in both ${startLabel} and ${endLabel}`,
    };
  }

  if (chartType === 'rankingSlope') {
    const startRanks = rankPeriodComparisonRows(comparisonRows, entityField, 'startValue');
    const endRanks = rankPeriodComparisonRows(comparisonRows, entityField, 'endValue');
    for (const row of comparisonRows) {
      row.startRank = startRanks.get(String(row[entityField] ?? '')) ?? 0;
      row.endRank = endRanks.get(String(row[entityField] ?? '')) ?? 0;
    }
  }

  const rankedRows = sortPeriodComparisonRows(comparisonRows, chartType, entityField, sortBy);
  const trimmedRows = topN && topN > 0 ? rankedRows.slice(0, topN) : rankedRows;
  const baseNote = chartType === 'rankingSlope'
    ? `Compared ${comparisonRows.length} entities across ${startLabel} and ${endLabel} with rank alignment`
    : `Computed deltas for ${comparisonRows.length} entities across ${startLabel} and ${endLabel}`;
  const topNNote = topN && topN > 0 && trimmedRows.length < comparisonRows.length
    ? `; showing top ${trimmedRows.length}`
    : '';
  return {
    chartData: trimmedRows,
    compareLabels,
    aggregationNote: excludedEntities > 0
      ? `${baseNote}${topNNote}; excluded ${excludedEntities} entities without both periods`
      : `${baseNote}${topNNote}`,
  };
}

function buildBoxplotChartData(
  rows: Array<Record<string, unknown>>,
  xField: string,
  yField: string,
  numericBinCount: number | null = null,
) {
  const numericBinner = numericBinCount ? createNumericBinner(rows, xField, numericBinCount) : null;
  const grouped = new Map<string, { values: number[]; sortValue: unknown }>();
  for (const row of rows) {
    const xAxisValue = numericBinner
      ? numericBinner(row[xField])
      : { label: String(row[xField] ?? ''), sortValue: row[xField] };
    if (!grouped.has(xAxisValue.label)) grouped.set(xAxisValue.label, { values: [], sortValue: xAxisValue.sortValue });
    grouped.get(xAxisValue.label)?.values.push(numeric(row[yField]));
  }
  return Array.from(grouped.entries())
    .sort((left, right) => compareAxisValues(left[1].sortValue, right[1].sortValue, 'asc'))
    .map(([label, entry]) => {
      const sorted = entry.values.filter((value) => !Number.isNaN(value)).sort((a, b) => a - b);
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
  const distinctXCount = groupField
    ? new Set(rows.map((row) => String(row[xField] ?? ''))).size
    : rows.length;
  if (distinctXCount <= limit) return rows;
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

  const rowsByX = new Map<string, Array<Record<string, unknown>>>();
  const totalsByX = new Map<string, number>();
  for (const row of rows) {
    const xValue = String(row[xField] ?? '');
    if (!rowsByX.has(xValue)) rowsByX.set(xValue, []);
    rowsByX.get(xValue)!.push(row);
    totalsByX.set(xValue, (totalsByX.get(xValue) ?? 0) + numeric(row[yField]));
  }

  const topXValues = Array.from(totalsByX.entries())
    .sort((left, right) => right[1] - left[1])
    .slice(0, limit)
    .map(([xValue]) => xValue);
  const topXSet = new Set(topXValues);
  const topGroupedRows = topXValues.flatMap((xValue) => rowsByX.get(xValue) ?? []);
  const restGroupedRows = rows.filter((row) => !topXSet.has(String(row[xField] ?? '')));
  const otherByGroup = new Map<string, Record<string, unknown>>();
  for (const row of restGroupedRows) {
    const group = String(row[groupField] ?? '');
    if (!otherByGroup.has(group)) {
      otherByGroup.set(group, { [xField]: 'Other', [groupField]: group, [yField]: 0, ...(secondaryField ? { [secondaryField]: 0 } : {}) });
    }
    const current = otherByGroup.get(group)!;
    current[yField] = numeric(current[yField]) + numeric(row[yField]);
    if (secondaryField) current[secondaryField] = numeric(current[secondaryField]) + numeric(row[secondaryField]);
  }
  return [...topGroupedRows, ...Array.from(otherByGroup.values())];
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
  numericBinCount?: number | null,
): ChartType[] {
  if (builder.chartType === 'heatmap' || builder.chartType === 'boxplot' || builder.chartType === 'rankingSlope' || builder.chartType === 'deltaComparison') {
    return [builder.chartType];
  }
  if (builder.chartType === 'histogram') return ['histogram', 'bar', 'line'];
  if (builder.chartType === 'dualAxis' || builder.secondaryYAxisField) return ['dualAxis', 'bar', 'line'];
  if (numericBinCount && builder.chartType !== 'scatter') return ['histogram', 'bar', 'line'];
  if (builder.chartType === 'normalizedStackedBar') return ['normalizedStackedBar', 'stackedBar', 'bar'];
  if (builder.chartType === 'stackedArea') return ['stackedArea', 'area', 'line'];
  if (builder.chartType === 'stackedBar') return ['stackedBar', 'bar', 'line'];
  if (builder.groupByField) return ['bar', 'line', 'area', 'stackedBar', 'normalizedStackedBar'];
  if (xKind === 'date') return ['line', 'area', 'stackedArea', 'bar'];
  return ['bar', 'line', 'scatter', 'pie', 'heatmap', 'boxplot'];
}

function shouldBucketTime(builder: ChartBuilderState, field?: ChartField) {
  return field?.kind === 'date' && builder.timeBucket !== 'none';
}

function resolveXAxisBinCount(
  transform: ChartSpec['config']['transform'],
  xField: string,
  chartType?: ChartType,
) {
  if (chartType === 'scatter') return null;
  if (transform?.type !== 'histogram') return null;
  const bins = Number(transform?.bins ?? 0);
  return Number.isInteger(bins) && bins > 1 ? bins : null;
}

function resolveBuilderXAxisField(
  transform: ChartSpec['config']['transform'],
  xAxisField: string | null | undefined,
  fields: ChartField[],
) {
  if (transform?.type === 'histogram' && typeof transform.field === 'string' && transform.field) {
    return transform.field;
  }
  return xAxisField ?? pickDefaultXField(fields);
}

function canSelectHistogram(spec: ChartSpec): boolean {
  const chartType = spec.config.chartType;
  if (['scatter', 'pie', 'heatmap', 'boxplot', 'dualAxis', 'rankingSlope', 'deltaComparison'].includes(chartType)) return false;
  if (spec.config.groupByField) return false;
  const xField = spec.config.transform?.type === 'histogram'
    ? String(spec.config.transform.field ?? '')
    : String(spec.config.xAxisField ?? '');
  if (!xField) return false;
  const rows = spec.downloadData ?? spec.chartData;
  return rows.some((row) => Number.isFinite(Number(row[xField] ?? NaN)));
}

function resolveNumericBinCount(builder: ChartBuilderState, field?: ChartField) {
  return shouldBucketNumeric(builder, field) ? builder.xAxisBinCount : null;
}

function shouldBucketNumeric(builder: ChartBuilderState, field?: ChartField) {
  return field?.kind === 'numeric'
    && builder.chartType !== 'scatter'
    && Number.isInteger(builder.xAxisBinCount)
    && Number(builder.xAxisBinCount) > 1;
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

function comparePeriodValues(left: unknown, right: unknown) {
  return comparePeriodSortKeys(toPeriodSortKey(left), toPeriodSortKey(right));
}

function toPeriodSortKey(value: unknown): Array<number | string> {
  if (isDateLike(value)) {
    const date = toDate(value);
    if (date) return [0, date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate()];
  }

  if (typeof value === 'string') {
    const trimmed = value.trim();
    let match = trimmed.match(/^(\d{4})[-/](\d{1,2})$/);
    if (match) return [1, Number(match[1]), Number(match[2])];
    match = trimmed.match(/^(\d{4})[-/]Q([1-4])$/i);
    if (match) return [2, Number(match[1]), Number(match[2])];
    match = trimmed.match(/^(\d{4})[-/]W(\d{1,2})$/i);
    if (match) return [3, Number(match[1]), Number(match[2])];
  }

  if (isNumericLike(value)) return [4, numeric(value)];
  return [5, String(value ?? '')];
}

function comparePeriodSortKeys(left: Array<number | string>, right: Array<number | string>) {
  const maxLength = Math.max(left.length, right.length);
  for (let index = 0; index < maxLength; index += 1) {
    const leftValue = left[index];
    const rightValue = right[index];
    if (leftValue === rightValue) continue;
    if (typeof leftValue === 'number' && typeof rightValue === 'number') return leftValue - rightValue;
    return String(leftValue ?? '').localeCompare(String(rightValue ?? ''));
  }
  return 0;
}

function rankPeriodComparisonRows(
  rows: Array<Record<string, unknown>>,
  entityField: string,
  valueField: 'startValue' | 'endValue',
) {
  const sortedRows = [...rows].sort((left, right) => numeric(right[valueField]) - numeric(left[valueField]));
  const ranks = new Map<string, number>();
  let currentRank = 0;
  let previousValue: number | null = null;
  sortedRows.forEach((row, index) => {
    const value = numeric(row[valueField]);
    if (previousValue === null || Math.abs(value - previousValue) > Number.EPSILON) {
      currentRank = index + 1;
      previousValue = value;
    }
    ranks.set(String(row[entityField] ?? ''), currentRank);
  });
  return ranks;
}

function sortPeriodComparisonRows(
  rows: Array<Record<string, unknown>>,
  chartType: 'rankingSlope' | 'deltaComparison',
  entityField: string,
  sortBy?: { field?: string; order?: 'asc' | 'desc' } | null,
) {
  if (sortBy?.field) {
    const direction = sortBy.order === 'asc' ? 'asc' : 'desc';
    const field = sortBy.field;
    if (rows.every((row) => field in row)) {
      return [...rows].sort((left, right) => compareAxisValues(left[field], right[field], direction));
    }
    if (field === entityField) {
      return [...rows].sort((left, right) => compareAxisValues(left[entityField], right[entityField], direction));
    }
  }

  if (chartType === 'rankingSlope') {
    return [...rows].sort(
      (left, right) => Math.min(numeric(left.startRank), numeric(left.endRank)) - Math.min(numeric(right.startRank), numeric(right.endRank)),
    );
  }

  return [...rows].sort((left, right) => Math.abs(numeric(right.delta)) - Math.abs(numeric(left.delta)));
}

function createNumericBinner(
  rows: Array<Record<string, unknown>>,
  field: string,
  requestedBins: number,
) {
  const values = rows
    .map((row) => Number(row[field]))
    .filter((value) => Number.isFinite(value));
  if (values.length === 0) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const distinctCount = new Set(values.map((value) => String(value))).size;
  const effectiveBins = Math.max(2, Math.min(requestedBins, distinctCount || requestedBins));
  const useDecimals = values.some((value) => !Number.isInteger(value)) || (max - min) / effectiveBins < 1;

  if (min === max) {
    const label = formatNumericBinLabel(min, max, useDecimals);
    return (value: unknown) => ({ label, sortValue: Number(value ?? min) });
  }

  const width = (max - min) / effectiveBins;
  return (value: unknown) => {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) {
      return { label: String(value ?? ''), sortValue: Number.POSITIVE_INFINITY };
    }
    const index = numericValue === max
      ? effectiveBins - 1
      : Math.max(0, Math.min(effectiveBins - 1, Math.floor((numericValue - min) / width)));
    const start = min + (index * width);
    const end = index === effectiveBins - 1 ? max : min + ((index + 1) * width);
    return {
      label: formatNumericBinLabel(start, end, useDecimals),
      sortValue: start,
    };
  };
}

function formatNumericBinLabel(start: number, end: number, useDecimals: boolean) {
  if (Math.abs(start - end) < Number.EPSILON) return formatNumericBinNumber(start, useDecimals);
  return `${formatNumericBinNumber(start, useDecimals)}-${formatNumericBinNumber(end, useDecimals)}`;
}

function formatNumericBinNumber(value: number, useDecimals: boolean) {
  return useDecimals ? value.toFixed(1) : value.toFixed(0);
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
