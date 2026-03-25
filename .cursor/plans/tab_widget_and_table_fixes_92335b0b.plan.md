---
name: Tab Widget and Table Fixes
overview: Transform the 4 accordion collapsible sections into a React tab widget (fixing messy markdown rendering in the process), and wire up the existing PaginatedTable component for markdown tables.
todos:
  - id: tab-widget
    content: Create TabWidget React component with horizontal tabs, active state, and per-panel Streamdown rendering
    status: completed
  - id: preprocess-accordion
    content: Add accordion-group detection and code-fence replacement in Response useMemo + EChartsCodeBlock handler
    status: completed
  - id: shared-components
    content: Extract shared Streamdown component map used by both Response and TabWidget
    status: completed
  - id: paginated-table
    content: Wire PaginatedTable into Streamdown components prop (table override)
    status: completed
  - id: test-streaming
    content: "Verify streaming resilience: accordion CSS fallback works during partial streaming, tab widget renders once complete"
    status: completed
isProject: false
---

# Tab Widget, Markdown Cleanup, and Paginated Tables

## Current State

- **Accordion group**: The 4 collapsible sections (Show SQL, SQL Explanation, Plan Executed, Code Reference) use raw `<details>`/`<summary>` HTML inside a `<div class="accordion-group">`, styled via CSS in `[src/index.css](agent_app/e2e-chatbot-app-next/client/src/index.css)` (lines 318-360).
- **Markdown inside accordion**: Content inside `<div class="accordion-content">` contains raw markdown (bold, headers, code blocks) that is NOT rendered because `rehype-sanitize` or HTML block rules prevent markdown processing inside HTML elements. This causes the "messy" SQL Explanation text.
- **PaginatedTable**: A fully-implemented component exists at `[paginated-table.tsx](agent_app/e2e-chatbot-app-next/client/src/components/elements/paginated-table.tsx)` but is NOT wired into Streamdown's `components` prop.
- **Response pipeline**: All rendering flows through `[response.tsx](agent_app/e2e-chatbot-app-next/client/src/components/elements/response.tsx)` where `useMemo` preprocesses the text before passing to `<Streamdown>`. Custom code blocks (echarts, sql-download, json-download) are handled in `EChartsCodeBlock`.

## Plan

### 1. Create a `TabWidget` React component

New file: `src/components/elements/tab-widget.tsx`

- Accepts an array of `{ title: string, content: string }` tabs
- Renders a horizontal tab bar with styled buttons (active state, hover, transitions)
- Shows one tab panel at a time; active panel's content is rendered through `<Streamdown>` with the **same component overrides** (ECharts, sql-download, json-download, PaginatedTable) so inner markdown/code blocks render properly
- This automatically fixes Issue 1 (SQL Explanation messiness) because each tab's raw markdown content is re-processed through Streamdown

Design: modern horizontal tabs with a bottom-border indicator, smooth color transitions, dark mode support.

### 2. Preprocess accordion-group HTML in `Response`

In `[response.tsx](agent_app/e2e-chatbot-app-next/client/src/components/elements/response.tsx)`, inside the `useMemo` (line 208):

- After the existing Processing Steps logic, detect the `<div class="accordion-group">` ... `</div>` block
- Parse out each tab: extract title from `<summary>` and content from `<div class="accordion-content">`
- Serialize as JSON, base64-encode, replace the entire block with a code fence marker: ``

```accordion-tabs:base64data ``

- In `EChartsCodeBlock`, add a new branch to detect `language-accordion-tabs:*`, decode the JSON, and render `<TabWidget>`

This follows the same pattern already used for `echarts-chart`, `sql-download`, and `json-download` code fences.

Key parsing considerations:

- Handle nested `<div>` tags inside accordion-content by counting open/close tags
- Only transform when the block is complete (for streaming resilience) -- if the closing `</div>` hasn't arrived yet, leave the raw HTML for the existing CSS fallback
- Strip `<div class="accordion-content">` wrapper and preserve inner content for each tab

### 3. Wire PaginatedTable into Streamdown

In `[response.tsx](agent_app/e2e-chatbot-app-next/client/src/components/elements/response.tsx)`, line 243:

```tsx
components={{
  a: DatabricksMessageCitationStreamdownIntegration,
  code: EChartsCodeBlock,
  table: PaginatedTable,  // add this
}}
```

The existing `PaginatedTable` already uses `data-streamdown="table-wrapper"` which integrates with Streamdown's built-in copy-as-CSV controls. It paginates at 25 rows with Prev/Next buttons.

Also add `table: PaginatedTable` in the `TabWidget`'s own Streamdown instance so tables inside tab panels are also paginated.

### 4. Extract shared component map

To avoid duplicating the Streamdown component overrides between `Response` and `TabWidget`, extract a shared constant:

```tsx
export const streamdownComponents = {
  a: DatabricksMessageCitationStreamdownIntegration,
  code: EChartsCodeBlock,
  table: PaginatedTable,
};
```

Both `Response` and `TabWidget` import and use this.

### 5. Update CSS

In `[src/index.css](agent_app/e2e-chatbot-app-next/client/src/index.css)`:

- **Keep** the existing `.accordion-group` CSS as a fallback during streaming (before the block is fully received and transformed)
- No new CSS rules needed for the tab widget itself -- it will use Tailwind classes inline

## Files to Modify

- `[response.tsx](agent_app/e2e-chatbot-app-next/client/src/components/elements/response.tsx)` -- preprocessing + shared components + PaginatedTable wiring
- `[paginated-table.tsx](agent_app/e2e-chatbot-app-next/client/src/components/elements/paginated-table.tsx)` -- no changes needed (already complete)
- `[src/index.css](agent_app/e2e-chatbot-app-next/client/src/index.css)` -- keep existing CSS as streaming fallback

## Files to Create

- `src/components/elements/tab-widget.tsx` -- new React tab component

