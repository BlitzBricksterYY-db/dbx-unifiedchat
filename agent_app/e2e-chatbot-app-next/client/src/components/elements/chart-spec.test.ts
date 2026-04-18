import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildOption,
  createBuilderStateFromChart,
  getChartBuilderUiConfig,
  getSelectableChartTypes,
  materializeChartSpecFromBuilder,
  normalizeBuilderStateForChartType,
  parseChartSpec,
  parseChartWorkspace,
  validateBuilderState,
} from './chart-spec';

test('parseChartSpec accepts normalized stacked bar specs', () => {
  const spec = parseChartSpec(
    JSON.stringify({
      config: {
        chartType: 'normalizedStackedBar',
        title: 'Coverage Mix',
        xAxisField: 'benefit_type',
        groupByField: 'pay_type',
        layout: 'normalized',
        toolbox: true,
        supportedChartTypes: ['normalizedStackedBar', 'stackedBar', 'bar'],
        series: [{ field: 'paid_percent', name: 'Paid %', format: 'percent' }],
      },
      chartData: [
        { benefit_type: 'Medical', pay_type: 'Commercial', paid_percent: 70 },
        { benefit_type: 'Medical', pay_type: 'Medicare', paid_percent: 30 },
      ],
      aggregated: true,
      aggregationNote: 'Converted to percent-of-total',
    }),
  );

  assert.ok(spec);
  assert.deepEqual(getSelectableChartTypes(spec), ['normalizedStackedBar', 'stackedBar', 'bar']);
});

test('parseChartSpec rejects malformed chart payloads', () => {
  const spec = parseChartSpec(
    JSON.stringify({
      config: {
        chartType: 'bar',
        series: [],
      },
      chartData: [],
    }),
  );

  assert.equal(spec, null);
});

test('parseChartSpec accepts null compareLabels from backend payloads', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'bar',
      title: 'Average allowed amount',
      xAxisField: 'cancer_type',
      groupByField: 'insurance_type',
      yAxisField: null,
      series: [
        {
          field: 'avg_line_allowed',
          name: 'Avg Allowed Amount',
          format: 'currency',
          chartType: 'bar',
          axis: 'primary',
        },
      ],
      layout: 'grouped',
      toolbox: true,
      supportedChartTypes: ['bar', 'line', 'area', 'stackedBar', 'normalizedStackedBar'],
      referenceLines: [],
      compareLabels: null,
      transform: null,
    },
    chartData: [
      {
        cancer_type: 'Breast Cancer',
        insurance_type: 'COMMERCIAL',
        avg_line_allowed: 1078.11,
      },
    ],
    totalRows: 1,
    aggregated: false,
    aggregationNote: null,
  });

  assert.ok(spec);
  assert.equal(spec.config.compareLabels, null);
});

test('buildOption creates a heatmap config', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'heatmap',
      title: 'State by Benefit',
      xAxisField: 'state',
      yAxisField: 'benefit_type',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
    },
    chartData: [
      { state: 'MI', benefit_type: 'Medical', paid_amount: 100 },
      { state: 'MI', benefit_type: 'Rx', paid_amount: 50 },
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  assert.equal((option.series as any)?.[0]?.type, 'heatmap');
  assert.equal((option.xAxis as any)?.type, 'category');
  assert.equal((option.yAxis as any)?.type, 'category');
});

test('buildOption creates a dual-axis config', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'dualAxis',
      title: 'Volume vs Spend',
      xAxisField: 'month',
      series: [
        { field: 'claim_count', name: 'Claim Count', format: 'number', chartType: 'bar', axis: 'primary' },
        { field: 'paid_amount', name: 'Paid Amount', format: 'currency', chartType: 'line', axis: 'secondary' },
      ],
    },
    chartData: [
      { month: '2024-01', claim_count: 10, paid_amount: 1000 },
      { month: '2024-02', claim_count: 15, paid_amount: 1200 },
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  assert.equal(Array.isArray(option.yAxis), true);
  assert.equal((option.series as any)?.[0]?.type, 'bar');
  assert.equal((option.series as any)?.[1]?.type, 'line');
  assert.equal((option.series as any)?.[1]?.yAxisIndex, 1);
});

test('parseChartWorkspace accepts grouped visualization payloads', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-1',
    title: 'Monthly Spend',
    description: 'Trend workspace',
    table: {
      columns: ['service_month', 'paid_amount', 'benefit_type'],
      rows: [{ service_month: '2024-01', paid_amount: 100, benefit_type: 'Medical' }],
      totalRows: 1,
      previewRowCount: 1,
      isPreview: false,
      filename: 'results.csv',
      title: 'Monthly Spend',
    },
    fields: [
      { name: 'service_month', label: 'Service Month', kind: 'date', role: 'time', format: 'number', uniqueCount: 1, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 1, uniqueRatio: 1 },
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 1, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'line',
          title: 'Monthly Spend',
          xAxisField: 'service_month',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [{ service_month: '2024-01', paid_amount: 100 }],
      },
    ],
  });

  assert.ok(workspace);
  assert.equal(workspace?.charts.length, 1);
  assert.equal(workspace?.table.columns[0], 'service_month');
});

test('materializeChartSpecFromBuilder creates a normalized grouped chart from workspace rows', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-2',
    title: 'Benefit Share',
    table: {
      columns: ['service_month', 'paid_amount', 'benefit_type'],
      rows: [
        { service_month: '2024-01-01', paid_amount: 100, benefit_type: 'Medical' },
        { service_month: '2024-01-10', paid_amount: 50, benefit_type: 'Rx' },
        { service_month: '2024-02-01', paid_amount: 80, benefit_type: 'Medical' },
      ],
      totalRows: 3,
      previewRowCount: 3,
      isPreview: false,
      title: 'Benefit Share',
    },
    fields: [
      { name: 'service_month', label: 'Service Month', kind: 'date', role: 'time', format: 'number', uniqueCount: 3, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 3, uniqueRatio: 1 },
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 0.66 },
    ],
    charts: [
      {
        config: {
          chartType: 'line',
          title: 'Benefit Share',
          xAxisField: 'service_month',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [{ service_month: '2024-01', paid_amount: 150 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const nextBuilder = {
    ...builder,
    chartType: 'normalizedStackedBar' as const,
    xAxisField: 'service_month',
    yAxisField: 'paid_amount',
    groupByField: 'benefit_type',
    timeBucket: 'month' as const,
  };
  const validation = validateBuilderState(nextBuilder, workspace!);
  assert.equal(validation.valid, true);

  const spec = materializeChartSpecFromBuilder(workspace!, nextBuilder, workspace!.charts[0], 'manual');
  assert.equal(spec.config.layout, 'normalized');
  assert.equal(spec.config.groupByField, 'benefit_type');
  assert.equal(spec.chartData.length, 3);
  assert.match(spec.aggregationNote ?? '', /percent-of-total|Aggregated|Bucketed/i);
});

test('materializeChartSpecFromBuilder buckets numeric X axis into bins', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-ages',
    title: 'Age Spend',
    table: {
      columns: ['age', 'paid_amount'],
      rows: [
        { age: 5, paid_amount: 10 },
        { age: 8, paid_amount: 20 },
        { age: 17, paid_amount: 30 },
        { age: 24, paid_amount: 40 },
        { age: 33, paid_amount: 50 },
        { age: 41, paid_amount: 60 },
      ],
      totalRows: 6,
      previewRowCount: 6,
      isPreview: false,
      title: 'Age Spend',
    },
    fields: [
      { name: 'age', label: 'Age', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 6, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 6, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'bar',
          title: 'Age Spend',
          xAxisField: 'age',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [{ age: 5, paid_amount: 10 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = normalizeBuilderStateForChartType(
    {
      ...createBuilderStateFromChart(workspace!.charts[0], workspace!),
      chartType: 'bar',
      xAxisField: 'age',
      xAxisBinCount: 4,
      yAxisField: 'paid_amount',
    },
    workspace!.fields ?? [],
  );
  const validation = validateBuilderState(builder, workspace!);
  assert.equal(validation.valid, true);

  const spec = materializeChartSpecFromBuilder(workspace!, builder, workspace!.charts[0], 'manual');
  assert.equal(spec.config.transform?.type, 'histogram');
  assert.equal(spec.config.transform?.bins, 4);
  assert.ok(spec.chartData.length <= 4);
  assert.equal(typeof spec.chartData[0]?.age, 'string');
  assert.match(spec.aggregationNote ?? '', /Bucketed Age into 4 bins/i);
});

test('getChartBuilderUiConfig adapts controls by chart type', () => {
  const scatter = getChartBuilderUiConfig('scatter');
  assert.equal(scatter.xAxisKind, 'numeric');
  assert.equal(scatter.showZAxis, true);
  assert.equal(scatter.showAggregation, false);

  const pie = getChartBuilderUiConfig('pie');
  assert.equal(pie.showGroupBy, false);
  assert.equal(pie.showSecondaryYAxis, false);
  assert.equal(pie.showTopN, true);
});

test('normalizeBuilderStateForChartType clears incompatible fields', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-3',
    title: 'Diagnosis distribution',
    table: {
      columns: ['diagnosis_code', 'description', 'total_diagnosis_count', 'unique_patient_count'],
      rows: [
        { diagnosis_code: 'Z00129', description: 'Routine exam', total_diagnosis_count: 1160, unique_patient_count: 202 },
        { diagnosis_code: 'Z23', description: 'Immunization', total_diagnosis_count: 969, unique_patient_count: 197 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'Diagnosis distribution',
    },
    fields: [
      { name: 'diagnosis_code', label: 'Diagnosis Code', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'description', label: 'Description', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'total_diagnosis_count', label: 'Total Diagnosis Count', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'unique_patient_count', label: 'Unique Patient Count', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'bar',
          title: 'Diagnosis distribution',
          xAxisField: 'diagnosis_code',
          groupByField: 'description',
          series: [{ field: 'total_diagnosis_count', name: 'Total Diagnosis Count', format: 'number', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [{ diagnosis_code: 'Z00129', total_diagnosis_count: 1160 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);

  const pieState = normalizeBuilderStateForChartType(
    { ...builder, chartType: 'pie', groupByField: 'description', secondaryYAxisField: 'unique_patient_count' },
    workspace!.fields ?? [],
  );
  assert.equal(pieState.groupByField, '');
  assert.equal(pieState.secondaryYAxisField, '');

  const dualAxisState = normalizeBuilderStateForChartType(
    { ...builder, chartType: 'dualAxis', secondaryYAxisField: 'total_diagnosis_count' },
    workspace!.fields ?? [],
  );
  assert.equal(dualAxisState.secondaryYAxisField, 'unique_patient_count');
});
