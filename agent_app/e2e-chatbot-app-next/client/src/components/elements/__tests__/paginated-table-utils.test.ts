/**
 * Unit tests for paginated-table-utils.ts
 *
 * Run with:
 *   node --import tsx --test client/src/components/elements/__tests__/paginated-table-utils.test.ts
 *
 * These tests cover the pure-logic portions of the PaginatedTable (column
 * inference, formatting, totals, delimited export, localStorage keying,
 * and heatmap color math) — everything that can be verified without a
 * browser.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { createElement } from "react";
import {
	type NormalizedTable,
	type TableDataRow,
	buildDelimited,
	buildTotalsRow,
	coerceValue,
	computeColumnMeta,
	formatValueByKind,
	heatmapBackground,
	inferColumnKind,
	makeStateKey,
	normalizeTableData,
	parseNodesTable,
} from "../paginated-table-utils";

// -----------------------------------------------------------------------------
// parseNodesTable
// -----------------------------------------------------------------------------

describe("parseNodesTable", () => {
	test("extracts columns and rows from a thead/tbody tree", () => {
		const tree = createElement("table", null, [
			createElement("thead", { key: "h" }, [
				createElement("tr", { key: "hr" }, [
					createElement("th", { key: "c1" }, "name"),
					createElement("th", { key: "c2" }, "count"),
				]),
			]),
			createElement("tbody", { key: "b" }, [
				createElement("tr", { key: "r1" }, [
					createElement("td", { key: "c1" }, "alice"),
					createElement("td", { key: "c2" }, "3"),
				]),
				createElement("tr", { key: "r2" }, [
					createElement("td", { key: "c1" }, "bob"),
					createElement("td", { key: "c2" }, "5"),
				]),
			]),
		]);
		const parsed = parseNodesTable(tree.props.children);
		assert.deepEqual(parsed.columns, ["name", "count"]);
		assert.equal(parsed.rows.length, 2);
		assert.equal(parsed.rows[0].name, "alice");
		assert.equal(parsed.rows[0].count, "3");
		assert.equal(parsed.totalRows, 2);
		assert.equal(parsed.isPreview, false);
	});

	test("handles header-only row inside loose rows", () => {
		const rows = [
			createElement("tr", { key: "r1" }, [
				createElement("th", { key: "c1" }, "a"),
				createElement("th", { key: "c2" }, "b"),
			]),
			createElement("tr", { key: "r2" }, [
				createElement("td", { key: "c1" }, "1"),
				createElement("td", { key: "c2" }, "2"),
			]),
		];
		const parsed = parseNodesTable(rows);
		assert.deepEqual(parsed.columns, ["a", "b"]);
		assert.equal(parsed.rows.length, 1);
		assert.equal(parsed.rows[0].a, "1");
	});

	test("returns empty table for empty children", () => {
		const parsed = parseNodesTable([]);
		assert.deepEqual(parsed.columns, []);
		assert.deepEqual(parsed.rows, []);
		assert.equal(parsed.totalRows, 0);
	});
});

// -----------------------------------------------------------------------------
// normalizeTableData
// -----------------------------------------------------------------------------

describe("normalizeTableData", () => {
	test("marks isPreview when totalRows > shipped rows", () => {
		const result = normalizeTableData({
			columns: ["a"],
			rows: [{ a: 1 }, { a: 2 }],
			totalRows: 1000,
		});
		// totalRows is clamped to shipped count but isPreview stays true.
		assert.equal(result.totalRows, 2);
		assert.equal(result.isPreview, true);
	});

	test("uses explicit isPreview flag", () => {
		const result = normalizeTableData({
			columns: ["a"],
			rows: [{ a: 1 }],
			isPreview: true,
		});
		assert.equal(result.isPreview, true);
	});

	test("applies defaults for filename/title/sql", () => {
		const result = normalizeTableData({ columns: [], rows: [] });
		assert.equal(result.filename, "results.csv");
		assert.equal(result.title, "Results");
		assert.equal(result.sql, "");
		assert.equal(result.sqlFilename, "query.sql");
	});

	test("trims sql whitespace", () => {
		const result = normalizeTableData({
			columns: [],
			rows: [],
			sql: "  SELECT 1  \n",
		});
		assert.equal(result.sql, "SELECT 1");
	});
});

// -----------------------------------------------------------------------------
// inferColumnKind
// -----------------------------------------------------------------------------

describe("inferColumnKind", () => {
	const makeRows = (column: string, values: unknown[]): TableDataRow[] =>
		values.map((v) => ({ [column]: v }));

	test("returns text when no data", () => {
		assert.equal(inferColumnKind("anything", []), "text");
	});

	test("detects integer by column name hint + all-integer values", () => {
		const rows = makeRows("claim_count", [1, 5, 100, "2,500"]);
		assert.equal(inferColumnKind("claim_count", rows), "integer");
	});

	test("detects integer by all-integer values with id column", () => {
		const rows = makeRows("patient_id", ["1", "2", "3", "1000"]);
		assert.equal(inferColumnKind("patient_id", rows), "integer");
	});

	test("detects number for decimal values without special name", () => {
		const rows = makeRows("ratio", ["0.25", "0.75", "1.5"]);
		assert.equal(inferColumnKind("ratio", rows), "number");
	});

	test("detects currency by column name", () => {
		const rows = makeRows("paid_amount", [100, 200, 300]);
		assert.equal(inferColumnKind("paid_amount", rows), "currency");
	});

	test("detects currency by value prefix ($)", () => {
		const rows = makeRows("charge", ["$100.00", "$200.50", "$1,234.56"]);
		assert.equal(inferColumnKind("charge", rows), "currency");
	});

	test("detects percent by column name", () => {
		const rows = makeRows("approval_rate", [0.92, 0.85, 0.99]);
		assert.equal(inferColumnKind("approval_rate", rows), "percent");
	});

	test("detects percent by trailing % in values", () => {
		const rows = makeRows("coverage", ["92%", "85%", "99%"]);
		assert.equal(inferColumnKind("coverage", rows), "percent");
	});

	test("detects date by column name + ISO values", () => {
		const rows = makeRows("service_date", [
			"2024-01-15",
			"2024-02-20",
			"2024-03-05",
		]);
		assert.equal(inferColumnKind("service_date", rows), "date");
	});

	test("detects date by ISO timestamp", () => {
		const rows = makeRows("created_at", [
			"2024-01-15T10:30:00Z",
			"2024-02-20T15:00:00Z",
		]);
		assert.equal(inferColumnKind("created_at", rows), "date");
	});

	test("returns text for non-numeric mixed values", () => {
		const rows = makeRows("status", [
			"active",
			"inactive",
			"pending",
			"cancelled",
			"active",
			"pending",
		]);
		assert.equal(inferColumnKind("status", rows), "text");
	});

	test("ignores null/empty values when sampling", () => {
		const rows = makeRows("amount", [null, "", 100, 200, 300]);
		assert.equal(inferColumnKind("amount", rows), "currency");
	});
});

// -----------------------------------------------------------------------------
// coerceValue
// -----------------------------------------------------------------------------

describe("coerceValue", () => {
	test("null for null/empty", () => {
		assert.equal(coerceValue(null, "number"), null);
		assert.equal(coerceValue("", "number"), null);
		assert.equal(coerceValue(undefined, "number"), null);
	});

	test("parses plain number", () => {
		assert.equal(coerceValue("123", "integer"), 123);
		assert.equal(coerceValue("1.5", "number"), 1.5);
	});

	test("strips thousand separators", () => {
		assert.equal(coerceValue("1,234,567", "integer"), 1234567);
	});

	test("strips leading currency symbol", () => {
		assert.equal(coerceValue("$1,234.56", "currency"), 1234.56);
		assert.equal(coerceValue("€99.00", "currency"), 99);
	});

	test("converts % suffix to ratio", () => {
		assert.equal(coerceValue("25%", "percent"), 0.25);
		assert.equal(coerceValue("100%", "percent"), 1);
	});

	test("returns Date for date kind", () => {
		const result = coerceValue("2024-01-15", "date");
		assert.ok(result instanceof Date);
		assert.equal((result as Date).getUTCFullYear(), 2024);
		assert.equal((result as Date).getUTCMonth(), 0);
		assert.equal((result as Date).getUTCDate(), 15);
	});

	test("returns null for non-date strings under date kind", () => {
		assert.equal(coerceValue("not-a-date", "date"), null);
	});

	test("text kind returns string representation", () => {
		assert.equal(coerceValue("alice", "text"), "alice");
		assert.equal(coerceValue(42, "text"), "42");
	});
});

// -----------------------------------------------------------------------------
// formatValueByKind
// -----------------------------------------------------------------------------

describe("formatValueByKind", () => {
	test("integer formats with thousand separators", () => {
		const out = formatValueByKind(1234567, "integer");
		// Locale-dependent separator — check a digit group appears.
		assert.match(out, /1[.,\s]?234[.,\s]?567/);
	});

	test("currency includes a currency symbol", () => {
		const out = formatValueByKind(1234.56, "currency");
		assert.match(out, /[$€£¥₹]/);
		assert.match(out, /1[.,\s]?234/);
	});

	test("percent formats 0.25 as ~25%", () => {
		const out = formatValueByKind(0.25, "percent");
		assert.match(out, /25\s?%/);
	});

	test("date formats ISO date to readable date", () => {
		const out = formatValueByKind("2024-01-15", "date");
		// Some form of 2024 and 15 should appear.
		assert.match(out, /2024/);
		assert.match(out, /15/);
	});

	test("empty for null or empty string", () => {
		assert.equal(formatValueByKind(null, "number"), "");
		assert.equal(formatValueByKind("", "currency"), "");
	});

	test("text kind returns the stringified value", () => {
		assert.equal(formatValueByKind("alice", "text"), "alice");
	});
});

// -----------------------------------------------------------------------------
// computeColumnMeta
// -----------------------------------------------------------------------------

describe("computeColumnMeta", () => {
	test("computes min/max for numeric columns", () => {
		const rows: TableDataRow[] = [
			{ amount: 10, name: "a" },
			{ amount: 50, name: "b" },
			{ amount: 25, name: "c" },
		];
		const meta = computeColumnMeta(rows, ["amount", "name"]);
		assert.equal(meta.amount.kind, "currency");
		assert.equal(meta.amount.min, 10);
		assert.equal(meta.amount.max, 50);
		assert.equal(meta.name.kind, "text");
		assert.equal(meta.name.min, undefined);
		assert.equal(meta.name.max, undefined);
	});

	test("leaves min/max undefined when column is all-empty", () => {
		const rows: TableDataRow[] = [{ amount: null }, { amount: "" }];
		const meta = computeColumnMeta(rows, ["amount"]);
		assert.equal(meta.amount.min, undefined);
		assert.equal(meta.amount.max, undefined);
	});
});

// -----------------------------------------------------------------------------
// buildTotalsRow
// -----------------------------------------------------------------------------

describe("buildTotalsRow", () => {
	const rows: TableDataRow[] = [
		{ name: "a", claim_count: 10, paid_amount: 100 },
		{ name: "b", claim_count: 20, paid_amount: 250 },
		{ name: "c", claim_count: 30, paid_amount: 175 },
	];
	const columns = ["name", "claim_count", "paid_amount"];
	const meta = computeColumnMeta(rows, columns);

	test("returns null for mode=none", () => {
		assert.equal(buildTotalsRow(rows, meta, columns, "none"), null);
	});

	test("sum aggregates numeric columns", () => {
		const total = buildTotalsRow(rows, meta, columns, "sum");
		assert.ok(total);
		assert.equal(total?.claim_count, 60);
		assert.equal(total?.paid_amount, 525);
	});

	test("avg aggregates numeric columns", () => {
		const total = buildTotalsRow(rows, meta, columns, "avg");
		assert.ok(total);
		assert.equal(total?.claim_count, 20);
		assert.equal(total?.paid_amount, 175);
	});

	test("min / max", () => {
		const min = buildTotalsRow(rows, meta, columns, "min");
		const max = buildTotalsRow(rows, meta, columns, "max");
		assert.equal(min?.claim_count, 10);
		assert.equal(min?.paid_amount, 100);
		assert.equal(max?.claim_count, 30);
		assert.equal(max?.paid_amount, 250);
	});

	test("integer mode rounds for sum but not avg", () => {
		const rowsWithFloatInts: TableDataRow[] = [
			{ id: 1, frac_count: 1 },
			{ id: 2, frac_count: 2 },
			{ id: 3, frac_count: 2 }, // count of 3 items, sum=5, avg=1.666...
		];
		const cols = ["id", "frac_count"];
		const m = computeColumnMeta(rowsWithFloatInts, cols);
		const sum = buildTotalsRow(rowsWithFloatInts, m, cols, "sum");
		const avg = buildTotalsRow(rowsWithFloatInts, m, cols, "avg");
		assert.equal(sum?.frac_count, 5);
		assert.ok(
			typeof avg?.frac_count === "number" &&
				Math.abs((avg?.frac_count as number) - 5 / 3) < 1e-9,
		);
	});

	test("writes label in first text column", () => {
		const total = buildTotalsRow(rows, meta, columns, "sum");
		assert.equal(total?.name, "Sum");
	});

	test("returns null when there are no numeric columns", () => {
		const textOnlyRows: TableDataRow[] = [
			{ a: "x", b: "y" },
			{ a: "m", b: "n" },
		];
		const m = computeColumnMeta(textOnlyRows, ["a", "b"]);
		assert.equal(buildTotalsRow(textOnlyRows, m, ["a", "b"], "sum"), null);
	});
});

// -----------------------------------------------------------------------------
// buildDelimited
// -----------------------------------------------------------------------------

describe("buildDelimited", () => {
	const columns = ["name", "count"];
	const rows: TableDataRow[] = [
		{ name: "alice", count: 1 },
		{ name: "bob", count: 2 },
	];

	test("returns comma-separated CSV with header", () => {
		const csv = buildDelimited(columns, rows, ",");
		assert.equal(csv, "name,count\nalice,1\nbob,2");
	});

	test("returns tab-separated TSV", () => {
		const tsv = buildDelimited(columns, rows, "\t");
		assert.equal(tsv, "name\tcount\nalice\t1\nbob\t2");
	});

	test("omits header when includeHeader=false", () => {
		const csv = buildDelimited(columns, rows, ",", false);
		assert.equal(csv, "alice,1\nbob,2");
	});

	test("quotes values containing the separator", () => {
		const csv = buildDelimited(["a"], [{ a: "hello, world" }], ",");
		assert.equal(csv, 'a\n"hello, world"');
	});

	test("escapes embedded double-quotes", () => {
		const csv = buildDelimited(["a"], [{ a: 'she said "hi"' }], ",");
		assert.equal(csv, 'a\n"she said ""hi"""');
	});

	test("quotes values with newlines", () => {
		const csv = buildDelimited(["a"], [{ a: "line1\nline2" }], ",");
		assert.equal(csv, 'a\n"line1\nline2"');
	});

	test("empty string for empty columns", () => {
		assert.equal(buildDelimited([], rows, ","), "");
	});

	test("null and undefined become empty fields", () => {
		const csv = buildDelimited(
			["a", "b"],
			[{ a: null, b: undefined }],
			",",
			false,
		);
		assert.equal(csv, ",");
	});
});

// -----------------------------------------------------------------------------
// heatmapBackground
// -----------------------------------------------------------------------------

describe("heatmapBackground", () => {
	test("returns undefined when min equals max", () => {
		assert.equal(heatmapBackground(5, 5, 5, "light"), undefined);
	});

	test("returns undefined for non-finite input", () => {
		assert.equal(heatmapBackground(Number.NaN, 0, 10, "light"), undefined);
		assert.equal(
			heatmapBackground(5, 0, Number.POSITIVE_INFINITY, "light"),
			undefined,
		);
	});

	test("returns an rgba color when valid", () => {
		const color = heatmapBackground(5, 0, 10, "light");
		assert.ok(color);
		assert.match(String(color), /^rgba\(/);
	});

	test("interpolates alpha between min and max", () => {
		const low = heatmapBackground(1, 0, 10, "light");
		const high = heatmapBackground(9, 0, 10, "light");
		assert.ok(low && high);
		const lowAlpha = Number(String(low).match(/,\s*([0-9.]+)\)$/)?.[1]);
		const highAlpha = Number(String(high).match(/,\s*([0-9.]+)\)$/)?.[1]);
		assert.ok(highAlpha > lowAlpha, `expected ${highAlpha} > ${lowAlpha}`);
	});

	test("light and dark modes use different base colors", () => {
		const light = heatmapBackground(5, 0, 10, "light");
		const dark = heatmapBackground(5, 0, 10, "dark");
		assert.ok(light && dark);
		assert.notEqual(light, dark);
	});
});

// -----------------------------------------------------------------------------
// makeStateKey
// -----------------------------------------------------------------------------

describe("makeStateKey", () => {
	test("is deterministic for same title + columns", () => {
		const k1 = makeStateKey("Monthly spend", ["a", "b", "c"]);
		const k2 = makeStateKey("Monthly spend", ["a", "b", "c"]);
		assert.equal(k1, k2);
	});

	test("differs when title differs", () => {
		const k1 = makeStateKey("Table A", ["a"]);
		const k2 = makeStateKey("Table B", ["a"]);
		assert.notEqual(k1, k2);
	});

	test("differs when columns differ", () => {
		const k1 = makeStateKey("T", ["a", "b"]);
		const k2 = makeStateKey("T", ["a", "c"]);
		assert.notEqual(k1, k2);
	});

	test("truncates very long column signatures", () => {
		const many = Array.from({ length: 100 }, (_, i) => `col_${i}`);
		const key = makeStateKey("T", many);
		// Prefix + 'T::' + up to 200 chars of signature.
		assert.ok(key.length < 260);
	});
});

// -----------------------------------------------------------------------------
// Round-trip sanity: normalize → totals → csv
// -----------------------------------------------------------------------------

describe("integration: normalize → totals → csv", () => {
	test("realistic pipeline", () => {
		const norm: NormalizedTable = normalizeTableData({
			columns: ["location_of_care", "pay_type", "claim_count"],
			rows: [
				{
					location_of_care: "OFFICE/CLINIC",
					pay_type: "MEDICARE",
					claim_count: 67288,
				},
				{
					location_of_care: "OFFICE/CLINIC",
					pay_type: "COMMERCIAL",
					claim_count: 45761,
				},
				{
					location_of_care: "HOSPITAL OP",
					pay_type: "MEDICARE",
					claim_count: 34333,
				},
			],
			title: "Care settings by pay type",
		});
		const meta = computeColumnMeta(norm.rows, norm.columns);
		assert.equal(meta.claim_count.kind, "integer");
		assert.equal(meta.claim_count.min, 34333);
		assert.equal(meta.claim_count.max, 67288);

		const totals = buildTotalsRow(norm.rows, meta, norm.columns, "sum");
		assert.ok(totals);
		assert.equal(totals?.claim_count, 147382);
		assert.equal(totals?.location_of_care, "Sum");

		const csv = buildDelimited(norm.columns, norm.rows, ",");
		assert.match(csv, /^location_of_care,pay_type,claim_count\n/);
		assert.ok(csv.includes("67288"));
	});
});
