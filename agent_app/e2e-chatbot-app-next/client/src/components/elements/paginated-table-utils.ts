import {
	Children,
	type ReactElement,
	type ReactNode,
	isValidElement,
} from "react";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

export type TableDataRow = Record<string, unknown>;

export type TableData = {
	columns: string[];
	rows: TableDataRow[];
	totalRows?: number;
	previewRowCount?: number;
	isPreview?: boolean;
	filename?: string;
	title?: string;
	sql?: string;
	sqlFilename?: string;
};

export type NormalizedTable = {
	columns: string[];
	rows: TableDataRow[];
	totalRows: number;
	previewRowCount: number;
	isPreview: boolean;
	filename: string;
	title: string;
	sql: string;
	sqlFilename: string;
};

export type ColumnKind =
	| "integer"
	| "currency"
	| "percent"
	| "number"
	| "date"
	| "text";

export type ColumnMeta = {
	kind: ColumnKind;
	min?: number;
	max?: number;
	currencySymbol?: string;
};

export type TotalsMode = "none" | "sum" | "avg" | "min" | "max";

// -----------------------------------------------------------------------------
// React-node table parsing (markdown path)
// -----------------------------------------------------------------------------

function getElementTag(child: ReactNode): string {
	if (!isValidElement(child)) return "";
	if (typeof child.type === "string") return child.type;
	const displayName =
		(child.type as { displayName?: string }).displayName ??
		(child.type as { name?: string }).name ??
		"";
	return displayName.toLowerCase();
}

function getTextContent(node: ReactNode): string {
	if (node == null || typeof node === "boolean") return "";
	if (typeof node === "string" || typeof node === "number") return String(node);
	if (Array.isArray(node)) return node.map(getTextContent).join(" ");
	if (!isValidElement(node)) return "";
	return Children.toArray((node as ReactElement).props.children)
		.map(getTextContent)
		.join(" ");
}

function collectRows(node: ReactNode): ReactElement[] {
	const rows: ReactElement[] = [];
	Children.forEach(node, (child) => {
		if (!isValidElement(child)) return;
		const tag = getElementTag(child);
		if (tag === "tr") {
			rows.push(child as ReactElement);
			return;
		}
		rows.push(...collectRows((child as ReactElement).props.children));
	});
	return rows;
}

function rowHasHeaderCells(row: ReactElement): boolean {
	return Children.toArray(row.props.children).some((child) => {
		if (!isValidElement(child)) return false;
		return getElementTag(child) === "th";
	});
}

function rowToArray(row: ReactElement): string[] {
	return Children.toArray(row.props.children)
		.filter(isValidElement)
		.map((cell) => getTextContent(cell).trim());
}

export function parseNodesTable(children: ReactNode): NormalizedTable {
	const kids = Children.toArray(children);
	let explicitThead: ReactElement | null = null;
	let explicitTbody: ReactElement | null = null;
	const looseRows: ReactElement[] = [];

	for (const child of kids) {
		if (!isValidElement(child)) continue;
		const tag = getElementTag(child);
		if (tag === "thead") explicitThead = child as ReactElement;
		else if (tag === "tbody") explicitTbody = child as ReactElement;
		else if (tag === "tr") looseRows.push(child as ReactElement);
	}

	let headerRow: ReactElement | null = null;
	let bodyRows: ReactElement[] = [];

	if (explicitThead || explicitTbody) {
		const theadRows = explicitThead
			? collectRows(explicitThead.props.children)
			: [];
		const tbodyRows = explicitTbody
			? collectRows(explicitTbody.props.children)
			: [];
		headerRow = theadRows[0] ?? null;
		bodyRows = tbodyRows.length > 0 ? tbodyRows : theadRows.slice(1);
		if (!headerRow && bodyRows.length > 0 && rowHasHeaderCells(bodyRows[0])) {
			headerRow = bodyRows[0];
			bodyRows = bodyRows.slice(1);
		}
	} else {
		const rows = looseRows.length > 0 ? looseRows : collectRows(kids);
		if (rows.length > 0 && rowHasHeaderCells(rows[0])) {
			headerRow = rows[0];
			bodyRows = rows.slice(1);
		} else {
			bodyRows = rows;
		}
	}

	const columns = headerRow ? rowToArray(headerRow) : [];
	const rows: TableDataRow[] = bodyRows.map((row) => {
		const cells = rowToArray(row);
		return columns.reduce<TableDataRow>((acc, column, index) => {
			acc[column] = cells[index] ?? "";
			return acc;
		}, {});
	});

	return {
		columns,
		rows,
		totalRows: rows.length,
		previewRowCount: rows.length,
		isPreview: false,
		filename: "results.csv",
		title: "Results",
		sql: "",
		sqlFilename: "query.sql",
	};
}

export function normalizeTableData(tableData: TableData): NormalizedTable {
	const shippedRows = tableData.rows.length;
	const totalRows = Math.min(tableData.totalRows ?? shippedRows, shippedRows);
	const previewRowCount = tableData.previewRowCount ?? shippedRows;
	return {
		columns: tableData.columns,
		rows: tableData.rows,
		totalRows,
		previewRowCount,
		isPreview:
			Boolean(tableData.isPreview) ||
			(tableData.totalRows ?? shippedRows) > shippedRows,
		filename: tableData.filename ?? "results.csv",
		title: tableData.title ?? "Results",
		sql: tableData.sql?.trim() || "",
		sqlFilename: tableData.sqlFilename ?? "query.sql",
	};
}

// -----------------------------------------------------------------------------
// Column type inference
// -----------------------------------------------------------------------------

// Column-name hints. We normalize underscores to spaces before matching so
// that snake_case columns like `paid_amount` behave as expected with \b.
const CURRENCY_REGEX =
	/\b(amount|price|cost|revenue|charge|paid|allowed|spend|salary|wage|fee|premium|usd)\b/i;
const PERCENT_REGEX = /\b(pct|percent|percentage|rate)\b/i;
const INTEGER_REGEX = /\b(count|total|num|number|qty|quantity|id)\b/i;
const DATE_COLUMN_REGEX = /(date|time|timestamp|dob|\bat\b|\bon\b)/i;
const ISO_DATE_REGEX =
	/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/;
const NUMERIC_STRING_REGEX = /^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$/;
const CURRENCY_PREFIX_REGEX = /^(\$|€|£|¥|₹)\s?-?\d/;

function parseNumberLike(value: unknown): number | null {
	if (typeof value === "number") return Number.isFinite(value) ? value : null;
	if (typeof value !== "string") return null;
	let trimmed = value.trim();
	if (trimmed === "") return null;
	// Strip leading currency symbol.
	trimmed = trimmed.replace(/^[$€£¥₹]\s?/, "");
	// Percent suffix.
	const isPercent = trimmed.endsWith("%");
	if (isPercent) trimmed = trimmed.slice(0, -1).trim();
	if (!NUMERIC_STRING_REGEX.test(trimmed)) return null;
	const num = Number(trimmed.replace(/,/g, ""));
	if (!Number.isFinite(num)) return null;
	return isPercent ? num / 100 : num;
}

function parseDateLike(value: unknown): Date | null {
	if (value instanceof Date) {
		return Number.isFinite(value.getTime()) ? value : null;
	}
	if (typeof value !== "string") return null;
	const trimmed = value.trim();
	if (!ISO_DATE_REGEX.test(trimmed)) return null;
	const parsed = new Date(trimmed);
	return Number.isFinite(parsed.getTime()) ? parsed : null;
}

export function inferColumnKind(
	column: string,
	rows: TableDataRow[],
): ColumnKind {
	// Normalize snake_case → space-separated so `\b` word boundaries work.
	const normalized = column.replace(/[_-]+/g, " ");

	// Column-name hints (strong signal).
	if (DATE_COLUMN_REGEX.test(normalized)) {
		// Verify at least one value parses as date.
		for (const row of rows.slice(0, 25)) {
			if (parseDateLike(row[column]) !== null) return "date";
		}
	}
	if (PERCENT_REGEX.test(normalized)) return "percent";
	if (CURRENCY_REGEX.test(normalized)) return "currency";

	// Sample values.
	let numericSeen = 0;
	let integerSeen = 0;
	let dateSeen = 0;
	let currencySeen = 0;
	let percentSeen = 0;
	let nonEmptySeen = 0;
	for (const row of rows) {
		const value = row[column];
		if (value == null || value === "") continue;
		nonEmptySeen += 1;
		// Currency prefix ($1,234.56).
		if (typeof value === "string" && CURRENCY_PREFIX_REGEX.test(value)) {
			currencySeen += 1;
		}
		// Percent suffix (12.3%).
		if (typeof value === "string" && value.trim().endsWith("%")) {
			const num = parseNumberLike(value);
			if (num !== null) percentSeen += 1;
		}
		const asNumber = parseNumberLike(value);
		if (asNumber !== null) {
			numericSeen += 1;
			if (Number.isInteger(asNumber)) integerSeen += 1;
			continue;
		}
		if (parseDateLike(value) !== null) {
			dateSeen += 1;
			continue;
		}
		// Any non-numeric, non-date → definitely text.
		if (nonEmptySeen >= 5 && numericSeen === 0 && dateSeen === 0) {
			return "text";
		}
		if (nonEmptySeen >= 50) break;
	}

	if (nonEmptySeen === 0) return "text";

	const numericRatio = numericSeen / nonEmptySeen;
	const dateRatio = dateSeen / nonEmptySeen;

	if (currencySeen > 0 && currencySeen / nonEmptySeen > 0.4) return "currency";
	if (percentSeen > 0 && percentSeen / nonEmptySeen > 0.4) return "percent";
	if (dateRatio > 0.6) return "date";
	if (numericRatio > 0.8) {
		if (integerSeen === numericSeen && INTEGER_REGEX.test(normalized))
			return "integer";
		if (integerSeen === numericSeen) return "integer";
		return "number";
	}
	return "text";
}

export function coerceValue(
	value: unknown,
	kind: ColumnKind,
): number | Date | string | null {
	if (value == null || value === "") return null;
	if (kind === "date") return parseDateLike(value);
	if (kind === "text") return typeof value === "string" ? value : String(value);
	return parseNumberLike(value);
}

// -----------------------------------------------------------------------------
// Column metadata (min/max for heatmap)
// -----------------------------------------------------------------------------

export function computeColumnMeta(
	rows: TableDataRow[],
	columns: string[],
): Record<string, ColumnMeta> {
	const meta: Record<string, ColumnMeta> = {};
	for (const column of columns) {
		const kind = inferColumnKind(column, rows);
		let min = Number.POSITIVE_INFINITY;
		let max = Number.NEGATIVE_INFINITY;
		if (kind !== "text") {
			for (const row of rows) {
				const value = coerceValue(row[column], kind);
				if (value == null) continue;
				const numeric =
					typeof value === "number"
						? value
						: value instanceof Date
							? value.getTime()
							: Number.NaN;
				if (!Number.isFinite(numeric)) continue;
				if (numeric < min) min = numeric;
				if (numeric > max) max = numeric;
			}
		}
		meta[column] = {
			kind,
			min: Number.isFinite(min) ? min : undefined,
			max: Number.isFinite(max) ? max : undefined,
		};
	}
	return meta;
}

// -----------------------------------------------------------------------------
// Formatting
// -----------------------------------------------------------------------------

const INTEGER_FORMATTER = new Intl.NumberFormat(undefined, {
	maximumFractionDigits: 0,
});
const NUMBER_FORMATTER = new Intl.NumberFormat(undefined, {
	maximumFractionDigits: 4,
});
const CURRENCY_FORMATTER = new Intl.NumberFormat(undefined, {
	style: "currency",
	currency: "USD",
	maximumFractionDigits: 2,
});
const PERCENT_FORMATTER = new Intl.NumberFormat(undefined, {
	style: "percent",
	maximumFractionDigits: 2,
});
// Date-only strings ("2024-01-15") parse as UTC midnight, so we format in UTC
// to avoid showing yesterday's date for users in western timezones.
const DATE_FORMATTER_UTC = new Intl.DateTimeFormat(undefined, {
	year: "numeric",
	month: "short",
	day: "2-digit",
	timeZone: "UTC",
});
// Timestamps with a time portion are rendered in the viewer's local TZ.
const DATETIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
	year: "numeric",
	month: "short",
	day: "2-digit",
	hour: "2-digit",
	minute: "2-digit",
});

export function formatValueByKind(value: unknown, kind: ColumnKind): string {
	const coerced = coerceValue(value, kind);
	if (coerced == null) return "";
	switch (kind) {
		case "integer":
			return INTEGER_FORMATTER.format(coerced as number);
		case "number":
			return NUMBER_FORMATTER.format(coerced as number);
		case "currency":
			return CURRENCY_FORMATTER.format(coerced as number);
		case "percent":
			return PERCENT_FORMATTER.format(coerced as number);
		case "date": {
			const d = coerced as Date;
			// A date-only ISO string parses as UTC midnight. Heuristic: if UTC
			// hours/minutes/seconds are all zero, treat it as a pure date and
			// format in UTC; otherwise render the real timestamp in local time.
			const isDateOnly =
				d.getUTCHours() === 0 &&
				d.getUTCMinutes() === 0 &&
				d.getUTCSeconds() === 0;
			if (isDateOnly) {
				return DATE_FORMATTER_UTC.format(d);
			}
			return DATETIME_FORMATTER.format(d);
		}
		default:
			return String(coerced);
	}
}

export const COLUMN_KIND_LABELS: Record<ColumnKind, string> = {
	integer: "Integer",
	currency: "Currency",
	percent: "Percent",
	number: "Number",
	date: "Date",
	text: "Text",
};

// -----------------------------------------------------------------------------
// Totals row
// -----------------------------------------------------------------------------

function aggregate(values: number[], mode: TotalsMode): number | null {
	if (values.length === 0) return null;
	switch (mode) {
		case "sum":
			return values.reduce((a, b) => a + b, 0);
		case "avg":
			return values.reduce((a, b) => a + b, 0) / values.length;
		case "min":
			return Math.min(...values);
		case "max":
			return Math.max(...values);
		default:
			return null;
	}
}

export function buildTotalsRow(
	rows: TableDataRow[],
	meta: Record<string, ColumnMeta>,
	columns: string[],
	mode: TotalsMode,
): TableDataRow | null {
	if (mode === "none" || columns.length === 0) return null;
	const row: TableDataRow = {};
	let hasAnyAggregate = false;
	let labelColumn: string | null = null;
	for (const column of columns) {
		const kind = meta[column]?.kind ?? "text";
		if (kind === "text" || kind === "date") {
			if (!labelColumn) labelColumn = column;
			row[column] = "";
			continue;
		}
		const values: number[] = [];
		for (const r of rows) {
			const coerced = coerceValue(r[column], kind);
			if (typeof coerced === "number" && Number.isFinite(coerced)) {
				values.push(coerced);
			}
		}
		const agg = aggregate(values, mode);
		if (agg === null) {
			row[column] = "";
			continue;
		}
		row[column] = kind === "integer" && mode !== "avg" ? Math.round(agg) : agg;
		hasAnyAggregate = true;
	}
	if (!hasAnyAggregate) return null;
	const label = `${mode.charAt(0).toUpperCase()}${mode.slice(1)}`;
	if (labelColumn) row[labelColumn] = label;
	// Mark as totals row so cell renderer can style.
	(row as TableDataRow & { __totals: boolean }).__totals = true;
	return row;
}

// -----------------------------------------------------------------------------
// Export helpers
// -----------------------------------------------------------------------------

function escapeCsvField(value: unknown, separator: string): string {
	const text = value == null ? "" : String(value);
	if (
		text.includes(separator) ||
		text.includes('"') ||
		text.includes("\n") ||
		text.includes("\r")
	) {
		return `"${text.replace(/"/g, '""')}"`;
	}
	return text;
}

export function buildDelimited(
	columns: string[],
	rows: TableDataRow[],
	separator: string,
	includeHeader = true,
): string {
	if (columns.length === 0) return "";
	const lines: string[] = [];
	if (includeHeader) {
		lines.push(
			columns.map((c) => escapeCsvField(c, separator)).join(separator),
		);
	}
	for (const row of rows) {
		lines.push(
			columns
				.map((column) => escapeCsvField(row[column], separator))
				.join(separator),
		);
	}
	return lines.join("\n");
}

export function downloadBlob(
	filename: string,
	contents: string,
	mimeType: string,
) {
	const blob = new Blob([contents], { type: mimeType });
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement("a");
	anchor.href = url;
	anchor.download = filename;
	anchor.click();
	URL.revokeObjectURL(url);
}

// -----------------------------------------------------------------------------
// Heatmap color helper (min→max interpolation)
// -----------------------------------------------------------------------------

export function heatmapBackground(
	value: number,
	min: number,
	max: number,
	themeMode: "light" | "dark",
): string | undefined {
	if (
		!Number.isFinite(value) ||
		!Number.isFinite(min) ||
		!Number.isFinite(max)
	) {
		return undefined;
	}
	if (max === min) return undefined;
	const ratio = Math.max(0, Math.min(1, (value - min) / (max - min)));
	// Use accent (blue) scaled by intensity, with theme-aware alpha.
	const alpha =
		themeMode === "dark"
			? (0.05 + ratio * 0.35).toFixed(3)
			: (0.04 + ratio * 0.3).toFixed(3);
	// zinc-aligned blue-ish tone that works in both modes.
	return themeMode === "dark"
		? `rgba(96, 165, 250, ${alpha})`
		: `rgba(59, 130, 246, ${alpha})`;
}

// -----------------------------------------------------------------------------
// Persistence
// -----------------------------------------------------------------------------

const STATE_KEY_PREFIX = "paginated-table:state:";

export type PersistedTableState = {
	columnState?: unknown;
	filterModel?: unknown;
	density?: "compact" | "comfortable" | "spacious";
	heatmap?: boolean;
	showFilters?: boolean;
	totalsMode?: TotalsMode;
};

export function makeStateKey(title: string, columns: string[]): string {
	// Include a short column signature so state doesn't carry across unrelated
	// tables that happen to share a title.
	const sig = columns.join("|").slice(0, 200);
	return `${STATE_KEY_PREFIX}${title}::${sig}`;
}

export function loadTableState(key: string): PersistedTableState | null {
	try {
		const raw = localStorage.getItem(key);
		if (!raw) return null;
		return JSON.parse(raw) as PersistedTableState;
	} catch {
		return null;
	}
}

export function saveTableState(key: string, state: PersistedTableState): void {
	try {
		localStorage.setItem(key, JSON.stringify(state));
	} catch {
		// Quota or serialization error — ignore silently.
	}
}

export function clearTableState(key: string): void {
	try {
		localStorage.removeItem(key);
	} catch {
		// ignore
	}
}
