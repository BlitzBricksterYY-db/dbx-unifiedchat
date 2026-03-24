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


def _trace_state_snapshot(payload: Any) -> dict[str, Any]:
    """Capture the full agent state for trace inputs/outputs.

    Messages are excluded (already captured by LangChain autologging)
    and replaced with a count to avoid duplication.
    """
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}

    snapshot: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "messages":
            if isinstance(value, list):
                snapshot["message_count"] = len(value)
        else:
            snapshot[key] = value
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

