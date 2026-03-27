"""
LangGraph workflow construction for the multi-agent system.

This module defines the graph structure, routing logic, and workflow compilation.
"""

from functools import wraps
from typing import Any, Callable, Optional, Union

import mlflow
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from mlflow.entities import SpanType

from ..core.state import AgentState, GraphInput
from ..agents.clarification import ClarificationAgent
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


def create_super_agent_hybrid(config=None) -> StateGraph:
    """
    Create the Hybrid Super Agent LangGraph workflow.

    Args:
        config: Optional configuration object (uses default if None)

    Returns:
        StateGraph: Uncompiled LangGraph workflow
    """
    if config is None:
        from .config import get_config
        config = get_config()

    table_name = (
        f"{config.unity_catalog.catalog_name}"
        f".{config.unity_catalog.schema_name}"
        f".enriched_genie_docs_chunks"
    )
    clarification_agent = ClarificationAgent(
        llm_endpoint=config.llm.clarification_endpoint,
        table_name=table_name,
    )

    print("\n" + "="*80)
    print("BUILDING HYBRID SUPER AGENT WORKFLOW")
    print("="*80)

    workflow = StateGraph(AgentState, input=GraphInput)

    workflow.add_node(
        "unified_intent_context_clarification",
        clarification_agent.subgraph,
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

    def route_after_unified(state: AgentState) -> str:
        """Route after unified node: planning or END (meta-question/irrelevant).

        Clarification no longer routes to END here -- unclear queries pause inside
        the subgraph via interrupt() and resume directly into planning.
        """
        if state.get("is_irrelevant", False):
            return END
        if state.get("is_meta_question", False):
            return END
        return "planning"

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
        return "summarize"

    workflow.set_entry_point("unified_intent_context_clarification")

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

    workflow.add_edge("summarize", END)

    print("Workflow nodes added:")
    print("  1. Unified Intent+Context+Clarification (subgraph)")
    print("  2. Planning Agent")
    print("  3. SQL Synthesis Agent - Table Route")
    print("  4. SQL Synthesis Agent - Genie Route")
    print("  5. SQL Execution Agent")
    print("  6. Result Summarize Agent - FINAL NODE")
    print("\nConditional routing configured")
    print("All paths route to summarize node before END")
    print("\nHybrid Super Agent workflow created successfully!")
    print("="*80)

    return workflow


def create_agent_graph(
    config=None,
    with_checkpointer: Union[bool, str] = False,
):
    """
    Create and optionally compile the agent graph.

    Args:
        config: Optional configuration object (uses default if None)
        with_checkpointer:
            False  -- return uncompiled StateGraph (serving path compiles at runtime)
            True   -- compile with DatabricksCheckpointSaver (CLI on Databricks)
            "memory" -- compile with MemorySaver (local dev without Lakebase)

    Returns:
        StateGraph or CompiledStateGraph depending on with_checkpointer
    """
    workflow = create_super_agent_hybrid(config)

    if with_checkpointer is True:
        from databricks_langchain.checkpoint import DatabricksCheckpointSaver
        from databricks.sdk import WorkspaceClient

        if config is None:
            from .config import get_config
            config = get_config()

        w = WorkspaceClient()
        checkpointer = DatabricksCheckpointSaver(
            w.lakebase, database_instance_name=config.lakebase.instance_name
        )
        return workflow.compile(checkpointer=checkpointer)

    if with_checkpointer == "memory":
        from langgraph.checkpoint.memory import MemorySaver
        return workflow.compile(checkpointer=MemorySaver())

    return workflow
