"""
AgentRx Node for the multi-agent LangGraph workflow.

This module provides the agent_rx_node function that integrates
the AgentRxAgent into the LangGraph state graph. It reads the user's
resource modification request from state and returns the result.
"""

import traceback
from typing import Dict, Any, Optional

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.config import get_stream_writer

from ..core.state import AgentState


# Module-level agent cache
_agent_cache: Dict[str, Any] = {}

LLM_ENDPOINT_AGENT_RX: Optional[str] = None


def get_cached_agent_rx():
    """Get or create a cached AgentRxAgent instance."""
    global LLM_ENDPOINT_AGENT_RX

    if LLM_ENDPOINT_AGENT_RX is None:
        try:
            from ..core.config import get_config
            config = get_config()
            LLM_ENDPOINT_AGENT_RX = config.llm.agent_rx_endpoint
        except Exception as e:
            print(f"Warning: Failed to load agent_rx LLM endpoint from config: {e}")

    if "agent_rx" not in _agent_cache:
        print("Creating AgentRxAgent (first use)...")
        try:
            from databricks_langchain import ChatDatabricks
            from .agent_rx_agent import AgentRxAgent

            if LLM_ENDPOINT_AGENT_RX is None:
                raise ValueError("LLM_ENDPOINT_AGENT_RX must be configured")

            llm = ChatDatabricks(endpoint=LLM_ENDPOINT_AGENT_RX, temperature=0.1)
            _agent_cache["agent_rx"] = AgentRxAgent(llm)
            print(f"AgentRxAgent cached (endpoint: {LLM_ENDPOINT_AGENT_RX})")
        except ImportError as e:
            raise ImportError(f"Failed to import dependencies for AgentRxAgent: {e}")
    else:
        print("Using cached AgentRxAgent")

    return _agent_cache["agent_rx"]


def agent_rx_node(state: AgentState) -> dict:
    """
    AgentRx node: handles resource modification requests.

    Reads the user query from the current turn, invokes the AgentRxAgent
    (ReAct loop with Genie Space + ETL tools), and returns the result
    as an AIMessage for display to the user.

    Returns:
        Dictionary with state updates including agent_rx_result and messages.
    """
    writer = get_stream_writer()

    print("\n" + "=" * 80)
    print("AGENT RX - RESOURCE MODIFICATION AGENT")
    print("=" * 80)

    current_turn = state.get("current_turn")
    if current_turn:
        user_request = current_turn.get("context_summary") or current_turn["query"]
    else:
        from langchain_core.messages import HumanMessage
        messages = state.get("messages", [])
        human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        user_request = human_msgs[-1].content if human_msgs else ""

    print(f"Request: {user_request}")
    writer({"type": "agent_start", "agent": "agent_rx", "query": user_request[:200]})

    try:
        agent = get_cached_agent_rx()
        writer({"type": "agent_thinking", "agent": "agent_rx", "content": "Processing resource modification..."})

        result = agent.invoke(user_request)

        response_text = result.get("response", "Operation completed.")
        tool_calls = result.get("tool_calls", [])

        print(f"AgentRx completed: {len(tool_calls)} tool calls")
        print(f"Response length: {len(response_text)} chars")

        writer({
            "type": "agent_rx_complete",
            "tool_call_count": len(tool_calls),
            "tools_used": [tc["tool"] for tc in tool_calls],
        })

        return {
            "agent_rx_result": {
                "response": response_text,
                "tool_calls": tool_calls,
                "success": True,
            },
            "messages": [
                AIMessage(content=response_text),
                SystemMessage(content=f"AgentRx completed {len(tool_calls)} tool operations"),
            ],
        }

    except Exception as e:
        print(f"AgentRx error: {e}")
        traceback.print_exc()

        error_msg = (
            f"### Resource Modification Error\n\n"
            f"An error occurred while processing your request:\n\n"
            f"```\n{str(e)}\n```\n\n"
            f"Please try again or rephrase your request."
        )

        return {
            "agent_rx_result": {
                "response": error_msg,
                "tool_calls": [],
                "success": False,
                "error": str(e),
            },
            "messages": [
                AIMessage(content=error_msg),
                SystemMessage(content=f"AgentRx error: {str(e)}"),
            ],
        }
