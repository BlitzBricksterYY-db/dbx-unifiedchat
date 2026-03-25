---
name: sequential output fixes
overview: Fix sequential-mode result assembly so the final answer, charts, downloadable tables, SQL accordion, and code-reference sections all reflect the same set of per-step artifacts, then tighten summarization/enrichment rules to avoid incorrect claims from repeated or truncated result previews.
todos:
  - id: seq-metadata
    content: Persist per-step SQL and label metadata with sequential execution results
    status: pending
  - id: artifact-assembly
    content: Make summarize assembly derive SQL/titles/enrichment sections from accumulated result metadata
    status: pending
  - id: summary-prompt
    content: Rewrite multi-result summary prompt to require per-result subsections and safer aggregation language
    status: pending
  - id: code-enrichment-heuristics
    content: Filter out aggregate metric columns before code lookup/enrichment
    status: pending
  - id: validate-sequential-output
    content: Re-run the reported scenario and add/update focused tests for sequential artifact consistency
    status: pending
isProject: false
---

# Sequential Output Fixes

## Root Issues

- Sequential execution accumulates completed result sets in `preserved_results` / `execution_results`, but sequential SQL text and labels are overwritten on each synthesis step instead of being accumulated. This is why the final accordion can show only the last SQL query while charts/tables correctly show all result sets.
- The summarizer prompt in `[agent_app/agent_server/multi_agent/agents/summarize_agent.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/summarize_agent.py)` explicitly asks for a single markdown table and does not require one section per result set, so the narrative can disagree with the appended artifacts.
- The final assembly in `[agent_app/agent_server/multi_agent/agents/summarize.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/summarize.py)` titles charts, tables, and code-reference sections from the current `sql_query_labels`, which are stale in sequential mode.
- Code enrichment in `[agent_app/agent_server/multi_agent/tools/web_search.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/tools/web_search.py)` is too permissive and can classify metric/count columns like `cpt_procedure_count` as code columns, producing bogus “Code Reference” tables.
- The summarizer is allowed to infer cohort counts from repeated enrollment/benefit rows, which leads to incorrect statements like payer totals summing to more than the 10 members.

## Implementation Approach

- Add stable per-step artifact metadata for sequential mode in `[agent_app/agent_server/multi_agent/core/state.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/core/state.py)` and the sequential execution/synthesis path.
- On each sequential step, persist the executed SQL, label, and query index alongside the result object in `[agent_app/agent_server/multi_agent/agents/sql_execution.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/sql_execution.py)` instead of relying on `sql_queries` / `sql_query_labels` remaining accurate after later steps.
- Update `[agent_app/agent_server/multi_agent/agents/summarize.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/summarize.py)` to derive chart titles, downloadable table titles, SQL accordion contents, and code-reference section labels from the accumulated per-result metadata rather than the latest synthesis state.
- Rewrite the prompt contract in `[agent_app/agent_server/multi_agent/agents/summarize_agent.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/summarize_agent.py)` so multi-result/sequential runs render one subsection per result set, avoid claiming a specific number of tables/charts unless explicitly provided, and avoid distinct-member claims from repeated coverage rows.
- Tighten code-column detection in `[agent_app/agent_server/multi_agent/tools/web_search.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/tools/web_search.py)` with simple heuristics before the LLM call: skip columns with `count`, `total`, `avg`, `amount`, `cost`, `rows`, `days`, `units`, or obviously aggregated numeric metrics; only enrich probable identifier columns.

## Concrete Fix Targets

- `[agent_app/agent_server/multi_agent/agents/sql_synthesis.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/sql_synthesis.py)`
  - Preserve sequential SQL/query-label history instead of replacing it each step, or stop using these top-level fields for sequential rendering.
- `[agent_app/agent_server/multi_agent/agents/sql_execution.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/sql_execution.py)`
  - Attach `query_label` and executed SQL metadata directly to each preserved result.
- `[agent_app/agent_server/multi_agent/agents/summarize.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/summarize.py)`
  - Build all appended artifact blocks from accumulated result metadata.
  - Pass more explicit multi-result context into the summarizer.
- `[agent_app/agent_server/multi_agent/agents/summarize_agent.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/agents/summarize_agent.py)`
  - Change the prompt from “one markdown table” to “one subsection per query/result set”.
  - Add guardrails for repeated rows, truncated previews, and unsupported cohort-level inferences.
- `[agent_app/agent_server/multi_agent/tools/web_search.py](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/agent_server/multi_agent/tools/web_search.py)`
  - Prevent enrichment of aggregated metric columns.

## Validation

- Reproduce the provided sequential example and verify:
- `Show SQL` contains all sequential queries, not just the last one.
- Result subsections, chart count, downloadable table count, and titles all line up 1:1.
- The summary no longer claims the wrong number of tables/charts.
- Coverage/member-count claims do not overcount repeated enrollment rows.
- “Code Reference” no longer generates nonsense CPT/HCPCS descriptions for count columns.
- Add/update targeted tests around sequential rendering in the Next.js app and/or backend summarization path where coverage already exists, especially around accordion/table titles and multi-step sequential output.

