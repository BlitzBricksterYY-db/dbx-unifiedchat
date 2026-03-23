"""
LangGraph workflow construction for the multi-agent system.

This module defines the graph structure, routing logic, and workflow compilation.
"""

from functools import wraps
from typing import Any, Callable, Optional

import mlflow
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from mlflow.entities import SpanType

from ..core.state import AgentState
from ..agents.clarification import unified_intent_context_clarification_node
from ..agents.planning import planning_node
from ..agents.sql_synthesis import sql_synthesis_table_node, sql_synthesis_genie_node
from ..agents.sql_execution import sql_execution_node
from ..agents.summarize import summarize_node


def _truncate(value: Any, max_len: int = 2000) -> Any:
    """Truncate large string values so spans stay readable."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"... ({len(value)} chars total)"
    return value


def _trace_state_snapshot(payload: Any) -> dict[str, Any]:
    """Capture a rich state snapshot for trace inputs/outputs.

    Designed to surface the fields that matter most when debugging a
    chat-turn inside the MLflow trace UI.
    """
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}

    snapshot: dict[str, Any] = {}

    # Scalar flags / identifiers
    for key in (
        "original_query",
        "execution_mode",
        "force_synthesis_route",
        "question_clear",
        "is_meta_question",
        "is_irrelevant",
        "next_agent",
        "has_sql",
        "thread_id",
        "user_id",
    ):
        value = payload.get(key)
        if value is not None:
            snapshot[key] = value

    # Turn context
    current_turn = payload.get("current_turn")
    if isinstance(current_turn, dict):
        snapshot["current_turn"] = {
            k: current_turn[k]
            for k in ("turn_id", "query", "intent_type", "parent_turn_id", "context_summary")
            if k in current_turn and current_turn[k] is not None
        }

    # Intent metadata
    intent_metadata = payload.get("intent_metadata")
    if isinstance(intent_metadata, dict):
        snapshot["intent_metadata"] = {
            k: intent_metadata[k]
            for k in ("intent_type", "confidence", "reasoning", "domain", "complexity")
            if k in intent_metadata and intent_metadata[k] is not None
        }

    # Planning outputs
    plan = payload.get("plan")
    if isinstance(plan, dict):
        snapshot["plan"] = {
            k: plan[k]
            for k in ("sub_questions", "requires_join", "join_strategy", "execution_plan", "relevant_space_ids")
            if k in plan and plan[k] is not None
        }
    for key in ("sub_questions", "relevant_space_ids", "execution_plan", "join_strategy"):
        value = payload.get(key)
        if value is not None and key not in snapshot.get("plan", {}):
            snapshot[key] = value

    # SQL synthesis
    sql_query = payload.get("sql_query")
    if sql_query:
        snapshot["sql_query"] = _truncate(sql_query)
    sql_queries = payload.get("sql_queries")
    if isinstance(sql_queries, list) and sql_queries:
        snapshot["sql_queries"] = [_truncate(q) for q in sql_queries]
    sql_explanation = payload.get("sql_synthesis_explanation")
    if sql_explanation:
        snapshot["sql_synthesis_explanation"] = _truncate(sql_explanation)
    synthesis_error = payload.get("synthesis_error")
    if synthesis_error:
        snapshot["synthesis_error"] = _truncate(synthesis_error)

    # Execution results
    execution_results = payload.get("execution_results")
    if isinstance(execution_results, list) and execution_results:
        snapshot["execution_results"] = [
            {
                "status": r.get("status"),
                "success": r.get("success"),
                "row_count": r.get("row_count"),
                "columns": r.get("columns"),
                "error": _truncate(r.get("error")) if r.get("error") else None,
                "sql": _truncate(r.get("sql")) if r.get("sql") else None,
            }
            for r in execution_results
        ]
    execution_result = payload.get("execution_result")
    if isinstance(execution_result, dict) and not execution_results:
        snapshot["execution_result"] = {
            "status": execution_result.get("status"),
            "success": execution_result.get("success"),
            "row_count": execution_result.get("row_count"),
            "columns": execution_result.get("columns"),
            "error": _truncate(execution_result.get("error")) if execution_result.get("error") else None,
        }
    execution_error = payload.get("execution_error")
    if execution_error:
        snapshot["execution_error"] = _truncate(execution_error)

    # Final summary
    final_summary = payload.get("final_summary")
    if final_summary:
        snapshot["final_summary"] = _truncate(final_summary, max_len=4000)

    # Clarification
    pending_clarification = payload.get("pending_clarification")
    if isinstance(pending_clarification, dict):
        snapshot["pending_clarification"] = pending_clarification

    # Meta-answer
    meta_answer = payload.get("meta_answer")
    if meta_answer:
        snapshot["meta_answer"] = _truncate(meta_answer)

    # Messages count (don't dump full messages -- too large)
    messages = payload.get("messages")
    if isinstance(messages, list):
        snapshot["message_count"] = len(messages)

    return snapshot


def _sync_turn_metadata(state: Any, result: Any) -> None:
    """Attach turn identifiers to the active trace once intent detection resolves them."""
    current_turn = None
    if isinstance(result, dict):
        current_turn = result.get("current_turn")
    if not isinstance(current_turn, dict) and isinstance(state, dict):
        current_turn = state.get("current_turn")
    if not isinstance(current_turn, dict):
        return

    trace_metadata = {}
    if turn_id := current_turn.get("turn_id"):
        trace_metadata["chat.turn_id"] = turn_id
    if parent_turn_id := current_turn.get("parent_turn_id"):
        trace_metadata["chat.parent_turn_id"] = parent_turn_id
    if intent_type := current_turn.get("intent_type"):
        trace_metadata["chat.intent_type"] = intent_type

    if trace_metadata:
        mlflow.update_current_trace(metadata=trace_metadata)


def _with_node_trace(
    node_name: str,
    node_fn: Callable[[AgentState], Any],
    span_type: str = SpanType.AGENT,
) -> Callable[[AgentState], Any]:
    """Wrap a LangGraph node in a manual MLflow span."""

    @wraps(node_fn)
    def traced_node(state: AgentState) -> Any:
        with mlflow.start_span(
            name=node_name,
            span_type=span_type,
            attributes={"langgraph.node": node_name},
        ) as span:
            span.set_inputs(_trace_state_snapshot(state))
            try:
                result = node_fn(state)
            except Exception as exc:
                span.set_status("ERROR")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise

            span.set_outputs(_trace_state_snapshot(result))
            _sync_turn_metadata(state, result)
            return result

    return traced_node


def create_super_agent_hybrid() -> StateGraph:
    """
    Create the Hybrid Super Agent LangGraph workflow.
    
    Combines:
    - Function-based agent nodes for flexibility
    - Explicit state management for observability
    - Conditional routing for dynamic workflows
    
    Returns:
        StateGraph: Uncompiled LangGraph workflow
    """
    print("\n" + "="*80)
    print("🏗️ BUILDING HYBRID SUPER AGENT WORKFLOW")
    print("="*80)
    
    # Create the graph with explicit state
    workflow = StateGraph(AgentState)
    
    # Add nodes - SIMPLIFIED with unified node
    workflow.add_node(
        "unified_intent_context_clarification",
        _with_node_trace(
            "unified_intent_context_clarification",
            unified_intent_context_clarification_node,
            SpanType.AGENT,
        ),
    )
    workflow.add_node("planning", _with_node_trace("planning", planning_node, SpanType.AGENT))
    workflow.add_node(
        "sql_synthesis_table",
        _with_node_trace("sql_synthesis_table", sql_synthesis_table_node, SpanType.AGENT),
    )
    workflow.add_node(
        "sql_synthesis_genie",
        _with_node_trace("sql_synthesis_genie", sql_synthesis_genie_node, SpanType.AGENT),
    )
    workflow.add_node(
        "sql_execution",
        _with_node_trace("sql_execution", sql_execution_node, SpanType.TOOL),
    )
    workflow.add_node("summarize", _with_node_trace("summarize", summarize_node, SpanType.AGENT))
    
    # Define routing logic based on explicit state
    def route_after_unified(state: AgentState) -> str:
        """Route after unified node: planning or END (clarification/meta-question/irrelevant)"""
        # Check if irrelevant question - go directly to END with refusal
        if state.get("is_irrelevant", False):
            return END
        
        # Check if meta-question - go directly to END with answer
        if state.get("is_meta_question", False):
            return END
        
        # Check if question is clear - proceed to planning
        if state.get("question_clear", False):
            return "planning"
        
        # Otherwise, end for clarification
        return END
    
    def route_after_planning(state: AgentState) -> str:
        """Route after planning: determine SQL synthesis route or direct summarize"""
        next_agent = state.get("next_agent", "summarize")
        if next_agent == "sql_synthesis_table":
            return "sql_synthesis_table"
        elif next_agent == "sql_synthesis_genie":
            return "sql_synthesis_genie"
        return "summarize"
    
    def route_after_synthesis(state: AgentState) -> str:
        """Route after SQL synthesis: execution or summarize (if error)"""
        next_agent = state.get("next_agent", "summarize")
        if next_agent == "sql_execution":
            return "sql_execution"
        return "summarize"  # Summarize if synthesis error
    
    # Add edges with conditional routing
    # Entry point is unified node
    workflow.set_entry_point("unified_intent_context_clarification")
    
    # Route from unified node to planning or END (clarification)
    workflow.add_conditional_edges(
        "unified_intent_context_clarification",
        route_after_unified,
        {
            "planning": "planning",
            END: END
        }
    )
    
    workflow.add_conditional_edges(
        "planning",
        route_after_planning,
        {
            "sql_synthesis_table": "sql_synthesis_table",
            "sql_synthesis_genie": "sql_synthesis_genie",
            "summarize": "summarize"
        }
    )
    
    workflow.add_conditional_edges(
        "sql_synthesis_table",
        route_after_synthesis,
        {
            "sql_execution": "sql_execution",
            "summarize": "summarize"
        }
    )
    
    workflow.add_conditional_edges(
        "sql_synthesis_genie",
        route_after_synthesis,
        {
            "sql_execution": "sql_execution",
            "summarize": "summarize"
        }
    )
    
    # SQL execution routes conditionally: summarize, or back to synthesis on retry/sequential
    def route_after_execution(state: AgentState) -> str:
        next_agent = state.get("next_agent", "summarize")
        if next_agent in ("sql_synthesis_table", "sql_synthesis_genie"):
            return next_agent
        return "summarize"
    
    workflow.add_conditional_edges(
        "sql_execution",
        route_after_execution,
        {
            "sql_synthesis_table": "sql_synthesis_table",
            "sql_synthesis_genie": "sql_synthesis_genie",
            "summarize": "summarize",
        },
    )
    
    # Summarize is the final node before END
    workflow.add_edge("summarize", END)
    
    print("✓ Workflow nodes added:")
    print("  1. Unified Intent+Context+Clarification Node")
    print("  2. Planning Agent")
    print("  3. SQL Synthesis Agent - Table Route")
    print("  4. SQL Synthesis Agent - Genie Route")
    print("  5. SQL Execution Agent")
    print("  6. Result Summarize Agent - FINAL NODE")
    print("\n✓ Conditional routing configured")
    print("✓ All paths route to summarize node before END")
    print("\n✅ Hybrid Super Agent workflow created successfully!")
    print("="*80)
    
    return workflow


def create_agent_graph(config=None, with_checkpointer: bool = False):
    """
    Create and optionally compile the agent graph.
    
    Args:
        config: Optional configuration object (uses default if None)
        with_checkpointer: Whether to compile with checkpointer
        
    Returns:
        StateGraph or CompiledStateGraph depending on with_checkpointer
    """
    workflow = create_super_agent_hybrid()
    
    if with_checkpointer:
        # Import checkpointer only if needed
        from databricks_langchain.checkpoint import DatabricksCheckpointSaver
        from databricks_langchain.store import DatabricksStore
        from databricks.sdk import WorkspaceClient
        
        # Get Lakebase instance name from config
        if config:
            lakebase_instance = config.lakebase.instance_name
            embedding_endpoint = config.lakebase.embedding_endpoint
            embedding_dims = config.lakebase.embedding_dims
        else:
            # Use defaults
            from .config import get_config
            cfg = get_config()
            lakebase_instance = cfg.lakebase.instance_name
            embedding_endpoint = cfg.lakebase.embedding_endpoint
            embedding_dims = cfg.lakebase.embedding_dims
        
        # Create checkpointer
        w = WorkspaceClient()
        checkpointer = DatabricksCheckpointSaver(w.lakebase, database_instance_name=lakebase_instance)
        
        # Compile with checkpointer
        return workflow.compile(checkpointer=checkpointer)
    else:
        # Return uncompiled workflow
        return workflow

