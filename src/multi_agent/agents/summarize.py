"""
Result Summarize Agent Node

This module provides the result summarization node for the multi-agent system.
It wraps the ResultSummarizeAgent class and generates natural language summaries
of workflow execution results.

This is the final node that all workflow paths go through.
The node is optimized to use minimal state extraction to reduce token usage.
"""

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
        "sql_query": state.get("sql_query"),
        "sql_queries": state.get("sql_queries", []),
        "sql_query_labels": state.get("sql_query_labels", []),
        "execution_result": state.get("execution_result"),
        "execution_results": state.get("execution_results", []),
        "execution_error": state.get("execution_error"),
        "sql_synthesis_explanation": state.get("sql_synthesis_explanation"),
        "synthesis_error": state.get("synthesis_error"),
        # For logging: track original size
        "_original_message_count": len(messages)
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
            llm = ChatDatabricks(endpoint=llm_endpoint, temperature=0.1, max_tokens=5000)
            get_cached_summarize_agent._cached_agent = ResultSummarizeAgent(llm)
        except ImportError:
            # Fallback: Create a simple wrapper
            llm = ChatDatabricks(endpoint=llm_endpoint, temperature=0.1, max_tokens=5000)
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
    
    def __call__(self, state: dict) -> str:
        """Generate summary from state."""
        # Build prompt from state
        prompt = self._build_summary_prompt(state)
        
        # Stream LLM response
        print("🤖 Streaming summary generation...")
        summary = ""
        for chunk in self.llm.stream(prompt):
            if chunk.content:
                summary += chunk.content
        
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
        sql_queries = state.get('sql_queries', [])
        query_labels = state.get('sql_query_labels', [])
        execution_results = state.get('execution_results', [])
        
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
            
            MAX_PREVIEW_ROWS = 20
            MAX_JSON_CHARS = 2000
            
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
**Task:** Generate a clean, well-formatted summary. Follow these rules strictly:

**DO NOT include:**
- SQL queries (they will be added separately in a collapsible section)
- Workflow execution details or "System Approach" sections

**DO include:**
1. A concise title as a ## heading
2. A brief narrative (2-3 sentences)
3. Results as a well-formatted markdown table ($X,XXX,XXX.XX for currency, commas for counts)
4. A "### Key Insights" section with 3-5 bullet points
5. A brief outcome statement

Use markdown formatting. Keep it concise and user-friendly.
"""
        
        return prompt


@measure_node_time("summarize")
def summarize_node(state: AgentState) -> dict:
    """
    Result summarize node: text summary + chart specs + SQL download.

    1. Generates narrative summary via LLM (streams to user)
    2. For each result set, generates an echarts-chart code block via ChartGenerator
    3. Appends collapsible SQL section with download link
    """
    writer = get_stream_writer()

    print("\n" + "="*80)
    print("RESULT SUMMARIZE AGENT (Clean Output)")
    print("="*80)

    context = extract_summarize_context(state)
    writer({"type": "summary_start", "content": "Generating summary..."})

    summarize_agent = get_cached_summarize_agent()
    config = get_config()
    track_agent_model_usage("summarize", config.llm.summarize_endpoint)

    if 'original_query' not in context:
        context['original_query'] = state.get('original_query', 'N/A')

    # 1. LLM narrative summary (streams tokens to user via messages mode)
    summary = summarize_agent(context)

    # Collect execution results
    execution_results = state.get('execution_results', [])
    exec_result = state.get('execution_result', {})
    if not execution_results and exec_result:
        execution_results = [exec_result]

    # 2. Generate charts for each result set
    chart_generator = _get_chart_generator(config)
    original_query = state.get('original_query', '')

    for idx, result_item in enumerate(execution_results):
        if not result_item or not result_item.get('success'):
            continue

        columns = result_item.get('columns', [])
        data = result_item.get('result', [])
        if not columns or not data:
            continue

        if chart_generator:
            try:
                chart_spec = chart_generator.generate_chart(columns, data, original_query)
                if chart_spec:
                    chart_json = chart_generator._safe_json_dumps(chart_spec)
                    summary += f"\n\n```echarts-chart\n{chart_json}\n```\n"
                    print(f"Chart generated for result set {idx + 1} ({len(chart_json)} bytes)")
            except Exception as e:
                print(f"Chart generation failed for result set {idx + 1}: {e}")

    # 3. Append collapsible SQL download section
    sql_queries = state.get('sql_queries', [])
    single_sql = state.get('sql_query')
    if not sql_queries and single_sql:
        sql_queries = [single_sql]

    if sql_queries:
        from .summarize_agent import ResultSummarizeAgent
        summary += ResultSummarizeAgent.format_sql_download(sql_queries)

    # 4. Append error messages if any
    if state.get("synthesis_error"):
        summary += f"\n\n**SQL Synthesis Error:** {state['synthesis_error']}"
    if state.get("execution_error"):
        summary += f"\n\n**Execution Error:** {state['execution_error']}"

    print(f"Final summary: {len(summary)} chars")
    print("="*80)

    writer({"type": "summary_complete", "content": f"Summary generated ({len(summary)} chars)"})

    return {
        "final_summary": summary,
        "messages": [AIMessage(content=summary)]
    }


def _get_chart_generator(config):
    """Get or create cached ChartGenerator instance."""
    if not hasattr(_get_chart_generator, "_cached"):
        try:
            from databricks_langchain import ChatDatabricks
            from .chart_generator import ChartGenerator

            llm = ChatDatabricks(
                endpoint=config.llm.chart_endpoint,
                temperature=0.0,
                max_tokens=1000,
            )
            _get_chart_generator._cached = ChartGenerator(llm)
            print(f"ChartGenerator created (endpoint: {config.llm.chart_endpoint})")
        except Exception as e:
            print(f"ChartGenerator unavailable: {e}")
            _get_chart_generator._cached = None

    return _get_chart_generator._cached
