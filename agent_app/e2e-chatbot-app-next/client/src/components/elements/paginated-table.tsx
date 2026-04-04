'use client';

import {
  Children,
  type ReactElement,
  type ReactNode,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';

const PAGE_SIZE = 10;

function getElementTag(child: ReactNode): string {
  if (!isValidElement(child)) return '';
  if (typeof child.type === 'string') return child.type;
  const displayName =
    (child.type as { displayName?: string }).displayName ??
    (child.type as { name?: string }).name ??
    '';
  return displayName.toLowerCase();
}

type TableDataRow = Record<string, unknown>;

type TableData = {
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

function extractChildren(node: ReactNode): ReactNode[] {
  if (!isValidElement(node)) return [];
  return Children.toArray((node as ReactElement).props.children);
}

function getTextContent(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(getTextContent).join(' ');
  if (!isValidElement(node)) return '';

  return Children.toArray((node as ReactElement).props.children)
    .map(getTextContent)
    .join(' ');
}

function collectRows(node: ReactNode): ReactElement[] {
  const rows: ReactElement[] = [];
  Children.forEach(node, (child) => {
    if (!isValidElement(child)) return;
    const tag = getElementTag(child);
    if (tag === 'tr') {
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
    return getElementTag(child) === 'th';
  });
}

function rowToArray(row: ReactElement): string[] {
  return Children.toArray(row.props.children)
    .filter(isValidElement)
    .map((cell) => getTextContent(cell).trim());
}

function escapeCsv(value: unknown): string {
  const text = value == null ? '' : String(value);
  return text.includes(',') || text.includes('"') || text.includes('\n')
    ? `"${text.replace(/"/g, '""')}"`
    : text;
}

function toCsv(columns: string[], rows: TableDataRow[]): string {
  if (!columns.length || !rows.length) return '';
  const header = columns.map(escapeCsv).join(',');
  const lines = rows.map((row) =>
    columns.map((column) => escapeCsv(row[column])).join(','),
  );
  return [header, ...lines].join('\n');
}

function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadSql(filename: string, sql: string) {
  const blob = new Blob([sql], { type: 'text/sql;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function PaginatedTable(
  props: Record<string, unknown> & { tableData?: TableData },
) {
  const { children, tableData } = props;

  const parsed = useMemo(() => {
    if (tableData) {
      const shippedRows = tableData.rows.length;
      const totalRows = Math.min(tableData.totalRows ?? shippedRows, shippedRows);
      const previewRowCount = tableData.previewRowCount ?? shippedRows;
      return {
        mode: 'data' as const,
        columns: tableData.columns,
        rows: tableData.rows,
        totalRows,
        previewRowCount,
        isPreview: Boolean(tableData.isPreview) || (tableData.totalRows ?? shippedRows) > shippedRows,
        filename: tableData.filename ?? 'results.csv',
        title: tableData.title ?? 'Results',
        sql: tableData.sql?.trim() || '',
        sqlFilename: tableData.sqlFilename ?? 'query.sql',
      };
    }

    const kids = Children.toArray(children as ReactNode);
    let explicitThead: ReactElement | null = null;
    let explicitTbody: ReactElement | null = null;
    const looseRows: ReactElement[] = [];

    for (const child of kids) {
      if (!isValidElement(child)) continue;
      const tag = getElementTag(child);
      if (tag === 'thead') {
        explicitThead = child as ReactElement;
      } else if (tag === 'tbody') {
        explicitTbody = child as ReactElement;
      } else if (tag === 'tr') {
        looseRows.push(child as ReactElement);
      }
    }

    let headerRow: ReactElement | null = null;
    let bodyRows: ReactElement[] = [];

    if (explicitThead || explicitTbody) {
      const theadRows = explicitThead ? collectRows(explicitThead.props.children) : [];
      const tbodyRows = explicitTbody ? collectRows(explicitTbody.props.children) : [];
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
    const totalRows = bodyRows.length;

    return {
      mode: 'nodes' as const,
      columns,
      headerRow,
      rows: bodyRows,
      totalRows,
      previewRowCount: totalRows,
      isPreview: false,
      filename: 'results.csv',
      title: 'Results',
      sql: '',
      sqlFilename: 'query.sql',
    };
  }, [children, tableData]);

  const totalRows = parsed.totalRows;
  const needsPagination = totalRows > PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  const [page, setPage] = useState(0);
  const [isExpanded, setIsExpanded] = useState(true);
  const [isSqlVisible, setIsSqlVisible] = useState(false);
  const [sqlCopied, setSqlCopied] = useState(false);

  useEffect(() => {
    setPage(0);
    setIsExpanded(true);
    setIsSqlVisible(false);
    setSqlCopied(false);
  }, [parsed.mode, parsed.filename, parsed.title, totalRows]);

  useEffect(() => {
    setPage((currentPage) => Math.min(currentPage, totalPages - 1));
  }, [totalPages]);

  const handlePrev = useCallback(() => setPage((p) => Math.max(0, p - 1)), []);
  const handleNext = useCallback(
    () => setPage((p) => Math.min(totalPages - 1, p + 1)),
    [totalPages],
  );
  const handleToggleExpanded = useCallback(() => {
    setIsExpanded((expanded) => !expanded);
  }, []);
  const handleToggleSql = useCallback(() => {
    setIsSqlVisible((visible) => !visible);
  }, []);
  const handleCopySql = useCallback(() => {
    if (!parsed.sql) return;
    navigator.clipboard.writeText(parsed.sql).then(() => {
      setSqlCopied(true);
      setTimeout(() => setSqlCopied(false), 2000);
    });
  }, [parsed.sql]);
  const handleDownloadSql = useCallback(() => {
    if (!parsed.sql) return;
    downloadSql(parsed.sqlFilename, parsed.sql);
  }, [parsed.sql, parsed.sqlFilename]);
  const handleDownload = useCallback(() => {
    const csv =
      parsed.mode === 'data'
        ? toCsv(parsed.columns, parsed.rows)
        : toCsv(parsed.columns, parsed.rows.map((row) => {
            const cells = rowToArray(row);
            return parsed.columns.reduce<TableDataRow>((acc, column, index) => {
              acc[column] = cells[index] ?? '';
              return acc;
            }, {});
          }));
    if (!csv) return;
    downloadCsv(parsed.filename, csv);
  }, [parsed]);

  const pagedRows = needsPagination
    ? parsed.rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    : parsed.rows;

  const startRow = page * PAGE_SIZE + 1;
  const endRow = Math.min((page + 1) * PAGE_SIZE, totalRows);
  const subtitle =
    totalRows === 0
      ? 'No rows'
      : parsed.isPreview
        ? `${parsed.previewRowCount} preview rows shown`
        : `${totalRows} row${totalRows === 1 ? '' : 's'} available`;

  return (
    <div
      data-streamdown="table-wrapper"
      className="my-3 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-700 dark:bg-zinc-900"
    >
      <div className="flex items-center justify-between gap-3 border-b border-zinc-200 bg-zinc-50/80 px-3 py-2.5 dark:border-zinc-700 dark:bg-zinc-800/60">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
            {parsed.title ?? 'Results'}
          </div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">
            {subtitle}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={handleToggleExpanded}
            className="rounded-md border border-transparent px-2.5 py-1 text-xs font-medium text-zinc-600 transition-colors hover:border-zinc-200 hover:bg-white dark:text-zinc-300 dark:hover:border-zinc-700 dark:hover:bg-zinc-900"
          >
            {isExpanded ? 'Collapse' : 'Expand'}
          </button>
          {parsed.sql ? (
            <button
              type="button"
              onClick={handleToggleSql}
              className="rounded-md border border-zinc-300 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              {isSqlVisible ? 'Hide SQL' : 'Show SQL'}
            </button>
          ) : null}
          <button
            type="button"
            onClick={handleDownload}
            disabled={parsed.rows.length === 0 || parsed.columns.length === 0}
            className="rounded-md border border-zinc-300 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            Download CSV
          </button>
        </div>
      </div>

      {isSqlVisible ? (
        <div className="border-b border-zinc-200 bg-zinc-50/50 dark:border-zinc-700 dark:bg-zinc-800/30">
          <div className="flex items-center justify-between gap-3 px-3 py-2">
            <div className="text-xs font-medium text-zinc-500 dark:text-zinc-400">SQL</div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopySql}
                className="rounded px-2 py-0.5 text-xs font-medium text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                {sqlCopied ? '✓ Copied' : 'Copy'}
              </button>
              <button
                type="button"
                onClick={handleDownloadSql}
                className="rounded px-2 py-0.5 text-xs font-medium text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                Download
              </button>
            </div>
          </div>
          <pre className="overflow-x-auto bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
            <code>{parsed.sql}</code>
          </pre>
        </div>
      ) : null}

      {isExpanded ? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px] leading-5">
              {parsed.mode === 'nodes' && parsed.headerRow ? (
                <thead className="bg-zinc-50/70 dark:bg-zinc-800/35">{parsed.headerRow}</thead>
              ) : null}
              {parsed.mode === 'data' && parsed.columns.length > 0 ? (
                <thead className="bg-zinc-50/70 dark:bg-zinc-800/35">
                  <tr>
                    {parsed.columns.map((column) => (
                      <th
                        key={column}
                        className="border-b border-zinc-200 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-zinc-500 dark:border-zinc-700 dark:text-zinc-400"
                      >
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
              ) : null}
              <tbody>
                {parsed.mode === 'nodes'
                  ? (pagedRows as React.ReactNode)
                  : pagedRows.map((row, rowIndex) => (
                      <tr
                        key={rowIndex}
                        className="border-b border-zinc-100 odd:bg-white even:bg-zinc-50/30 dark:border-zinc-800 dark:odd:bg-zinc-900 dark:even:bg-zinc-800/15"
                      >
                        {parsed.columns.map((column) => (
                          <td
                            key={column}
                            className="max-w-[220px] px-3 py-2.5 align-top text-zinc-700 dark:text-zinc-200"
                          >
                            <div className="truncate">{String((row as any)[column] ?? '')}</div>
                          </td>
                        ))}
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>

          {(needsPagination || parsed.rows.length > 0) && (
            <div className="flex items-center justify-between gap-2 border-t border-zinc-200 bg-zinc-50/60 px-3 py-2 text-[11px] text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800/30 dark:text-zinc-400">
              <span>
                {totalRows > 0
                  ? `Showing ${startRow}-${endRow} of ${totalRows}${parsed.isPreview ? ' preview rows' : ''}`
                  : 'No rows'}
              </span>
              {needsPagination ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handlePrev}
                    disabled={page === 0}
                    className="rounded-md border border-transparent px-2 py-0.5 transition-colors hover:border-zinc-200 hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 dark:hover:border-zinc-700 dark:hover:bg-zinc-900"
                  >
                    Prev
                  </button>
                  <span className="min-w-14 text-center">
                    {page + 1} / {totalPages}
                  </span>
                  <button
                    type="button"
                    onClick={handleNext}
                    disabled={page >= totalPages - 1}
                    className="rounded-md border border-transparent px-2 py-0.5 transition-colors hover:border-zinc-200 hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 dark:hover:border-zinc-700 dark:hover:bg-zinc-900"
                  >
                    Next
                  </button>
                </div>
              ) : (
                <span>Page 1 / 1</span>
              )}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
