import test from 'node:test';
import assert from 'node:assert/strict';

import { buildOption, getSelectableChartTypes, parseChartSpec } from './chart-spec';

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
