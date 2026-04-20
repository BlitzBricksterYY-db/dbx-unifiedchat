"""
Result Summarize Agent Node

This module provides the result summarization node for the multi-agent system.
It wraps the ResultSummarizeAgent class and generates natural language summaries
of workflow execution results.

This is the final node that all workflow paths go through.
The node is optimized to use minimal state extraction to reduce token usage.
"""

from datetime import date, datetime
from typing import Dict, Any, List
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, SystemMessage

from ..core.state import AgentState
from ..core.config import get_config


def truncate_message_history(
    messages: List,
    max_turns: int = 5,
    keep_system: bool = True
) -> List:
    """
    Keep only recent turns + system messages.
    
    Args:
        messages: Full message history
        max_turns: Number of recent turns to keep (default 5)
        keep_system: Whether to preserve all SystemMessage instances
        
    Returns:
        Truncated message list
    """
    if not messages:
        return []
    
    # Separate system messages from conversation
    system_msgs = []
    conversation_msgs = []
    
    for msg in messages:
        if isinstance(msg, SystemMessage) and keep_system:
            system_msgs.append(msg)
        else:
            conversation_msgs.append(msg)
    
    # Keep only last N turns (each turn = HumanMessage + AIMessage pair)
    recent_msgs = conversation_msgs[-(max_turns * 2):] if len(conversation_msgs) > max_turns * 2 else conversation_msgs
    
    return system_msgs + recent_msgs


def extract_summarize_context(state: AgentState) -> dict:
    """
    Extract minimal context for result summarization.
    
    OPTIMIZED: Applies message history truncation
    """
    messages = state.get("messages", [])
    
    return {
        "messages": truncate_message_history(messages, max_turns=5),
        "original_query": state.get("original_query"),
        "question_clear": state.get("question_clear", False),
        "sql_query": state.get("sql_query"),
        "sql_queries": state.get("sql_queries") or [],
        "sql_query_labels": state.get("sql_query_labels") or [],
        "execution_result": state.get("execution_result"),
        "execution_results": state.get("execution_results") or [],
        "execution_error": state.get("execution_error"),
        "sql_synthesis_explanation": state.get("sql_synthesis_explanation"),
        "sql_synthesis_explanations": state.get("sql_synthesis_explanations") or [],
        "synthesis_error": state.get("synthesis_error"),
        # For logging: track original size
        "_original_message_count": len(messages)
    }


def _result_label(result_item: Dict[str, Any], idx: int, fallback_labels: List[str]) -> str | None:
    """Resolve the display label for a result set."""
    label = result_item.get("query_label")
    if label:
        return label
    if idx < len(fallback_labels) and fallback_labels[idx]:
        return fallback_labels[idx]
    return None


def _build_artifact_entries(state: AgentState) -> List[Dict[str, Any]]:
    """Build normalized result/sql/label entries for downstream rendering."""
    execution_results = list(state.get("execution_results") or [])
    exec_result = state.get("execution_result")
    if not execution_results and exec_result:
        execution_results = [exec_result]

    fallback_sql_queries = list(state.get("sql_queries") or [])
    if not fallback_sql_queries and state.get("sql_query"):
        fallback_sql_queries = [state["sql_query"]]
    fallback_labels = list(state.get("sql_query_labels") or [])

    entries: List[Dict[str, Any]] = []
    for idx, result_item in enumerate(execution_results):
        if not result_item:
            continue
        entries.append(
            {
                "index": idx,
                "label": _result_label(result_item, idx, fallback_labels),
                "sql": result_item.get("sql") or (
                    fallback_sql_queries[idx] if idx < len(fallback_sql_queries) else None
                ),
                "status": result_item.get("status") or (
                    "success" if result_item.get("success") else "failed"
                ),
                "sql_explanation": result_item.get("sql_explanation"),
                "skip_reason": result_item.get("skip_reason"),
                "row_grain_hint": result_item.get("row_grain_hint"),
                "result": result_item,
            }
        )
    return entries


def _is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_date_like(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _infer_workspace_fields(columns: List[str], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sample = rows[:50]
    fields: List[Dict[str, Any]] = []
    for column in columns:
        values = [row.get(column) for row in sample if row.get(column) is not None]
        lowered = column.lower()
        unique_count = len({str(value) for value in values})
        unique_ratio = (unique_count / len(values)) if values else 0.0
        if values and all(_is_numeric_like(value) for value in values):
            kind = "numeric"
        elif values and all(_is_date_like(value) for value in values):
            kind = "date"
        else:
            kind = "text"

        if kind == "date":
            role = "time"
        elif any(token in lowered for token in ("_id", " id", "uuid", "identifier", "member_id", "patient_id", "claim_id")):
            role = "id"
        elif kind == "numeric" and any(token in lowered for token in ("amount", "cost", "paid", "charge", "revenue", "sales", "spend", "allowed")):
            role = "currency"
        elif kind == "numeric" and any(token in lowered for token in ("percent", "pct", "ratio", "share", "rate")):
            role = "percent"
        elif kind == "numeric":
            role = "measure"
        elif kind == "text":
            role = "dimension"
        else:
            role = "unknown"

        if role == "currency":
            fmt = "currency"
        elif role == "percent":
            fmt = "percent"
        else:
            fmt = "number"

        fields.append(
            {
                "name": column,
                "label": column.replace("_", " ").title(),
                "kind": kind,
                "role": role,
                "format": fmt,
                "uniqueCount": unique_count,
                "uniqueRatio": round(unique_ratio, 4),
            }
        )
    return fields


def _build_visualization_workspace_payload(
    entry: Dict[str, Any],
    chart_payload: Dict[str, Any],
    preview_rows: List[Dict[str, Any]],
    full_rows: List[Dict[str, Any]],
    source_row_count: int,
    total_entries: int,
) -> Dict[str, Any]:
    from .summarize_agent import ResultSummarizeAgent
    from agent_server.result_cache import put as cache_put

    idx = entry["index"]
    label = entry.get("label") or f"Query {idx + 1}"
    result_item = entry["result"]
    columns = result_item.get("columns", [])
    workspace_id = f"query-{idx + 1}"
    description = " ".join((entry.get("sql_explanation") or "").split()) or label
    if len(description) > 160:
        description = f"{description[:157].rstrip()}..."

    data_cache_key = cache_put(columns, full_rows)

    table_payload = {
        "columns": columns,
        "rows": preview_rows,
        "totalRows": source_row_count,
        "previewRowCount": len(preview_rows),
        "isPreview": source_row_count > len(preview_rows),
        "filename": f"results_{idx + 1}.csv" if total_entries > 1 else "results.csv",
        "title": label,
        "sql": ResultSummarizeAgent.resolve_sql_download_text(entry),
        "sqlFilename": ResultSummarizeAgent.get_sql_download_filename(
            entry,
            total_entries=total_entries,
        ),
    }
    chart_payload.setdefault("meta", {})
    chart_payload["meta"].update(
        {
            "chartId": f"{workspace_id}-chart-1",
            "sourceTableId": workspace_id,
            "source": chart_payload.get("meta", {}).get("source") or "auto",
            "previewLimited": source_row_count > len(preview_rows),
            "sourceRowCount": source_row_count,
        }
    )
    chart_payload.setdefault("config", {})
    chart_payload["config"]["title"] = label
    chart_payload["config"]["description"] = None
    chart_payload["config"].setdefault("style", {})
    chart_payload["config"]["style"]["showDescription"] = False
    return {
        "workspaceId": workspace_id,
        "title": label,
        "description": description,
        "table": table_payload,
        "charts": [chart_payload],
        "fields": _infer_workspace_fields(columns, preview_rows),
        "sourceMeta": {
            "queryIndex": idx + 1,
            "label": label,
            "sqlExplanation": None,
            "rowGrainHint": entry.get("row_grain_hint"),
            "previewLimited": source_row_count > len(preview_rows),
            "totalRows": source_row_count,
            "dataCacheKey": data_cache_key,
        },
    }


def get_cached_summarize_agent():
    """
    Get or create cached ResultSummarizeAgent instance.
    Expected gain: -100ms to -300ms per request
    """
    # Module-level cache
    if not hasattr(get_cached_summarize_agent, "_cached_agent"):
        print("⚡ Creating ResultSummarizeAgent (first use)...")
        config = get_config()
        llm_endpoint = config.llm.summarize_endpoint
        
        # Create LLM instance
        try:
            from databricks_langchain import ChatDatabricks
            from .summarize_agent import ResultSummarizeAgent
            llm = ChatDatabricks(endpoint=llm_endpoint, temperature=0.1, max_tokens=10000)
            get_cached_summarize_agent._cached_agent = ResultSummarizeAgent(llm)
        except ImportError:
            # Fallback: Create a simple wrapper
            llm = ChatDatabricks(endpoint=llm_endpoint, temperature=0.1, max_tokens=10000)
            get_cached_summarize_agent._cached_agent = _SimpleSummarizeAgent(llm)
        except Exception as e:
             raise ImportError(
                f"databricks_langchain is required or Error: {e}. Install with: pip install databricks-langchain"
            )
        print("✓ ResultSummarizeAgent cached")
    else:
        print("✓ Using cached ResultSummarizeAgent")
    
    return get_cached_summarize_agent._cached_agent


def track_agent_model_usage(agent_name: str, model_endpoint: str):
    """
    Track which LLM model is used by each agent for monitoring and cost analysis.
    
    Args:
        agent_name: Name of the agent (e.g., "summarize")
        model_endpoint: LLM endpoint being used (e.g., "databricks-claude-haiku-4-5")
    """
    print(f"📊 Agent '{agent_name}' using model: {model_endpoint}")


def measure_node_time(node_name: str):
    """
    Decorator to measure node execution time.
    Expected use: Track per-node performance for optimization.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                print(f"⏱️  {node_name}: {elapsed:.3f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                print(f"⏱️  {node_name}: {elapsed:.3f}s (FAILED)")
                raise
        return wrapper
    return decorator


class _SimpleSummarizeAgent:
    """
    Simple fallback summarize agent implementation.
    
    In production, use the full ResultSummarizeAgent class.
    """
    def __init__(self, llm):
        self.name = "ResultSummarize"
        self.llm = llm
    
    def __call__(self, state: dict, writer=None) -> str:
        """Generate summary from state."""
        prompt = self._build_summary_prompt(state)
        
        print("🤖 Streaming summary generation...")
        summary = ""
        for chunk in self.llm.stream(prompt):
            if chunk.content:
                summary += chunk.content
                if writer:
                    writer({"type": "text_delta", "content": chunk.content})
        
        summary = summary.strip()
        print(f"✓ Summary stream complete ({len(summary)} chars)")
        
        return summary
    
    def _build_summary_prompt(self, state: dict) -> str:
        """Build the prompt for summary generation based on state."""
        original_query = state.get('original_query', 'N/A')
        sql_query = state.get('sql_query')
        sql_explanation = state.get('sql_synthesis_explanation')
        exec_result = state.get('execution_result', {})
        synthesis_error = state.get('synthesis_error')
        execution_error = state.get('execution_error')
        
        prompt = f"""You are a result summarization agent. Generate a concise, natural language summary of what this multi-agent workflow accomplished.

**Original User Query:** {original_query}

**Workflow Execution Details:**

"""
        
        # NEW: Check for multiple SQL queries and results
        sql_queries = state.get('sql_queries') or []
        query_labels = state.get('sql_query_labels') or []
        execution_results = state.get('execution_results') or []
        
        # Fallback to single query/result for backward compatibility
        if not sql_queries and sql_query:
            sql_queries = [sql_query]
        if not execution_results and exec_result:
            execution_results = [exec_result]
        
        if sql_queries:
            if len(sql_queries) == 1:
                label = query_labels[0] if query_labels else ""
                label_display = f" — {label}" if label else ""
                prompt += f"""**SQL Generation:** ✅ Successful{label_display}
**SQL Query:** 
```sql
{sql_queries[0]}
```

"""
            else:
                prompt += f"""**SQL Generation:** ✅ Successful ({len(sql_queries)} queries for multi-part question)

"""
                for i, query in enumerate(sql_queries, 1):
                    label = query_labels[i-1] if i <= len(query_labels) and query_labels[i-1] else ""
                    label_display = f" — {label}" if label else ""
                    prompt += f"""**SQL Query {i}{label_display}:** 
```sql
{query}
```

"""
            
            if sql_explanation:
                prompt += f"""**SQL Synthesis Explanation:** {sql_explanation[:2000]}{'...' if len(sql_explanation) > 2000 else ''}

"""
            
            MAX_PREVIEW_ROWS = 200
            MAX_JSON_CHARS = 20000
            
            if execution_results:
                if len(execution_results) == 1:
                    result = execution_results[0]
                    if result.get('success'):
                        row_count = result.get('row_count', 0)
                        columns = result.get('columns', [])
                        result_data = result.get('result', [])
                        result_preview = result_data[:MAX_PREVIEW_ROWS] if len(result_data) > MAX_PREVIEW_ROWS else result_data
                        
                        import json as _json
                        result_json = _json.dumps(result_preview, indent=2, default=str)
                        if len(result_json) > MAX_JSON_CHARS:
                            result_json = result_json[:MAX_JSON_CHARS] + f'\n... (truncated)'
                        
                        prompt += f"""**Execution:** ✅ Successful
**Rows:** {row_count} rows returned{f' (showing first {MAX_PREVIEW_ROWS})' if row_count > MAX_PREVIEW_ROWS else ''}
**Columns:** {', '.join(columns[:10])}{'...' if len(columns) > 10 else ''}

**Result Preview:** 
{result_json}
{f'... and {row_count - MAX_PREVIEW_ROWS} more rows' if row_count > MAX_PREVIEW_ROWS else ''}
"""
                    else:
                        prompt += f"""**Execution:** ❌ Failed
**Error:** {result.get('error', 'Unknown error')}

"""
                else:
                    all_successful = all(r.get('success') for r in execution_results)
                    total_rows = sum(r.get('row_count', 0) for r in execution_results if r.get('success'))
                    
                    if all_successful:
                        prompt += f"""**Execution:** ✅ All {len(execution_results)} queries executed successfully
**Total Rows Returned:** {total_rows}

"""
                    else:
                        failed_count = sum(1 for r in execution_results if not r.get('success'))
                        prompt += f"""**Execution:** ⚠️ Partial success ({len(execution_results) - failed_count} succeeded, {failed_count} failed)

"""
                    
                    for i, result in enumerate(execution_results, 1):
                        if result.get('success'):
                            row_count = result.get('row_count', 0)
                            result_data = result.get('result', [])
                            result_preview = result_data[:MAX_PREVIEW_ROWS] if len(result_data) > MAX_PREVIEW_ROWS else result_data
                            
                            import json as _json
                            result_json = _json.dumps(result_preview, indent=2, default=str)
                            if len(result_json) > MAX_JSON_CHARS:
                                result_json = result_json[:MAX_JSON_CHARS] + f'\n... (truncated)'
                            
                            prompt += f"""**Query {i} Result:**
- Rows: {row_count}
- Data: {result_json}

"""
                        else:
                            prompt += f"""**Query {i} Result:**
- Status: ❌ Failed
- Error: {result.get('error', 'Unknown error')}

"""
            elif execution_error:
                prompt += f"""**Execution:** ❌ Failed
**Error:** {execution_error}

"""
        elif synthesis_error:
            prompt += f"""**SQL Generation:** ❌ Failed
**Error:** {synthesis_error}
**Explanation:** {sql_explanation or 'N/A'}

"""
        
        prompt += """
**Task:** Generate a comprehensive summary in natural language that:
1. Describes what the user asked for
2. Explains what the system did (planning, SQL generation, execution)
3. For multi-part questions with multiple queries:
   - Explain each sub-question that was addressed
   - Use a separate subsection for each query/result pair
   - Show each SQL query in its own code block with a clear label
   - Present each query's results in a clear, readable format (preferably as a markdown table)
   - After each query's results, include a clearly labeled `Insights` subsection for that specific result before moving to the next query
   - Do not merge per-query insights together; every query/result must have its own distinct insight commentary, even if the result is small, empty, or partially successful
   - End with a separate clearly labeled `Overall Insights` or `Overall Conclusion` subsection that synthesizes patterns, contrasts, and takeaways across all queries
4. For single queries:
   - Print out SQL synthesis explanation if any SQL was generated
   - Print out the SQL query in a code block
   - Print out the result in a readable format (preferably as a markdown table)
   - Include a clearly labeled `Insights` subsection for the result
5. States the outcome (success with X rows, error, needs clarification, etc.)

Use markdown formatting for readability. Keep it clear and user-friendly.
"""
        
        return prompt


def _get_cached_chart_generator():
    """Lazily create and cache a ChartGenerator instance."""
    if not hasattr(_get_cached_chart_generator, "_instance"):
        config = get_config()
        try:
            from databricks_langchain import ChatDatabricks
            from .chart_generator import ChartGenerator
            llm = ChatDatabricks(endpoint=config.llm.chart_endpoint, temperature=0, max_tokens=1000)
            _get_cached_chart_generator._instance = ChartGenerator(llm)
            print(f"✓ ChartGenerator cached (endpoint={config.llm.chart_endpoint})")
        except Exception as e:
            print(f"⚠ ChartGenerator init failed: {e}")
            _get_cached_chart_generator._instance = None
    return _get_cached_chart_generator._instance


@measure_node_time("summarize")
def summarize_node(state: AgentState) -> dict:
    """
    Orchestrates: LLM summary -> chart generation -> SQL download -> code enrichment.
    This is the final node that all workflow paths go through.
    """
    import json as _json
    import concurrent.futures
    import contextvars

    writer = get_stream_writer()

    print("\n" + "=" * 80)
    print("RESULT SUMMARIZE NODE")
    print("=" * 80)

    # --- 0. Kick off code enrichment in background (parallel with summary) ---
    artifact_entries = _build_artifact_entries(state)
    execution_results = [entry["result"] for entry in artifact_entries]

    enrichment_futures = []
    enrichment_pool = None
    enrichable_results = [
        (idx, result_item)
        for idx, result_item in enumerate(execution_results)
        if result_item and result_item.get("success") and result_item.get("columns")
    ]
    if enrichable_results:
        try:
            from ..tools.web_search import enrich_codes
            from databricks_langchain import ChatDatabricks
            config = get_config()
            enrich_llm = ChatDatabricks(
                endpoint=config.llm.detect_code_lookup_endpoint,
                temperature=0,
                max_tokens=1500,
            )
            enrichment_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(4, len(enrichable_results))
            )
            for idx, result_item in enrichable_results:
                entry = artifact_entries[idx] if idx < len(artifact_entries) else {}
                section_title = (
                    entry.get("label")
                    if entry.get("label")
                    else f"Query {idx + 1}"
                )
                enrichment_futures.append(
                    (
                        idx,
                        section_title,
                        enrichment_pool.submit(
                            contextvars.copy_context().run,
                            enrich_codes,
                            result_item["columns"],
                            result_item["result"],
                            enrich_llm,
                            None,
                            section_title,
                            False,
                        ),
                    )
                )
            print(f"⚡ Code enrichment submitted for {len(enrichment_futures)} result set(s)")
        except Exception as e:
            print(f"⚠ Code enrichment setup failed: {e}")
            enrichment_futures = []

    # --- Sub-steps visible in Processing Steps ---
    successful_results = [r for r in execution_results if r and r.get("success")]
    total_rows = sum(r.get("row_count", len(r.get("result", []))) for r in successful_results)
    writer({
        "type": "summarize_step",
        "content": f"SUMMARIZE: Preparing context ({len(successful_results)} result set(s), {total_rows} rows)",
    })

    context = extract_summarize_context(state)

    summarize_agent = get_cached_summarize_agent()
    config = get_config()
    track_agent_model_usage("summarize", config.llm.summarize_endpoint)
    chart_gen = _get_cached_chart_generator()
    original_query = state.get("original_query", "")

    MAX_PREVIEW_ROWS = 200

    # --- 0b. Kick off chart generation in background (parallel with summary) ---
    chart_futures = {}
    chart_pool = None
    chartable_entries = [
        entry
        for entry in artifact_entries
        if entry.get("result")
        and entry["result"].get("success")
        and entry["result"].get("columns")
        and entry["result"].get("result")
    ]
    if chart_gen and chartable_entries:
        try:
            chart_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(4, len(chartable_entries))
            )
            for entry in chartable_entries:
                result_item = entry["result"]
                chart_futures[entry["index"]] = (
                    entry,
                    chart_pool.submit(
                        contextvars.copy_context().run,
                        chart_gen.generate_chart,
                        result_item.get("columns", []),
                        result_item.get("result", []),
                        original_query,
                        {
                            "label": entry.get("label"),
                            "sql_query": entry.get("sql"),
                            "sql_explanation": entry.get("sql_explanation"),
                            "row_grain_hint": entry.get("row_grain_hint"),
                        },
                    ),
                )
            print(f"⚡ Chart generation submitted for {len(chart_futures)} result set(s)")
        except Exception as e:
            print(f"⚠ Chart generation setup failed: {e}")
            chart_futures = {}
            if chart_pool:
                chart_pool.shutdown(wait=False)
                chart_pool = None

    writer({
        "type": "summarize_step",
        "content": f"SUMMARIZE: Streaming summary (model: {config.llm.summarize_endpoint})...",
    })
    writer({"type": "summary_start", "content": "Generating summary..."})

    # --- 1. LLM text summary (streams to user via writer deltas) ---
    if hasattr(summarize_agent, "generate_summary"):
        summary = summarize_agent.generate_summary(context, writer=writer)
    else:
        summary = summarize_agent(context, writer=writer)

    # --- 2. Collect chart generation result and emit a visualization workspace per table ---
    for entry in artifact_entries:
        idx = entry["index"]
        result_item = entry["result"]
        if not result_item or not result_item.get("success"):
            continue
        columns = result_item.get("columns", [])
        data = result_item.get("result", [])
        if not columns or not data:
            continue

        future_entry = chart_futures.get(idx)
        if not future_entry:
            continue
        _future_meta, future = future_entry

        try:
            payload = future.result(timeout=30)
            if not payload:
                print(
                    "⚠ Chart generation returned no payload for result "
                    f"{idx} ({entry.get('label') or f'Query {idx + 1}'}) "
                    f"columns={columns}"
                )
                continue

            preview_rows = data[:MAX_PREVIEW_ROWS]
            source_row_count = result_item.get("row_count") or len(data)
            workspace_payload = _build_visualization_workspace_payload(
                entry=entry,
                chart_payload=payload,
                preview_rows=preview_rows,
                full_rows=data,
                source_row_count=source_row_count,
                total_entries=len(artifact_entries),
            )
            workspace_json = _json.dumps(workspace_payload, default=str)
            workspace_block = f"\n\n```viz-workspace\n{workspace_json}\n```\n"
            summary += workspace_block
            writer({"type": "text_delta", "content": workspace_block})
            print(f"✓ Visualization workspace inserted for result {idx} ({len(workspace_json)} bytes)")
        except Exception as e:
            print(
                "⚠ Chart generation failed for result "
                f"{idx} ({entry.get('label') or f'Query {idx + 1}'}) "
                f"columns={columns}: {e}"
            )
    if chart_pool:
        chart_pool.shutdown(wait=False)

    # --- 3. SQL download / explanation / plan (collapsible, streamed as delta) ---
    from .summarize_agent import ResultSummarizeAgent
    plan = state.get("plan")

    has_accordion = False
    if artifact_entries or plan or enrichment_futures or any(
        entry.get("sql_explanation") or entry.get("skip_reason") for entry in artifact_entries
    ):
        writer({"type": "text_delta", "content": "\n\n<div class=\"accordion-group\">\n\n"})
        has_accordion = True

    if artifact_entries:
        sql_block = ResultSummarizeAgent.format_sql_download(
            artifact_entries,
            total_entries=len(artifact_entries),
        )
        summary += sql_block
        writer({"type": "text_delta", "content": sql_block})

    # --- 3b. SQL Explanation (collapsible, streamed as delta) ---
    if any(entry.get("sql_explanation") or entry.get("skip_reason") for entry in artifact_entries):
        explanation_block = ResultSummarizeAgent.format_sql_explanation(
            artifact_entries=artifact_entries,
        )
        summary += explanation_block
        writer({"type": "text_delta", "content": explanation_block})

    # --- 3c. Plan Executed (collapsible, streamed as delta) ---
    if plan:
        plan_block = ResultSummarizeAgent.format_plan_executed(plan)
        summary += plan_block
        writer({"type": "text_delta", "content": plan_block})

    # --- 4. Collect code enrichment result (likely already done by now) ---
    if enrichment_futures:
        try:
            sections = []
            for _idx, _section_title, future in enrichment_futures:
                enriched_ref = future.result(timeout=20)
                if enriched_ref:
                    sections.append(enriched_ref.strip())
            if sections:
                combined_ref = (
                    "\n\n<details name=\"sql-accordion\"><summary>Code Reference</summary>\n\n"
                    "<div class=\"accordion-content\">\n\n"
                    + "\n\n".join(sections)
                    + "\n\n</div>\n</details>\n"
                )
                summary += combined_ref
                writer({"type": "text_delta", "content": combined_ref})
                print(f"✓ Code reference appended ({len(sections)} section(s))")
        except Exception as e:
            print(f"⚠ Code enrichment skipped: {e}")
        finally:
            if enrichment_pool:
                enrichment_pool.shutdown(wait=False)

    if has_accordion:
        writer({"type": "text_delta", "content": "\n\n</div>\n"})

    writer({"type": "summary_complete", "content": f"Summary generated ({len(summary)} chars)"})

    print(f"✓ final_summary: {len(summary)} chars")
    print("=" * 80)

    return {
        "final_summary": summary,
        "messages": [AIMessage(content=summary)],
    }
