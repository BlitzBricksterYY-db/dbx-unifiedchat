"""
Unit tests for AgentRxAgent class.

Tests construction, tool binding, invocation, and response extraction
with a mocked ReAct agent.
"""

import pytest
from unittest.mock import patch, MagicMock

# Patch target: create_react_agent is imported inside _build_agent
# from langgraph.prebuilt, so we patch it at source.
REACT_AGENT = "langgraph.prebuilt.create_react_agent"


def _make_mock_message(content="", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    return msg


class TestAgentRxInit:
    @patch(REACT_AGENT)
    def test_default_tools(self, mock_create):
        """Constructor uses ALL_GENIE_TOOLS + ALL_KB_TOOLS + ALL_ETL_TOOLS."""
        from multi_agent.agents.agent_rx_agent import AgentRxAgent
        from multi_agent.tools.genie_space_manager import ALL_GENIE_TOOLS
        from multi_agent.tools.knowledge_base_manager import ALL_KB_TOOLS
        from multi_agent.tools.etl_trigger import ALL_ETL_TOOLS

        mock_create.return_value = MagicMock()
        llm = MagicMock()
        agent = AgentRxAgent(llm)

        assert agent.tools == ALL_GENIE_TOOLS + ALL_KB_TOOLS + ALL_ETL_TOOLS
        expected_count = len(ALL_GENIE_TOOLS) + len(ALL_KB_TOOLS) + len(ALL_ETL_TOOLS)
        assert len(agent.tools) == expected_count

    @patch(REACT_AGENT)
    def test_custom_tools(self, mock_create):
        """Custom tools list overrides defaults."""
        from multi_agent.agents.agent_rx_agent import AgentRxAgent

        mock_create.return_value = MagicMock()
        custom = [MagicMock(), MagicMock()]
        agent = AgentRxAgent(MagicMock(), tools=custom)

        assert agent.tools == custom
        assert len(agent.tools) == 2


class TestAgentRxInvoke:
    @patch(REACT_AGENT)
    def test_returns_response(self, mock_create):
        """invoke() returns response and tool_calls."""
        from multi_agent.agents.agent_rx_agent import AgentRxAgent

        ai_msg = _make_mock_message(content="Done! Table added.")
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [ai_msg]}
        mock_create.return_value = mock_agent

        agent = AgentRxAgent(MagicMock())
        result = agent.invoke("Add table X to space Y")

        assert result["response"] == "Done! Table added."
        assert isinstance(result["tool_calls"], list)

    @patch(REACT_AGENT)
    def test_extracts_tool_calls(self, mock_create):
        """Tool call names and args extracted from messages."""
        from multi_agent.agents.agent_rx_agent import AgentRxAgent

        tc = {"name": "remove_space_from_index", "args": {"space_id": "s1"}}
        tool_msg = _make_mock_message(content="Calling tool...", tool_calls=[tc])
        ai_msg = _make_mock_message(content="Space removed from index.")
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [tool_msg, ai_msg]}
        mock_create.return_value = mock_agent

        agent = AgentRxAgent(MagicMock())
        result = agent.invoke("Remove space s1 from knowledge base")

        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "remove_space_from_index"
        assert result["tool_calls"][0]["args"]["space_id"] == "s1"
        assert result["response"] == "Space removed from index."

    @patch(REACT_AGENT)
    def test_callable(self, mock_create):
        """__call__ delegates to invoke."""
        from multi_agent.agents.agent_rx_agent import AgentRxAgent

        ai_msg = _make_mock_message(content="Response")
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [ai_msg]}
        mock_create.return_value = mock_agent

        agent = AgentRxAgent(MagicMock())
        result = agent("test request")

        assert result["response"] == "Response"

    @patch(REACT_AGENT)
    def test_system_prompt_present(self, mock_create):
        """System prompt passed to create_react_agent."""
        from multi_agent.agents.agent_rx_agent import AgentRxAgent, AGENT_RX_SYSTEM_PROMPT

        mock_create.return_value = MagicMock()
        AgentRxAgent(MagicMock())

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs.get("prompt") == AGENT_RX_SYSTEM_PROMPT
