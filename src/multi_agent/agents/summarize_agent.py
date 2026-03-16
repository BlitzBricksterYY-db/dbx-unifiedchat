"""
Result Summarize Agent

This module provides the ResultSummarizeAgent class for generating final summaries
of workflow execution results.

The agent analyzes the entire workflow state and produces a natural language summary
of what was accomplished, whether successful or not.

OOP design for clean summarization logic.
"""

import json
from typing import Dict, Any, List
from datetime import date, datetime
from decimal import Decimal

from langchain_core.runnables import Runnable

from ..core.state import AgentState


class ResultSummarizeAgent:
    """
    Agent responsible for generating a final summary of the workflow execution.
    
    Analyzes the entire workflow state and produces a natural language summary
    of what was accomplished, whether successful or not.
    
    OOP design for clean summarization logic.
    """
    
    def __init__(self, llm: Runnable):
        """
        Initialize Result Summarize Agent.
        
        Args:
            llm: LangChain Runnable LLM instance for generating summaries
        """
        self.name = "ResultSummarize"
        self.llm = llm
    
    @staticmethod
    def _safe_json_dumps(obj: Any, indent: int = 2) -> str:
        """
        Safely serialize objects to JSON, converting dates/datetime to strings.
        
        Args:
            obj: Object to serialize
            indent: JSON indentation level
            
        Returns:
            JSON string with date/datetime objects converted to ISO format strings
        """
        def default_handler(o):
            if isinstance(o, (date, datetime)):
                return o.isoformat()
            elif isinstance(o, Decimal):
                return float(o)
            else:
                raise TypeError(f'Object of type {o.__class__.__name__} is not JSON serializable')
        
        return json.dumps(obj, indent=indent, default=default_handler)
    
    def generate_summary(self, state: AgentState) -> str:
        """
        Generate the narrative text summary only.
        
        Charts and download sections are appended by summarize_node(),
        not by this method.
        """
        summary_prompt = self._build_summary_prompt(state)
        
        print("Streaming summary generation...")
        summary = ""
        for chunk in self.llm.stream(summary_prompt):
            if chunk.content:
                summary += chunk.content
        
        summary = summary.strip()
        print(f"Summary stream complete ({len(summary)} chars)")
        return summary
    
    @staticmethod
    def format_sql_download(sql_queries: List[str]) -> str:
        """
        Generate collapsible SQL section with data URI download.
        
        SQL is always small so a data URI is safe here.
        CSV downloads are handled on the frontend (Blob URL on click).
        """
        import base64
        
        if not sql_queries:
            return ""
        
        combined_sql = "\n\n-- Query Separator --\n\n".join(sql_queries)
        encoded = base64.b64encode(combined_sql.encode("utf-8")).decode("ascii")
        
        md = "\n\n---\n\n<details><summary>Show SQL</summary>\n\n"
        md += "```sql\n"
        md += combined_sql
        md += "\n```\n\n"
        md += f'<a href="data:text/sql;base64,{encoded}" download="query.sql">Download SQL</a>\n\n'
        md += "</details>\n"
        return md
    
    def _build_summary_prompt(self, state: AgentState) -> str:
        """Build the prompt for summary generation based on state."""
        
        original_query = state.get('original_query', 'N/A')
        question_clear = state.get('question_clear', False)
        pending_clarification = state.get('pending_clarification')
        execution_plan = state.get('execution_plan')
        join_strategy = state.get('join_strategy')
        sql_query = state.get('sql_query')
        sql_explanation = state.get('sql_synthesis_explanation')
        exec_result = state.get('execution_result', {})
        synthesis_error = state.get('synthesis_error')
        execution_error = state.get('execution_error')
        
        prompt = f"""You are a result summarization agent. Generate a concise, natural language summary of what this multi-agent workflow accomplished.

**Original User Query:** {original_query}

**Workflow Execution Details:**

"""
        
        # Add clarification info
        if not question_clear and pending_clarification:
            clarification_reason = pending_clarification.get('reason', 'Query needs clarification')
            prompt += f"""**Status:** Query needs clarification
**Clarification Needed:** {clarification_reason}
**Summary:** The query was too vague or ambiguous. Requested user clarification before proceeding.
"""
        else:
            # Add planning info
            if execution_plan:
                prompt += f"""**Planning:** {execution_plan}
**Strategy:** {join_strategy or 'N/A'}

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
            
            # Add SQL synthesis info
            if sql_queries:
                if len(sql_queries) == 1:
                    # Single query (original behavior)
                    label = query_labels[0] if query_labels else ""
                    label_display = f" — {label}" if label else ""
                    prompt += f"""**SQL Generation:** ✅ Successful{label_display}
**SQL Query:** 
```sql
{sql_queries[0]}
```

"""
                else:
                    # Multiple queries
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
                
                # TOKEN PROTECTION: Sample results to prevent huge prompts
                MAX_PREVIEW_ROWS = 20
                MAX_PREVIEW_COLS = 20
                MAX_JSON_CHARS = 2000
                
                # Add execution info (single or multiple results)
                if execution_results:
                    if len(execution_results) == 1:
                        # Single result (original behavior with token protection)
                        result = execution_results[0]
                        if result.get('success'):
                            row_count = result.get('row_count', 0)
                            columns = result.get('columns', [])
                            result_data = result.get('result', [])
                            
                            # Sample rows
                            result_preview = result_data[:MAX_PREVIEW_ROWS] if len(result_data) > MAX_PREVIEW_ROWS else result_data
                            
                            # Sample columns (if result has too many columns)
                            if result_preview and len(columns) > MAX_PREVIEW_COLS:
                                sampled_cols = columns[:MAX_PREVIEW_COLS]
                                result_preview = [
                                    {k: v for k, v in row.items() if k in sampled_cols}
                                    for row in result_preview
                                ]
                                col_display = ', '.join(sampled_cols) + f'... (+{len(columns) - MAX_PREVIEW_COLS} more columns)'
                            else:
                                col_display = ', '.join(columns[:10]) + ('...' if len(columns) > 10 else '')
                            
                            # Serialize to JSON
                            result_json = self._safe_json_dumps(result_preview, indent=2)
                            
                            # Truncate JSON if too large
                            if len(result_json) > MAX_JSON_CHARS:
                                result_json = result_json[:MAX_JSON_CHARS] + f'\n... (truncated, {len(result_json) - MAX_JSON_CHARS} chars omitted)'
                            
                            prompt += f"""**Execution:** ✅ Successful
**Rows:** {row_count} rows returned{f' (showing first {MAX_PREVIEW_ROWS})' if row_count > MAX_PREVIEW_ROWS else ''}
**Columns:** {col_display}

**Result Preview:** 
{result_json}
{f'... and {row_count - MAX_PREVIEW_ROWS} more rows' if row_count > MAX_PREVIEW_ROWS else ''}
"""
                        else:
                            prompt += f"""**Execution:** ❌ Failed
**Error:** {result.get('error', 'Unknown error')}

"""
                    else:
                        # Multiple results
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
                        
                        # Add details for each result
                        for i, result in enumerate(execution_results, 1):
                            if result.get('success'):
                                row_count = result.get('row_count', 0)
                                columns = result.get('columns', [])
                                result_data = result.get('result', [])
                                
                                # Token protection per result
                                result_preview = result_data[:MAX_PREVIEW_ROWS] if len(result_data) > MAX_PREVIEW_ROWS else result_data
                                
                                if result_preview and len(columns) > MAX_PREVIEW_COLS:
                                    sampled_cols = columns[:MAX_PREVIEW_COLS]
                                    result_preview = [
                                        {k: v for k, v in row.items() if k in sampled_cols}
                                        for row in result_preview
                                    ]
                                    col_display = ', '.join(sampled_cols) + f'... (+{len(columns) - MAX_PREVIEW_COLS} more columns)'
                                else:
                                    col_display = ', '.join(columns[:10]) + ('...' if len(columns) > 10 else '')
                                
                                result_json = self._safe_json_dumps(result_preview, indent=2)
                                if len(result_json) > MAX_JSON_CHARS:
                                    result_json = result_json[:MAX_JSON_CHARS] + f'\n... (truncated)'
                                
                                prompt += f"""**Query {i} Result:**
- Rows: {row_count}{f' (showing first {MAX_PREVIEW_ROWS})' if row_count > MAX_PREVIEW_ROWS else ''}
- Columns: {col_display}
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
- Technical process descriptions (planning, SQL generation steps)

**DO include:**
1. A concise title as a ## heading summarizing the analysis
2. A brief narrative (2-3 sentences) explaining what was analyzed
3. Results as a well-formatted markdown table:
   - Format currency values as $X,XXX,XXX.XX (e.g., $5,969,134.05)
   - Format large counts with commas (e.g., 29,152)
   - Format percentages with % symbol
4. **Code Annotation for Human Readability:**
   - For columns containing raw codes (diagnosis_code, procedure_code, ICD, CPT, etc.) WITHOUT description columns:
     * Add a "{code_column}_description" column with human-readable descriptions
     * Example: "I10" → "Essential (primary) hypertension"
5. A "### Key Insights" section with 3-5 bullet points highlighting notable patterns
6. A brief outcome statement (e.g., "7 rows returned successfully")

Use markdown formatting. Keep it concise and user-friendly.
"""
        
        return prompt
    
    def __call__(self, state: AgentState) -> str:
        """Make agent callable."""
        return self.generate_summary(state)
