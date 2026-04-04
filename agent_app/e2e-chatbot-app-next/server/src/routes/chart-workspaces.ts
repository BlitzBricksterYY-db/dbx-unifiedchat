import {
  Router,
  type Request,
  type Response,
  type Router as RouterType,
} from 'express';
import { z } from 'zod';

import { authMiddleware, requireAuth } from '../middleware/auth';

export const chartWorkspaceRouter: RouterType = Router();

const chartTypeValues = [
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
] as const;

const chartWorkspaceRequestSchema = z.object({
  workspace: z.object({
    workspaceId: z.string(),
    title: z.string(),
    table: z.object({
      columns: z.array(z.string()),
      rows: z.array(z.record(z.string(), z.unknown())),
    }),
    fields: z
      .array(
        z.object({
          name: z.string(),
          label: z.string().optional(),
          kind: z.enum(['numeric', 'date', 'text']).optional(),
          role: z.string().optional(),
        }),
      )
      .optional(),
    sourceMeta: z
      .object({
        previewLimited: z.boolean().optional(),
      })
      .optional(),
  }),
  existingChart: z.object({
    config: z.object({
      chartType: z.enum(chartTypeValues),
      title: z.string().optional(),
      description: z.string().optional().nullable(),
      xAxisField: z.string().optional().nullable(),
      groupByField: z.string().optional().nullable(),
      zAxisField: z.string().optional().nullable(),
      series: z.array(z.object({ field: z.string(), axis: z.string().optional().nullable() })),
      transform: z.any().optional().nullable(),
      style: z.any().optional().nullable(),
    }),
  }),
  request: z.string().min(1),
  mode: z.enum(['replace', 'add']).default('replace'),
});

chartWorkspaceRouter.use(authMiddleware);

chartWorkspaceRouter.post('/rechart', requireAuth, async (req: Request, res: Response) => {
  const parsed = chartWorkspaceRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({
      error: 'Invalid chart workspace request',
      issues: parsed.error.flatten(),
    });
  }

  const { workspace, existingChart, request, mode } = parsed.data;
  const fields = inferFields(
    workspace.table.columns,
    workspace.table.rows,
    workspace.fields ?? [],
  );
  const currentY = existingChart.config.series.find((series) => series.axis !== 'secondary')?.field
    ?? existingChart.config.series[0]?.field
    ?? fields.numeric[0]?.name
    ?? '';
  const currentSecondary = existingChart.config.series.find((series) => series.axis === 'secondary')?.field
    ?? '';

  const overrides = buildOverridesFromPrompt({
    prompt: request,
    fields,
    defaults: {
      chartType: existingChart.config.chartType,
      title: existingChart.config.title ?? workspace.title,
      description: existingChart.config.description ?? '',
      xAxisField: existingChart.config.xAxisField ?? fields.dimension[0]?.name ?? '',
      yAxisField: currentY,
      secondaryYAxisField: currentSecondary,
      groupByField: existingChart.config.groupByField ?? '',
      zAxisField: existingChart.config.zAxisField ?? '',
      aggregation: inferAggregation(existingChart.config.transform),
      timeBucket: inferTimeBucket(existingChart.config.transform),
      topN: inferTopN(existingChart.config.transform),
      sortDirection: inferSortDirection(existingChart.config.chartType),
      palette: existingChart.config.style?.palette ?? 'default',
      color: existingChart.config.style?.color ?? '',
      showLegend: existingChart.config.style?.showLegend ?? true,
      showLabels: existingChart.config.style?.showLabels ?? false,
      showGridLines: existingChart.config.style?.showGridLines ?? true,
      smoothLines: existingChart.config.style?.smoothLines ?? true,
      xAxisLabelRotation: existingChart.config.style?.xAxisLabelRotation ?? 0,
      yAxisLabelRotation: existingChart.config.style?.yAxisLabelRotation ?? 0,
      showTitle: existingChart.config.style?.showTitle ?? true,
      showDescription: existingChart.config.style?.showDescription ?? true,
    },
  });

  return res.json({
    mode,
    overrides,
    rationale: 'Interpreted the natural-language chart request into structured chart controls.',
    previewLimited: workspace.sourceMeta?.previewLimited ?? false,
  });
});

type FieldInfo = {
  name: string;
  label: string;
  kind: 'numeric' | 'date' | 'text';
  role: string;
};

function inferFields(
  columns: string[],
  rows: Array<Record<string, unknown>>,
  existing: Array<{ name: string; label?: string; kind?: 'numeric' | 'date' | 'text'; role?: string }>,
) {
  const existingMap = new Map(existing.map((field) => [field.name, field]));
  const inferred = columns.map((column) => {
    const existingField = existingMap.get(column);
    if (existingField?.kind) {
      return {
        name: column,
        label: existingField.label ?? prettify(column),
        kind: existingField.kind,
        role: existingField.role ?? 'unknown',
      } satisfies FieldInfo;
    }

    const sample = rows.slice(0, 50).map((row) => row[column]).filter((value) => value != null);
    const lowered = column.toLowerCase();
    let kind: FieldInfo['kind'] = 'text';
    if (sample.length > 0 && sample.every((value) => isNumericLike(value))) {
      kind = 'numeric';
    } else if (sample.length > 0 && sample.every((value) => isDateLike(value))) {
      kind = 'date';
    }
    let role = 'dimension';
    if (kind === 'date') role = 'time';
    else if (kind === 'numeric') role = /amount|cost|paid|count|total|rate|percent|ratio|share/.test(lowered) ? 'measure' : 'measure';
    else if (/_id$|^id$|uuid|identifier/.test(lowered)) role = 'id';
    return {
      name: column,
      label: prettify(column),
      kind,
      role,
    } satisfies FieldInfo;
  });

  return {
    all: inferred,
    numeric: inferred.filter((field) => field.kind === 'numeric' && field.role !== 'id'),
    dimension: inferred.filter((field) => field.kind !== 'numeric' || field.role === 'time'),
    time: inferred.filter((field) => field.kind === 'date' || field.role === 'time'),
  };
}

function buildOverridesFromPrompt({
  prompt,
  fields,
  defaults,
}: {
  prompt: string;
  fields: ReturnType<typeof inferFields>;
  defaults: Record<string, unknown>;
}) {
  const lower = normalize(prompt);
  const chartType = detectChartType(lower) ?? defaults.chartType;
  const xAxisField = matchFieldFromKeywords(lower, ['x axis', 'x-axis', 'x ', 'horizontal axis', 'by'], fields.all)
    ?? (lower.includes('time series') || lower.includes('trend') ? fields.time[0]?.name : null)
    ?? defaults.xAxisField;
  const yAxisField = matchFieldFromKeywords(lower, ['y axis', 'y-axis', 'metric', 'measure', 'value', 'on y'], fields.numeric)
    ?? defaults.yAxisField;
  const secondaryYAxisField = chartType === 'dualAxis'
    ? (
        matchFieldFromKeywords(lower, ['secondary axis', 'second metric', 'secondary y'], fields.numeric, [yAxisField as string])
        ?? defaults.secondaryYAxisField
      )
    : '';
  const groupByField = matchFieldFromKeywords(lower, ['group by', 'breakdown by', 'color by', 'segment by', 'split by'], fields.dimension, [xAxisField as string])
    ?? (chartType === 'stackedBar' || chartType === 'stackedArea' || chartType === 'normalizedStackedBar' ? defaults.groupByField : '');
  const zAxisField = matchFieldFromKeywords(lower, ['size by', 'bubble size', 'z axis', 'z-axis'], fields.numeric, [yAxisField as string, secondaryYAxisField as string])
    ?? '';

  const topN = detectTopN(lower) ?? defaults.topN;
  const palette = detectPalette(lower) ?? defaults.palette;
  const timeBucket = detectTimeBucket(lower) ?? defaults.timeBucket;
  const sortDirection = lower.includes('ascending') || lower.includes('asc')
    ? 'asc'
    : lower.includes('descending') || lower.includes('desc') || lower.includes('top ')
      ? 'desc'
      : defaults.sortDirection;

  const description = buildDescription(prompt, xAxisField as string, yAxisField as string, groupByField as string);

  return {
    ...defaults,
    chartType,
    xAxisField,
    yAxisField,
    secondaryYAxisField,
    groupByField,
    zAxisField,
    topN,
    palette,
    timeBucket,
    sortDirection,
    description,
    mode: defaults.mode ?? 'replace',
  };
}

function matchFieldFromKeywords(
  prompt: string,
  keywords: string[],
  fields: FieldInfo[],
  exclude: string[] = [],
) {
  const excluded = new Set(exclude.filter(Boolean));
  for (const keyword of keywords) {
    const index = prompt.indexOf(keyword);
    if (index === -1) continue;
    const slice = prompt.slice(index, index + 80);
    const direct = fields.find((field) => !excluded.has(field.name) && slice.includes(normalize(field.name)));
    if (direct) return direct.name;
    const byLabel = fields.find((field) => !excluded.has(field.name) && slice.includes(normalize(field.label)));
    if (byLabel) return byLabel.name;
  }

  return fields.find((field) => !excluded.has(field.name) && prompt.includes(normalize(field.name)))?.name
    ?? fields.find((field) => !excluded.has(field.name) && prompt.includes(normalize(field.label)))?.name
    ?? null;
}

function detectChartType(prompt: string) {
  if (prompt.includes('dual axis') || prompt.includes('combo chart')) return 'dualAxis';
  if (prompt.includes('stacked area')) return 'stackedArea';
  if (prompt.includes('100% stacked') || prompt.includes('normalized stacked')) return 'normalizedStackedBar';
  if (prompt.includes('stacked bar')) return 'stackedBar';
  if (prompt.includes('heatmap')) return 'heatmap';
  if (prompt.includes('boxplot') || prompt.includes('box plot')) return 'boxplot';
  if (prompt.includes('scatter')) return 'scatter';
  if (prompt.includes('pie') || prompt.includes('donut')) return 'pie';
  if (prompt.includes('area')) return 'area';
  if (prompt.includes('line') || prompt.includes('trend') || prompt.includes('time series')) return 'line';
  if (prompt.includes('bar') || prompt.includes('column')) return 'bar';
  return null;
}

function detectTimeBucket(prompt: string) {
  if (prompt.includes('daily') || prompt.includes('per day')) return 'day';
  if (prompt.includes('weekly') || prompt.includes('per week')) return 'week';
  if (prompt.includes('monthly') || prompt.includes('per month')) return 'month';
  if (prompt.includes('quarterly') || prompt.includes('per quarter')) return 'quarter';
  if (prompt.includes('yearly') || prompt.includes('annual') || prompt.includes('per year')) return 'year';
  return null;
}

function detectTopN(prompt: string) {
  const match = prompt.match(/\btop\s+(\d+)\b/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

function detectPalette(prompt: string) {
  if (prompt.includes('cool palette') || prompt.includes('blue green')) return 'cool';
  if (prompt.includes('warm palette') || prompt.includes('orange red')) return 'warm';
  if (prompt.includes('neutral palette') || prompt.includes('gray')) return 'neutral';
  return null;
}

function inferAggregation(transform: unknown) {
  const value = String((transform as { function?: string } | null)?.function ?? '').toLowerCase();
  return ['sum', 'avg', 'count', 'min', 'max'].includes(value) ? value : 'sum';
}

function inferTimeBucket(transform: unknown) {
  const value = String((transform as { bucket?: string } | null)?.bucket ?? '').toLowerCase();
  return ['day', 'week', 'month', 'quarter', 'year'].includes(value) ? value : 'none';
}

function inferTopN(transform: unknown) {
  const raw = (transform as { n?: number; topN?: number } | null) ?? {};
  return raw.n ?? raw.topN ?? null;
}

function inferSortDirection(chartType: string) {
  return ['line', 'area', 'stackedArea'].includes(chartType) ? 'asc' : 'desc';
}

function buildDescription(prompt: string, xField: string, yField: string, groupField: string) {
  if (prompt.trim().length <= 140) return prompt.trim();
  const parts = [
    xField ? `X axis ${prettify(xField)}` : '',
    yField ? `Y axis ${prettify(yField)}` : '',
    groupField ? `Breakdown by ${prettify(groupField)}` : '',
  ].filter(Boolean);
  return parts.join(' • ');
}

function normalize(value: string) {
  return value.toLowerCase().replace(/[_\-]+/g, ' ');
}

function prettify(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
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
