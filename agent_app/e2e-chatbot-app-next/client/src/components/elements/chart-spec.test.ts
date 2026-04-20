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

test('buildOption creates a histogram config', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'histogram',
      title: 'Age Distribution',
      xAxisField: 'bucket',
      series: [{ field: 'count', name: 'Count', format: 'number' }],
      transform: { type: 'histogram', field: 'age', bins: 4 },
    },
    chartData: [
      { bucket: '0-10', count: 2 },
      { bucket: '10-20', count: 3 },
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  assert.equal((option.series as any)?.[0]?.type, 'bar');
  assert.deepEqual((option.xAxis as any)?.data, ['0-10', '10-20']);
});

test('buildOption heatmap preserves signed visualMap range', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'heatmap',
      title: 'Signed Heatmap',
      xAxisField: 'state',
      yAxisField: 'benefit_type',
      series: [{ field: 'delta', name: 'Delta', format: 'number' }],
    },
    chartData: [
      { state: 'MI', benefit_type: 'Medical', delta: -10 },
      { state: 'TX', benefit_type: 'Medical', delta: -5 },
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  assert.equal((option.visualMap as any)?.min, -10);
  assert.equal((option.visualMap as any)?.max, 0);
});

test('materializeChartSpecFromBuilder keeps heatmap category axis fields aligned', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-heatmap',
    title: 'State by Benefit',
    table: {
      columns: ['patient_state', 'benefit_type', 'paid_amount'],
      rows: [
        { patient_state: 'MI', benefit_type: 'Medical', paid_amount: 100 },
        { patient_state: 'MI', benefit_type: 'Rx', paid_amount: 50 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'State by Benefit',
    },
    fields: [
      { name: 'patient_state', label: 'Patient State', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 1, uniqueRatio: 0.5 },
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'heatmap',
          title: 'State by Benefit',
          xAxisField: 'patient_state',
          yAxisField: 'benefit_type',
          groupByField: 'benefit_type',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [
          { patient_state: 'MI', benefit_type: 'Medical', paid_amount: 100 },
          { patient_state: 'MI', benefit_type: 'Rx', paid_amount: 50 },
        ],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(workspace!, builder, workspace!.charts[0], 'manual');

  assert.equal(spec.config.chartType, 'heatmap');
  assert.equal(spec.config.yAxisField, 'benefit_type');
  assert.equal(spec.config.groupByField, 'benefit_type');
  assert.equal(spec.config.series[0]?.field, 'paid_amount');

  const option = buildOption(spec);
  assert.equal((option.yAxis as any)?.type, 'category');
});

test('createBuilderStateFromChart falls back to heatmap yAxisField for group field', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-heatmap-fallback',
    title: 'State by Benefit',
    table: {
      columns: ['patient_state', 'benefit_type', 'paid_amount'],
      rows: [{ patient_state: 'MI', benefit_type: 'Medical', paid_amount: 100 }],
      totalRows: 1,
      previewRowCount: 1,
      isPreview: false,
      title: 'State by Benefit',
    },
    fields: [
      { name: 'patient_state', label: 'Patient State', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 1, uniqueRatio: 1 },
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 1, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 1, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'heatmap',
          title: 'State by Benefit',
          xAxisField: 'patient_state',
          yAxisField: 'benefit_type',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [{ patient_state: 'MI', benefit_type: 'Medical', paid_amount: 100 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  assert.equal(builder.groupByField, 'benefit_type');
});

test('materializeChartSpecFromBuilder preserves ranking slope chart shape', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-ranking',
    title: 'Member rank shift',
    table: {
      columns: ['patient_id', 'service_year', 'paid_amount'],
      rows: [
        { patient_id: 'A', service_year: '2023', paid_amount: 100 },
        { patient_id: 'A', service_year: '2024', paid_amount: 80 },
        { patient_id: 'B', service_year: '2023', paid_amount: 90 },
        { patient_id: 'B', service_year: '2024', paid_amount: 120 },
      ],
      totalRows: 4,
      previewRowCount: 4,
      isPreview: false,
      title: 'Member rank shift',
    },
    fields: [
      { name: 'patient_id', label: 'Patient', kind: 'text', role: 'id', format: 'number', uniqueCount: 2, uniqueRatio: 0.5 },
      { name: 'service_year', label: 'Service Year', kind: 'text', role: 'time', format: 'number', uniqueCount: 2, uniqueRatio: 0.5 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 4, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'rankingSlope',
          title: 'Member rank shift',
          xAxisField: 'patient_id',
          groupByField: 'service_year',
          compareLabels: ['2023', '2024'],
          transform: { type: 'rankingSlope', periodField: 'service_year', metric: 'paid_amount', compareLabels: ['2023', '2024'] },
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [
          { patient_id: 'A', startLabel: '2023', endLabel: '2024', startRank: 1, endRank: 2, delta: -20 },
          { patient_id: 'B', startLabel: '2023', endLabel: '2024', startRank: 2, endRank: 1, delta: 30 },
        ],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(workspace!, builder, workspace!.charts[0], 'manual');

  assert.equal(spec.config.chartType, 'rankingSlope');
  assert.deepEqual(spec.config.compareLabels, ['2023', '2024']);
  assert.equal(spec.config.transform?.type, 'rankingSlope');
  assert.deepEqual(spec.config.transform?.compareLabels, ['2023', '2024']);
  assert.ok(spec.chartData.every((row) => 'startRank' in row && 'endRank' in row));

  const option = buildOption(spec);
  assert.equal((option.series as any)?.[0]?.type, 'line');
});

test('materializeChartSpecFromBuilder preserves delta comparison chart shape', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-delta',
    title: 'Year Over Year Change',
    table: {
      columns: ['benefit_type', 'service_year', 'paid_amount'],
      rows: [
        { benefit_type: 'Medical', service_year: '2023', paid_amount: 100 },
        { benefit_type: 'Medical', service_year: '2024', paid_amount: 80 },
        { benefit_type: 'Rx', service_year: '2023', paid_amount: 90 },
        { benefit_type: 'Rx', service_year: '2024', paid_amount: 120 },
      ],
      totalRows: 4,
      previewRowCount: 4,
      isPreview: false,
      title: 'Year Over Year Change',
    },
    fields: [
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 0.5 },
      { name: 'service_year', label: 'Service Year', kind: 'text', role: 'time', format: 'number', uniqueCount: 2, uniqueRatio: 0.5 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 4, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'deltaComparison',
          title: 'Year Over Year Change',
          xAxisField: 'benefit_type',
          groupByField: 'service_year',
          compareLabels: ['2023', '2024'],
          transform: { type: 'deltaComparison', periodField: 'service_year', metric: 'paid_amount', compareLabels: ['2023', '2024'] },
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [
          { benefit_type: 'Medical', startLabel: '2023', endLabel: '2024', startValue: 100, endValue: 80, delta: -20 },
          { benefit_type: 'Rx', startLabel: '2023', endLabel: '2024', startValue: 90, endValue: 120, delta: 30 },
        ],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(workspace!, builder, workspace!.charts[0], 'manual');

  assert.equal(spec.config.chartType, 'deltaComparison');
  assert.deepEqual(spec.config.compareLabels, ['2023', '2024']);
  assert.equal(spec.config.transform?.type, 'deltaComparison');
  assert.ok(spec.chartData.every((row) => 'delta' in row && 'startValue' in row && 'endValue' in row));

  const option = buildOption(spec);
  assert.equal((option.series as any)?.[0]?.type, 'bar');
});

test('materializeChartSpecFromBuilder omits comparison topN metadata when no topN is applied', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-ranking-no-topn',
    title: 'Member rank shift',
    table: {
      columns: ['patient_id', 'service_year', 'paid_amount'],
      rows: [
        { patient_id: 'A', service_year: '2023', paid_amount: 100 },
        { patient_id: 'A', service_year: '2024', paid_amount: 80 },
        { patient_id: 'B', service_year: '2023', paid_amount: 90 },
        { patient_id: 'B', service_year: '2024', paid_amount: 120 },
        { patient_id: 'C', service_year: '2023', paid_amount: 70 },
        { patient_id: 'C', service_year: '2024', paid_amount: 60 },
      ],
      totalRows: 6,
      previewRowCount: 6,
      isPreview: false,
      title: 'Member rank shift',
    },
    fields: [
      { name: 'patient_id', label: 'Patient', kind: 'text', role: 'id', format: 'number', uniqueCount: 3, uniqueRatio: 0.5 },
      { name: 'service_year', label: 'Service Year', kind: 'text', role: 'time', format: 'number', uniqueCount: 2, uniqueRatio: 0.33 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 6, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'rankingSlope',
          title: 'Member rank shift',
          xAxisField: 'patient_id',
          groupByField: 'service_year',
          compareLabels: ['2023', '2024'],
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'rankingSlope', topN: null },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.chartData.length, 3);
  assert.equal((spec.config.transform as any)?.topN, undefined);
});

test('materializeChartSpecFromBuilder reports shown topN in comparison aggregation note', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-delta-topn-note',
    title: 'Year Over Year Change',
    table: {
      columns: ['benefit_type', 'service_year', 'paid_amount'],
      rows: [
        { benefit_type: 'Medical', service_year: '2023', paid_amount: 100 },
        { benefit_type: 'Medical', service_year: '2024', paid_amount: 80 },
        { benefit_type: 'Rx', service_year: '2023', paid_amount: 90 },
        { benefit_type: 'Rx', service_year: '2024', paid_amount: 120 },
        { benefit_type: 'Dental', service_year: '2023', paid_amount: 30 },
        { benefit_type: 'Dental', service_year: '2024', paid_amount: 50 },
      ],
      totalRows: 6,
      previewRowCount: 6,
      isPreview: false,
      title: 'Year Over Year Change',
    },
    fields: [
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 3, uniqueRatio: 0.5 },
      { name: 'service_year', label: 'Service Year', kind: 'text', role: 'time', format: 'number', uniqueCount: 2, uniqueRatio: 0.33 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 6, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'deltaComparison',
          title: 'Year Over Year Change',
          xAxisField: 'benefit_type',
          groupByField: 'service_year',
          compareLabels: ['2023', '2024'],
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'deltaComparison', topN: 2 },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.chartData.length, 2);
  assert.match(spec.aggregationNote ?? '', /Computed deltas for 3 entities across 2023 and 2024; showing top 2/i);
});

test('materializeChartSpecFromBuilder preserves backend sortBy and passthrough meta fields', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-passthrough',
    title: 'Monthly Spend',
    table: {
      columns: ['service_month', 'paid_amount'],
      rows: [
        { service_month: '2024-01', paid_amount: 100 },
        { service_month: '2024-02', paid_amount: 50 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'Monthly Spend',
    },
    fields: [
      { name: 'service_month', label: 'Service Month', kind: 'date', role: 'time', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'line',
          title: 'Monthly Spend',
          xAxisField: 'service_month',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
          sortBy: { field: 'service_month', order: 'asc' },
        },
        chartData: [
          { service_month: '2024-01', paid_amount: 100 },
          { service_month: '2024-02', paid_amount: 50 },
        ],
        meta: {
          source: 'natural-language',
          businessInsight: 'January leads.',
          intentSource: 'llm',
        },
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(workspace!, builder, workspace!.charts[0], 'manual');

  assert.deepEqual((spec.config as any).sortBy, { field: 'service_month', order: 'asc' });
  assert.equal((spec.meta as any).businessInsight, 'January leads.');
  assert.equal((spec.meta as any).intentSource, 'llm');
});

test('materializeChartSpecFromBuilder keeps supported chart types aligned with backend capabilities', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-supported-types',
    title: 'Monthly Spend by Benefit',
    table: {
      columns: ['service_month', 'benefit_type', 'paid_amount', 'claim_count'],
      rows: [
        { service_month: '2024-01', benefit_type: 'Medical', paid_amount: 100, claim_count: 2 },
        { service_month: '2024-02', benefit_type: 'Rx', paid_amount: 50, claim_count: 1 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'Monthly Spend by Benefit',
    },
    fields: [
      { name: 'service_month', label: 'Service Month', kind: 'date', role: 'time', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'benefit_type', label: 'Benefit Type', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'claim_count', label: 'Claim Count', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'line',
          title: 'Monthly Spend by Benefit',
          xAxisField: 'service_month',
          groupByField: 'benefit_type',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const groupedSpec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, groupByField: 'benefit_type', chartType: 'line' },
    workspace!.charts[0],
    'manual',
  );
  assert.deepEqual(groupedSpec.config.supportedChartTypes, ['bar', 'line', 'area', 'stackedBar', 'normalizedStackedBar']);

  const dualAxisSpec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'dualAxis', secondaryYAxisField: 'claim_count', groupByField: '' },
    workspace!.charts[0],
    'manual',
  );
  assert.deepEqual(dualAxisSpec.config.supportedChartTypes, ['dualAxis', 'bar', 'line']);

  const histogramSpec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'bar', xAxisField: 'paid_amount', yAxisField: 'claim_count', xAxisBinCount: 5, groupByField: '' },
    workspace!.charts[0],
    'manual',
  );
  assert.deepEqual(histogramSpec.config.supportedChartTypes, ['histogram', 'bar', 'line']);
});

test('materializeChartSpecFromBuilder does not claim histogram when numeric binning cannot run', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-bad-bins',
    title: 'Invalid Numeric Bins',
    table: {
      columns: ['age_band', 'paid_amount'],
      rows: [
        { age_band: 'young', paid_amount: 10 },
        { age_band: 'adult', paid_amount: 20 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'Invalid Numeric Bins',
    },
    fields: [
      { name: 'age_band', label: 'Age Band', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'bar',
          title: 'Invalid Numeric Bins',
          xAxisField: 'age_band',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, xAxisField: 'age_band', yAxisField: 'paid_amount', xAxisBinCount: 5 },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.config.transform, null);
  assert.doesNotMatch(spec.aggregationNote ?? '', /Bucketed/);
  assert.notDeepEqual(spec.config.supportedChartTypes, ['bar', 'line']);
});

test('buildOption tooltip keeps legitimate zero values', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'bar',
      title: 'Monthly Spend',
      xAxisField: 'service_month',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
    },
    chartData: [
      { service_month: '2024-01', paid_amount: 0 },
      { service_month: '2024-02', paid_amount: 100 },
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  const formatter = (option.tooltip as any)?.formatter;
  assert.equal(typeof formatter, 'function');
  const html = formatter([
    {
      axisValueLabel: '2024-01',
      seriesName: 'Paid Amount',
      value: 0,
      marker: '',
    },
  ]);
  assert.match(String(html), /\$0|\b0\b/);
});

test('buildOption heatmap tooltip tolerates malformed params.value', () => {
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
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  const formatter = (option.tooltip as any)?.formatter;
  assert.equal(typeof formatter, 'function');
  const html = formatter({ value: 100 });
  assert.match(String(html), /\//);
});

test('buildOption scatter falls back to a single series when group values are blank', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'scatter',
      title: 'Age vs Spend',
      xAxisField: 'age',
      groupByField: 'segment',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
    },
    chartData: [
      { age: 40, paid_amount: 100, segment: '' },
      { age: 50, paid_amount: 200, segment: '' },
    ],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  assert.equal((option.series as any)?.length, 1);
  assert.deepEqual((option.series as any)?.[0]?.data, [
    { value: [40, 100], name: '40', xValue: '40', yValue: '100', groupValue: '' },
    { value: [50, 200], name: '50', xValue: '50', yValue: '200', groupValue: '' },
  ]);
});

test('buildOption cartesian tooltip escapes html labels', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'bar',
      title: 'Unsafe Labels',
      xAxisField: 'category',
      series: [{ field: 'paid_amount', name: '<b>Paid</b>', format: 'currency' }],
    },
    chartData: [{ category: '<img>', paid_amount: 10 }],
  });

  assert.ok(spec);
  const option = buildOption(spec);
  const formatter = (option.tooltip as any)?.formatter;
  assert.equal(typeof formatter, 'function');
  const html = formatter([
    {
      axisValueLabel: '<img>',
      seriesName: '<b>Paid</b>',
      value: 10,
      marker: '',
    },
  ]);
  assert.doesNotMatch(String(html), /<img>|<b>/);
  assert.match(String(html), /&lt;img&gt;|&lt;b&gt;Paid&lt;\/b&gt;/);
});

test('validateBuilderState rejects non-numeric scatter bubble size fields', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-scatter-z',
    title: 'Age vs Spend',
    table: {
      columns: ['age', 'paid_amount', 'segment'],
      rows: [{ age: 40, paid_amount: 100, segment: 'A' }],
      totalRows: 1,
      previewRowCount: 1,
      isPreview: false,
      title: 'Age vs Spend',
    },
    fields: [
      { name: 'age', label: 'Age', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 1, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 1, uniqueRatio: 1 },
      { name: 'segment', label: 'Segment', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 1, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'scatter',
          title: 'Age vs Spend',
          xAxisField: 'age',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [{ age: 40, paid_amount: 100 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const result = validateBuilderState({ ...builder, chartType: 'scatter', zAxisField: 'segment' }, workspace!);
  assert.equal(result.valid, false);
  assert.match(result.issues.join(' '), /bubble size must use a numeric field/i);
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

test('materializeChartSpecFromBuilder applies topN on date x-axis when enabled', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-date-topn',
    title: 'Monthly Spend',
    table: {
      columns: ['service_month', 'paid_amount'],
      rows: [
        { service_month: '2024-01', paid_amount: 100 },
        { service_month: '2024-02', paid_amount: 300 },
        { service_month: '2024-03', paid_amount: 200 },
      ],
      totalRows: 3,
      previewRowCount: 3,
      isPreview: false,
      title: 'Monthly Spend',
    },
    fields: [
      { name: 'service_month', label: 'Service Month', kind: 'date', role: 'time', format: 'number', uniqueCount: 3, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 3, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'line',
          title: 'Monthly Spend',
          xAxisField: 'service_month',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'line', topN: 2 },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.chartData.length, 3);
  assert.match(spec.aggregationNote ?? '', /Top 2 categories/i);
  assert.equal(spec.config.transform?.type, 'topN');
  assert.equal((spec.config.transform as any)?.n, 2);
});

test('materializeChartSpecFromBuilder applies topN by whole x categories for grouped charts', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-grouped-topn',
    title: 'Spend by Category',
    table: {
      columns: ['category', 'segment', 'paid_amount'],
      rows: [
        { category: 'A', segment: 'Commercial', paid_amount: 90 },
        { category: 'A', segment: 'Medicare', paid_amount: 10 },
        { category: 'B', segment: 'Commercial', paid_amount: 40 },
        { category: 'B', segment: 'Medicare', paid_amount: 30 },
        { category: 'C', segment: 'Commercial', paid_amount: 20 },
        { category: 'C', segment: 'Medicare', paid_amount: 10 },
      ],
      totalRows: 6,
      previewRowCount: 6,
      isPreview: false,
      title: 'Spend by Category',
    },
    fields: [
      { name: 'category', label: 'Category', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 3, uniqueRatio: 0.5 },
      { name: 'segment', label: 'Segment', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 0.33 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 6, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'bar',
          title: 'Spend by Category',
          xAxisField: 'category',
          groupByField: 'segment',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'bar', topN: 1 },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.chartData.length, 4);
  assert.deepEqual(
    spec.chartData.map((row) => [row.category, row.segment, row.paid_amount]),
    [
      ['A', 'Commercial', 90],
      ['A', 'Medicare', 10],
      ['Other', 'Commercial', 60],
      ['Other', 'Medicare', 40],
    ],
  );
});

test('materializeChartSpecFromBuilder applies topN before normalization for grouped charts', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-normalized-topn',
    title: 'Spend Mix by Category',
    table: {
      columns: ['category', 'segment', 'paid_amount'],
      rows: [
        { category: 'A', segment: 'Commercial', paid_amount: 90 },
        { category: 'A', segment: 'Medicare', paid_amount: 10 },
        { category: 'B', segment: 'Commercial', paid_amount: 40 },
        { category: 'B', segment: 'Medicare', paid_amount: 30 },
        { category: 'C', segment: 'Commercial', paid_amount: 20 },
        { category: 'C', segment: 'Medicare', paid_amount: 10 },
      ],
      totalRows: 6,
      previewRowCount: 6,
      isPreview: false,
      title: 'Spend Mix by Category',
    },
    fields: [
      { name: 'category', label: 'Category', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 3, uniqueRatio: 0.5 },
      { name: 'segment', label: 'Segment', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 2, uniqueRatio: 0.33 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 6, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'normalizedStackedBar',
          title: 'Spend Mix by Category',
          xAxisField: 'category',
          groupByField: 'segment',
          layout: 'normalized',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'normalizedStackedBar', topN: 1 },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.config.layout, 'normalized');
  assert.match(spec.aggregationNote ?? '', /Top 1 categories/i);
  assert.deepEqual(
    spec.chartData.map((row) => [row.category, row.segment, Math.round(Number(row.paid_amount))]),
    [
      ['A', 'Commercial', 90],
      ['A', 'Medicare', 10],
      ['Other', 'Commercial', 60],
      ['Other', 'Medicare', 40],
    ],
  );
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

test('materializeChartSpecFromBuilder applies topN to binned numeric x-axis charts', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-binned-topn',
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
        chartData: [],
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
      topN: 1,
    },
    workspace!.fields ?? [],
  );
  const spec = materializeChartSpecFromBuilder(workspace!, builder, workspace!.charts[0], 'manual');

  assert.equal(spec.config.transform?.type, 'histogram');
  assert.equal((spec.config.transform as any)?.topN, 1);
  assert.equal(spec.chartData.length, 2);
  assert.equal(spec.chartData[0]?.paid_amount, 110);
  assert.equal(spec.chartData[1]?.age, 'Other');
  assert.equal(spec.chartData[1]?.paid_amount, 100);
});

test('materializeChartSpecFromBuilder persists pie topN in transform metadata', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-pie-topn',
    title: 'Spend by Category',
    table: {
      columns: ['category', 'paid_amount'],
      rows: [
        { category: 'A', paid_amount: 90 },
        { category: 'B', paid_amount: 80 },
        { category: 'C', paid_amount: 70 },
        { category: 'D', paid_amount: 60 },
        { category: 'E', paid_amount: 50 },
        { category: 'F', paid_amount: 40 },
      ],
      totalRows: 6,
      previewRowCount: 6,
      isPreview: false,
      title: 'Spend by Category',
    },
    fields: [
      { name: 'category', label: 'Category', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 6, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 6, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'pie',
          title: 'Spend by Category',
          xAxisField: 'category',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'pie', topN: 4 },
    workspace!.charts[0],
    'manual',
  );
  const roundTrippedBuilder = createBuilderStateFromChart(spec, workspace!);

  assert.equal(spec.config.transform?.type, 'topN');
  assert.equal((spec.config.transform as any)?.n, 4);
  assert.equal(roundTrippedBuilder.topN, 4);
});

test('materializeChartSpecFromBuilder defaults pie topN when builder value is non-positive', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-pie-topn-default',
    title: 'Spend by Category',
    table: {
      columns: ['category', 'paid_amount'],
      rows: [
        { category: 'A', paid_amount: 90 },
        { category: 'B', paid_amount: 80 },
        { category: 'C', paid_amount: 70 },
        { category: 'D', paid_amount: 60 },
        { category: 'E', paid_amount: 50 },
        { category: 'F', paid_amount: 40 },
        { category: 'G', paid_amount: 30 },
      ],
      totalRows: 7,
      previewRowCount: 7,
      isPreview: false,
      title: 'Spend by Category',
    },
    fields: [
      { name: 'category', label: 'Category', kind: 'text', role: 'dimension', format: 'number', uniqueCount: 7, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 7, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'pie',
          title: 'Spend by Category',
          xAxisField: 'category',
          series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
          style: { palette: 'default' },
        },
        chartData: [],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  const spec = materializeChartSpecFromBuilder(
    workspace!,
    { ...builder, chartType: 'pie', topN: 0 },
    workspace!.charts[0],
    'manual',
  );

  assert.equal(spec.config.transform?.type, 'topN');
  assert.equal((spec.config.transform as any)?.n, 6);
  assert.match(spec.aggregationNote ?? '', /Top 6 categories/i);
});

test('createBuilderStateFromChart preserves histogram source field and bins from backend specs', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-hist',
    title: 'Age Distribution',
    table: {
      columns: ['age', 'paid_amount'],
      rows: [
        { age: 5, paid_amount: 10 },
        { age: 8, paid_amount: 20 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'Age Distribution',
    },
    fields: [
      { name: 'age', label: 'Age', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'bar',
          title: 'Age Distribution',
          xAxisField: 'bucket',
          series: [{ field: 'count', name: 'Count', format: 'number', axis: 'primary' }],
          transform: { type: 'histogram', field: 'age', bins: 4 },
          style: { palette: 'default' },
        },
        chartData: [{ bucket: '5-10', bucketStart: 5, bucketEnd: 10, count: 2 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  assert.equal(builder.chartType, 'histogram');
  assert.equal(builder.xAxisField, 'age');
  assert.equal(builder.xAxisBinCount, 4);
});

test('createBuilderStateFromChart preserves histogram bins when topN metadata coexists', () => {
  const workspace = parseChartWorkspace({
    workspaceId: 'query-hist-topn',
    title: 'Age Distribution',
    table: {
      columns: ['age', 'paid_amount'],
      rows: [
        { age: 5, paid_amount: 10 },
        { age: 8, paid_amount: 20 },
      ],
      totalRows: 2,
      previewRowCount: 2,
      isPreview: false,
      title: 'Age Distribution',
    },
    fields: [
      { name: 'age', label: 'Age', kind: 'numeric', role: 'measure', format: 'number', uniqueCount: 2, uniqueRatio: 1 },
      { name: 'paid_amount', label: 'Paid Amount', kind: 'numeric', role: 'currency', format: 'currency', uniqueCount: 2, uniqueRatio: 1 },
    ],
    charts: [
      {
        config: {
          chartType: 'bar',
          title: 'Age Distribution',
          xAxisField: 'bucket',
          series: [{ field: 'count', name: 'Count', format: 'number', axis: 'primary' }],
          transform: { type: 'histogram', field: 'age', bins: 4, topN: 3 },
          style: { palette: 'default' },
        },
        chartData: [{ bucket: '5-10', bucketStart: 5, bucketEnd: 10, count: 2 }],
      },
    ],
  });

  assert.ok(workspace);
  const builder = createBuilderStateFromChart(workspace!.charts[0], workspace!);
  assert.equal(builder.chartType, 'histogram');
  assert.equal(builder.xAxisField, 'age');
  assert.equal(builder.xAxisBinCount, 4);
  assert.equal(builder.topN, 3);
});

test('getSelectableChartTypes exposes histogram for numeric axis charts', () => {
  const spec = parseChartSpec({
    config: {
      chartType: 'bar',
      title: 'Age Spend',
      xAxisField: 'age',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency' }],
      supportedChartTypes: ['bar', 'line', 'scatter', 'pie'],
    },
    chartData: [
      { age: 10, paid_amount: 100 },
      { age: 20, paid_amount: 200 },
    ],
    downloadData: [
      { age: 10, paid_amount: 100 },
      { age: 20, paid_amount: 200 },
    ],
  });

  assert.ok(spec);
  assert.deepEqual(getSelectableChartTypes(spec), ['bar', 'histogram', 'line', 'scatter', 'pie']);
});

test('getChartBuilderUiConfig adapts controls by chart type', () => {
  const histogram = getChartBuilderUiConfig('histogram');
  assert.equal(histogram.xAxisKind, 'numeric');
  assert.equal(histogram.showGroupBy, false);
  assert.equal(histogram.showSort, true);

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
