import test from 'node:test';
import assert from 'node:assert/strict';

import { buildOption } from './chart-spec';
import { extractSelectionFromClick, matchesSelection } from './interactive-chart';

test('scatter selection extracts point values and matches raw rows', () => {
  const spec = {
    config: {
      chartType: 'scatter',
      title: 'Age vs Paid',
      xAxisField: 'age',
      yAxisField: null,
      zAxisField: 'member_count',
      groupByField: 'segment',
      layout: 'clustered',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
      toolbox: true,
      supportedChartTypes: ['scatter'],
      referenceLines: [],
      compareLabels: null,
      sortBy: null,
      transform: null,
      style: {},
    },
    chartData: [
      { age: 42, paid_amount: 100, member_count: 3, segment: 'Commercial' },
    ],
    downloadData: [
      { age: 42, paid_amount: 100, member_count: 3, segment: 'Commercial' },
      { age: 42, paid_amount: 110, member_count: 3, segment: 'Commercial' },
    ],
    totalRows: 2,
    aggregated: false,
    aggregationNote: null,
    meta: {},
  } as any;

  const option = buildOption(spec);
  const firstSeries = Array.isArray(option.series) ? option.series[0] as any : null;
  const firstPoint = firstSeries?.data?.[0];

  const selection = extractSelectionFromClick(
    spec,
    {
      componentType: 'series',
      seriesName: 'Commercial',
      value: firstPoint?.value,
      data: firstPoint,
    },
    10,
    20,
  );

  assert.deepEqual(selection, {
    xValue: '42',
    groupValue: 'Commercial',
    yValue: '100',
    zValue: '3',
    seriesName: 'Commercial',
    left: 10,
    top: 20,
  });
  assert.equal(matchesSelection(spec.downloadData[0], spec, selection), true);
  assert.equal(matchesSelection(spec.downloadData[1], spec, selection), false);
});

test('heatmap selection extracts axis labels and matches grouped rows', () => {
  const spec = {
    config: {
      chartType: 'heatmap',
      title: 'State by Benefit',
      xAxisField: 'patient_state',
      yAxisField: 'benefit_type',
      zAxisField: null,
      groupByField: 'benefit_type',
      layout: 'clustered',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
      toolbox: true,
      supportedChartTypes: ['heatmap'],
      referenceLines: [],
      compareLabels: null,
      sortBy: null,
      transform: { type: 'heatmap', xField: 'patient_state', yField: 'benefit_type', metric: 'paid_amount', function: 'sum' },
      style: {},
    },
    chartData: [
      { patient_state: 'KS', benefit_type: 'Medical', paid_amount: 100 },
    ],
    downloadData: [
      { patient_state: 'KS', benefit_type: 'Medical', paid_amount: 100 },
      { patient_state: 'KS', benefit_type: 'Rx', paid_amount: 50 },
    ],
    totalRows: 2,
    aggregated: true,
    aggregationNote: null,
    meta: {},
  } as any;

  const option = buildOption(spec);
  const heatmapSeries = Array.isArray(option.series) ? option.series[0] as any : null;
  const firstCell = heatmapSeries?.data?.[0];

  const selection = extractSelectionFromClick(
    spec,
    {
      componentType: 'series',
      value: firstCell?.value,
      data: firstCell,
    },
    0,
    0,
  );

  assert.deepEqual(selection, {
    xValue: 'KS',
    groupValue: 'Medical',
    yValue: undefined,
    zValue: undefined,
    seriesName: undefined,
    left: 0,
    top: 0,
  });
  assert.equal(matchesSelection(spec.downloadData[0], spec, selection), true);
  assert.equal(matchesSelection(spec.downloadData[1], spec, selection), false);
});

test('ranking slope selection uses series name so row filtering matches entity rows', () => {
  const spec = {
    config: {
      chartType: 'rankingSlope',
      title: 'Member rank shift',
      xAxisField: 'patient_id',
      yAxisField: null,
      zAxisField: null,
      groupByField: 'service_year',
      layout: 'clustered',
      series: [{ field: 'paid_amount', name: 'Paid Amount', format: 'currency', axis: 'primary' }],
      toolbox: true,
      supportedChartTypes: ['rankingSlope'],
      referenceLines: [],
      compareLabels: ['2023', '2024'],
      sortBy: null,
      transform: { type: 'rankingSlope', periodField: 'service_year', metric: 'paid_amount', compareLabels: ['2023', '2024'] },
      style: {},
    },
    chartData: [
      { patient_id: 'A', startLabel: '2023', endLabel: '2024', startRank: 1, endRank: 2 },
    ],
    downloadData: [
      { patient_id: 'A', service_year: '2023', paid_amount: 100 },
      { patient_id: 'A', service_year: '2024', paid_amount: 80 },
      { patient_id: 'B', service_year: '2023', paid_amount: 90 },
    ],
    totalRows: 3,
    aggregated: true,
    aggregationNote: null,
    meta: {},
  } as any;

  const selection = extractSelectionFromClick(
    spec,
    {
      componentType: 'series',
      name: '2023',
      seriesName: 'A',
      value: 1,
    },
    5,
    6,
  );

  assert.deepEqual(selection, {
    xValue: 'A',
    groupValue: undefined,
    yValue: undefined,
    zValue: undefined,
    seriesName: 'A',
    left: 5,
    top: 6,
  });
  assert.equal(matchesSelection(spec.downloadData[0], spec, selection), true);
  assert.equal(matchesSelection(spec.downloadData[1], spec, selection), true);
  assert.equal(matchesSelection(spec.downloadData[2], spec, selection), false);
});
