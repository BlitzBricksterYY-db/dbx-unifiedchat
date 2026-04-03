import type { EChartsOption } from 'echarts';
import { z } from 'zod';

const chartTypes = [
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

const chartFormatSchema = z.enum(['currency', 'number', 'percent']).optional();
const seriesChartTypeSchema = z.enum(['bar', 'line', 'area']).optional().nullable();
const seriesAxisSchema = z.enum(['primary', 'secondary']).optional().nullable();

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

const seriesSchema = z.object({
  field: z.string().min(1),
  name: z.string().min(1),
  format: chartFormatSchema,
  chartType: seriesChartTypeSchema,
  axis: seriesAxisSchema,
});

const chartConfigSchema = z.object({
  chartType: z.enum(chartTypes),
  title: z.string().optional(),
  xAxisField: z.string().optional().nullable(),
  groupByField: z.string().optional().nullable(),
  yAxisField: z.string().optional().nullable(),
  layout: z.enum(['grouped', 'stacked', 'normalized']).optional().nullable(),
  series: z.array(seriesSchema).min(1).max(3),
  toolbox: z.boolean().optional(),
  supportedChartTypes: z.array(z.enum(chartTypes)).optional(),
  referenceLines: z.array(referenceLineSchema).optional(),
  compareLabels: z.array(z.string()).optional().nullable(),
  transform: transformSchema,
});

export const chartSpecSchema = z.object({
  config: chartConfigSchema,
  chartData: z.array(z.record(z.string(), z.unknown())).max(400),
  downloadData: z.array(z.record(z.string(), z.unknown())).optional(),
  totalRows: z.number().optional(),
  aggregated: z.boolean().optional(),
  aggregationNote: z.string().nullable().optional(),
});

export type ChartSpec = z.infer<typeof chartSpecSchema>;

export function parseChartSpec(raw: unknown): ChartSpec | null {
  const parsed = typeof raw === 'string' ? safeParseJson(raw) : raw;
  if (!parsed) return null;
  const result = chartSpecSchema.safeParse(parsed);
  return result.success ? result.data : null;
}

export function getSelectableChartTypes(spec: ChartSpec): string[] {
  const supported = spec.config.supportedChartTypes?.filter(Boolean);
  return supported && supported.length > 0 ? supported : ['bar', 'line', 'scatter', 'pie'];
}

export function buildOption(spec: ChartSpec, overrideType?: string): EChartsOption {
  const config = spec.config;
  const requestedType = overrideType && chartTypes.includes(overrideType as (typeof chartTypes)[number])
    ? overrideType
    : undefined;
  const type = (requestedType ?? config.chartType) as (typeof chartTypes)[number];

  if (type === 'heatmap') {
    return buildHeatmapOption(spec);
  }
  if (type === 'boxplot') {
    return buildBoxplotOption(spec);
  }
  if (type === 'rankingSlope') {
    return buildRankingSlopeOption(spec);
  }
  if (type === 'deltaComparison') {
    return buildDeltaComparisonOption(spec);
  }
  if (type === 'pie') {
    return buildPieOption(spec);
  }
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
    title: { text: spec.config.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['30%', '65%'],
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
    title: { text: spec.config.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      formatter: (params: any) => {
        const value = Array.isArray(params.value)
          ? params.value[2]
          : 0;
        return `${xValues[params.value[0]]} / ${yValues[params.value[1]]}: ${formatValue(value, spec.config.series[0]?.format)}`;
      },
    },
    grid: { left: '8%', right: '8%', top: '12%', bottom: '18%', containLabel: true },
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
        label: { show: false },
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
    title: { text: spec.config.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const values = Array.isArray((params as { data?: unknown }).data)
          ? ((params as { data: number[] }).data)
          : [0, 0, 0, 0, 0];
        return `${(params as { name?: string }).name ?? ''}<br/>Min: ${values[0]}<br/>Q1: ${values[1]}<br/>Median: ${values[2]}<br/>Q3: ${values[3]}<br/>Max: ${values[4]}`;
      },
    },
    legend: { show: false },
    grid: { left: '6%', right: '4%', top: '12%', bottom: '16%', containLabel: true },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 8 ? 30 : 0 } },
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
    title: { text: spec.config.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, type: 'scroll' },
    grid: { left: '4%', right: '4%', top: '14%', bottom: '18%', containLabel: true },
    xAxis: { type: 'category', data: labels.length === 2 ? labels : ['Start', 'End'] },
    yAxis: {
      type: 'value',
      inverse: true,
      minInterval: 1,
    },
    series: spec.chartData.map((row) => ({
      type: 'line',
      name: String(row[spec.config.xAxisField ?? 'entity'] ?? ''),
      data: [Number(row.startRank ?? 0), Number(row.endRank ?? 0)],
      label: { show: true, formatter: ({ dataIndex }: { dataIndex: number }) => dataIndex === 0 ? String(row[spec.config.xAxisField ?? 'entity'] ?? '') : '' },
      emphasis: { focus: 'series' as const },
    })),
  };
}

function buildDeltaComparisonOption(spec: ChartSpec): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const values = spec.chartData.map((row) => Number(row.delta ?? 0));
  return {
    title: { text: spec.config.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => formatValue(Number(value), spec.config.series[0]?.format),
    },
    grid: { left: '5%', right: '4%', top: '12%', bottom: '18%', containLabel: true },
    xAxis: {
      type: 'category',
      data: spec.chartData.map((row) => String(row[xField] ?? '')),
      axisLabel: { interval: 0, rotate: spec.chartData.length > 8 ? 30 : 0 },
    },
    yAxis: { type: 'value', axisLabel: axisLabelFormatter(spec.config.series[0]?.format) },
    series: [
      {
        type: 'bar',
        data: values,
        itemStyle: {
          color: (params) => Number(params.value) >= 0 ? '#2563eb' : '#dc2626',
        },
      },
    ],
  };
}

function buildCartesianOption(spec: ChartSpec, chartType: string): EChartsOption {
  const xField = spec.config.xAxisField ?? '';
  const xValues = uniqueStrings(spec.chartData.map((row) => String(row[xField] ?? '')));
  const groupedSeries = spec.config.groupByField
    ? buildGroupedSeries(spec, chartType, xValues)
    : buildUngroupedSeries(spec, chartType, xValues);
  const hasSecondaryAxis = groupedSeries.some((series) => series.yAxisIndex === 1);
  const primaryFormat = spec.config.series.find((series) => (series.axis ?? 'primary') !== 'secondary')?.format;
  const secondaryFormat = spec.config.series.find((series) => series.axis === 'secondary')?.format;
  const isPercentScale =
    spec.config.layout === 'normalized' ||
    spec.config.series.some((series) => series.format === 'percent') ||
    spec.config.chartType === 'normalizedStackedBar';

  return {
    title: { text: spec.config.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: chartType.includes('line') || chartType.includes('area') ? 'line' : 'shadow' },
      valueFormatter: (value) => formatValue(Number(value), inferTooltipFormat(spec, Number(value))),
    },
    legend: { bottom: 0, type: 'scroll' },
    grid: { left: '4%', right: hasSecondaryAxis ? '8%' : '4%', bottom: '18%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xValues,
      axisLabel: { rotate: xValues.length > 8 ? 30 : 0, interval: 0 },
    },
    yAxis: buildYAxes(primaryFormat, secondaryFormat, isPercentScale, hasSecondaryAxis),
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
        stack: shouldStack(spec.config.layout, chartType) ? `stack-${seriesSpec.field}` : undefined,
        areaStyle: renderType === 'area' || chartType === 'area' || chartType === 'stackedArea' ? {} : undefined,
        yAxisIndex: seriesSpec.axis === 'secondary' ? 1 : 0,
        markLine: buildMarkLine(spec.config.referenceLines, seriesSpec.axis ?? 'primary'),
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
      stack: shouldStack(spec.config.layout, chartType) ? `stack-${seriesSpec.axis ?? 'primary'}` : undefined,
      areaStyle: renderType === 'area' || chartType === 'area' || chartType === 'stackedArea' ? {} : undefined,
      yAxisIndex: chartType === 'dualAxis' && seriesSpec.axis === 'secondary' ? 1 : 0,
      markLine: buildMarkLine(spec.config.referenceLines, seriesSpec.axis ?? 'primary'),
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
) {
  const axes: EChartsOption['yAxis'] = [
    {
      type: 'value',
      max: isPercentScale ? 100 : undefined,
      axisLabel: axisLabelFormatter(isPercentScale ? 'percent' : primaryFormat),
    },
  ];
  if (hasSecondaryAxis) {
    axes.push({
      type: 'value',
      max: secondaryFormat === 'percent' ? 100 : undefined,
      axisLabel: axisLabelFormatter(secondaryFormat),
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
    label: { formatter: ({ data }: { data?: { name?: string; yAxis?: number } }) => data?.name ?? `${data?.yAxis ?? ''}` },
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
    return { formatter: (value: number) => fmtCurrencyAxis(value) };
  }
  if (format === 'percent') {
    return { formatter: (value: number) => `${Number(value).toFixed(0)}%` };
  }
  return undefined;
}

function formatValue(value: number, format?: ChartSpec['config']['series'][number]['format']) {
  if (format === 'currency') {
    return value.toLocaleString('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    });
  }
  if (format === 'percent') {
    return `${value.toFixed(1)}%`;
  }
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function fmtCurrencyAxis(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value}`;
}

function uniqueStrings(values: string[]) {
  return [...new Set(values)];
}
