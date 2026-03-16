import { useCallback, useMemo, useRef, useState } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import {
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  ToolboxComponent,
  DatasetComponent,
  SVGRenderer,
]);

interface SeriesConfig {
  field: string;
  name: string;
  format?: "currency" | "percent" | "number";
  stack?: string;
}

interface ChartConfig {
  chartType: string;
  title?: string;
  xAxisField?: string;
  groupByField?: string;
  series: SeriesConfig[];
  sortBy?: { field: string; order: string };
  toolbox?: boolean;
}

export interface ChartSpec {
  config: ChartConfig;
  chartData: Record<string, unknown>[];
  downloadData?: Record<string, unknown>[];
  totalRows?: number;
  aggregated?: boolean;
  aggregationNote?: string | null;
}

const CHART_TYPES = ["bar", "line", "scatter", "pie"] as const;

function formatValue(val: unknown, fmt?: string): string {
  if (val == null) return "";
  const n = Number(val);
  if (Number.isNaN(n)) return String(val);
  if (fmt === "currency") return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (fmt === "percent") return `${(n * 100).toFixed(1)}%`;
  return n.toLocaleString("en-US");
}

function formatAxisLabel(val: unknown, fmt?: string): string {
  if (val == null) return "";
  const n = Number(val);
  if (Number.isNaN(n)) return String(val);
  if (fmt === "currency") {
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
    return `$${n.toFixed(0)}`;
  }
  if (fmt === "percent") return `${(n * 100).toFixed(0)}%`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

function buildOption(spec: ChartSpec, overrideType?: string): echarts.EChartsCoreOption {
  const { config, chartData } = spec;
  const type = overrideType ?? config.chartType ?? "bar";
  const xField = config.xAxisField;
  const groupBy = config.groupByField;
  const seriesCfg = config.series ?? [];

  if (type === "pie") {
    const field = seriesCfg[0]?.field;
    const fmt = seriesCfg[0]?.format;
    if (!field || !xField) return {};
    return {
      title: { text: config.title, left: "center", textStyle: { fontSize: 14 } },
      tooltip: {
        trigger: "item",
        formatter: (p: { name: string; value: number; percent: number }) =>
          `${p.name}: ${formatValue(p.value, fmt)} (${p.percent}%)`,
      },
      legend: { bottom: 0, type: "scroll" },
      toolbox: config.toolbox ? { feature: { saveAsImage: {}, restore: {} } } : undefined,
      series: [{
        type: "pie",
        radius: ["30%", "65%"],
        data: chartData.map((row) => ({ name: String(row[xField] ?? ""), value: Number(row[field] ?? 0) })),
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.3)" } },
      }],
    };
  }

  // Cartesian charts: bar, line, scatter
  const xLabels = chartData.map((r) => String(r[xField ?? ""] ?? ""));

  let series: echarts.EChartsCoreOption["series"];

  if (groupBy) {
    const groups = [...new Set(chartData.map((r) => String(r[groupBy] ?? "")))];
    const field = seriesCfg[0]?.field;
    const fmt = seriesCfg[0]?.format;
    if (!field) return {};

    series = groups.map((grp) => ({
      name: grp,
      type,
      stack: seriesCfg[0]?.stack,
      data: chartData.map((r) => (String(r[groupBy] ?? "") === grp ? Number(r[field] ?? 0) : 0)),
      tooltip: { valueFormatter: (v: number) => formatValue(v, fmt) },
    }));
  } else {
    series = seriesCfg.map((s) => ({
      name: s.name,
      type,
      data: chartData.map((r) => Number(r[s.field] ?? 0)),
      tooltip: { valueFormatter: (v: number) => formatValue(v, s.format) },
    }));
  }

  const primaryFmt = seriesCfg[0]?.format;

  return {
    title: { text: config.title, left: "center", textStyle: { fontSize: 14 } },
    tooltip: { trigger: "axis", axisPointer: { type: type === "scatter" ? "cross" : "shadow" } },
    legend: { bottom: 0, type: "scroll" },
    grid: { left: "3%", right: "4%", bottom: "15%", containLabel: true },
    toolbox: config.toolbox
      ? { feature: { magicType: { type: ["line", "bar"] }, restore: {}, saveAsImage: {}, dataView: {} } }
      : undefined,
    xAxis: { type: "category", data: xLabels, axisLabel: { rotate: xLabels.length > 8 ? 30 : 0, interval: 0 } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => formatAxisLabel(v, primaryFmt) } },
    series,
  };
}

function generateCsv(data: Record<string, unknown>[]): string {
  if (!data.length) return "";
  const cols = Object.keys(data[0]);
  const escape = (v: unknown) => {
    const s = String(v ?? "");
    return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = [cols.map(escape).join(",")];
  for (const row of data) {
    rows.push(cols.map((c) => escape(row[c])).join(","));
  }
  return rows.join("\n");
}

export default function InteractiveChart({ spec }: { spec: ChartSpec }) {
  const chartRef = useRef<ReactEChartsCore>(null);
  const originalType = spec.config.chartType ?? "bar";
  const [activeType, setActiveType] = useState(originalType);

  const option = useMemo(() => buildOption(spec, activeType), [spec, activeType]);

  const handleDownloadCsv = useCallback(() => {
    const data = spec.downloadData?.length ? spec.downloadData : spec.chartData;
    const csv = generateCsv(data);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "data.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [spec]);

  const handleReset = useCallback(() => {
    setActiveType(originalType);
    chartRef.current?.getEchartsInstance()?.dispatchAction({ type: "restore" });
  }, [originalType]);

  return (
    <div className="my-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs">
        {CHART_TYPES.map((t) => (
          <button
            type="button"
            key={t}
            onClick={() => setActiveType(t)}
            className={`px-2 py-1 rounded capitalize transition-colors ${
              activeType === t
                ? "bg-blue-600 text-white"
                : "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600"
            }`}
          >
            {t}
          </button>
        ))}
        <button
          type="button"
          onClick={handleReset}
          className="px-2 py-1 rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
        >
          Reset
        </button>
        <div className="flex-1" />
        <button
          type="button"
          onClick={handleDownloadCsv}
          className="px-2 py-1 rounded bg-green-600 text-white hover:bg-green-700 transition-colors"
        >
          Download CSV
        </button>
      </div>

      {/* Chart */}
      <ReactEChartsCore
        ref={chartRef}
        echarts={echarts}
        option={option}
        style={{ height: 400, width: "100%" }}
        opts={{ renderer: "svg" }}
        notMerge
      />

      {/* Aggregation note */}
      {spec.aggregated && spec.aggregationNote && (
        <div className="px-3 py-1.5 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-gray-700">
          {spec.aggregationNote}
          {spec.totalRows && spec.downloadData?.length
            ? ` \u2014 CSV contains ${spec.downloadData.length} of ${spec.totalRows} rows`
            : null}
        </div>
      )}
    </div>
  );
}
