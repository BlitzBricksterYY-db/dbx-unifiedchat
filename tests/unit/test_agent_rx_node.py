"""
Unit tests for agent_rx_node and get_cached_agent_rx.

Tests the LangGraph node function that integrates AgentRxAgent into the
workflow, with mocked agent and stream writer.
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage

MODULE = "multi_agent.agents.agent_rx"


@pytest.fixture
def mock_writer():
    writer = MagicMock()
    with patch(f"{MODULE}.get_stream_writer", return_value=writer):
        yield writer


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.invoke.return_value = {
        "response": "Space removed from index successfully.",
        "tool_calls": [{"tool": "remove_space_from_index", "args": {"space_id": "s1"}}],
    }
    return agent


class TestAgentRxNode:
    def test_success(self, mock_writer, mock_agent, sample_resource_modification_state):
        """Returns agent_rx_result with success: True, AIMessage in messages."""
        from multi_agent.agents.agent_rx import agent_rx_node

        with patch(f"{MODULE}.get_cached_agent_rx", return_value=mock_agent):
            result = agent_rx_node(sample_resource_modification_state)

        assert result["agent_rx_result"]["success"] is True
        assert result["agent_rx_result"]["response"] == "Space removed from index successfully."
        assert len(result["agent_rx_result"]["tool_calls"]) == 1
        assert any(isinstance(m, AIMessage) for m in result["messages"])

    def test_reads_context_summary(self, mock_writer, mock_agent):
        """Prefers current_turn.context_summary over raw query."""
        from multi_agent.agents.agent_rx import agent_rx_node

        state = {
            "current_turn": {
                "query": "raw query",
                "context_summary": "Summarized: add table to space",
            },
            "messages": [],
        }

        with patch(f"{MODULE}.get_cached_agent_rx", return_value=mock_agent):
            agent_rx_node(state)

        mock_agent.invoke.assert_called_once_with("Summarized: add table to space")

    def test_falls_back_to_human_message(self, mock_writer, mock_agent):
        """Without current_turn, reads last HumanMessage."""
        from multi_agent.agents.agent_rx import agent_rx_node

        state = {
            "current_turn": None,
            "messages": [
                HumanMessage(content="First message"),
                HumanMessage(content="Add table X to space Y"),
            ],
        }

        with patch(f"{MODULE}.get_cached_agent_rx", return_value=mock_agent):
            agent_rx_node(state)

        mock_agent.invoke.assert_called_once_with("Add table X to space Y")

    def test_error_handling(self, mock_writer):
        """On agent exception, returns success: False with error markdown."""
        from multi_agent.agents.agent_rx import agent_rx_node

        failing_agent = MagicMock()
        failing_agent.invoke.side_effect = RuntimeError("LLM timeout")

        state = {
            "current_turn": {"query": "do something", "context_summary": None},
            "messages": [],
        }

        with patch(f"{MODULE}.get_cached_agent_rx", return_value=failing_agent):
            result = agent_rx_node(state)

        assert result["agent_rx_result"]["success"] is False
        assert "LLM timeout" in result["agent_rx_result"]["error"]
        assert "Resource Modification Error" in result["agent_rx_result"]["response"]

    def test_emits_writer_events(self, mock_writer, mock_agent, sample_resource_modification_state):
        """Writer called with agent_start, agent_thinking, agent_rx_complete."""
        from multi_agent.agents.agent_rx import agent_rx_node

        with patch(f"{MODULE}.get_cached_agent_rx", return_value=mock_agent):
            agent_rx_node(sample_resource_modification_state)

        event_types = [call.args[0]["type"] for call in mock_writer.call_args_list]
        assert "agent_start" in event_types
        assert "agent_thinking" in event_types
        assert "agent_rx_complete" in event_types


class TestGetCachedAgentRx:
    def test_caches(self):
        """Second call reuses cached instance."""
        import multi_agent.agents.agent_rx as mod

        mod._agent_cache.clear()
        mod.LLM_ENDPOINT_AGENT_RX = None

        mock_config = MagicMock()
        mock_config.llm.agent_rx_endpoint = "test-endpoint"

        with patch("multi_agent.core.config.get_config", return_value=mock_config), \
             patch("databricks_langchain.ChatDatabricks") as mock_chat, \
             patch("multi_agent.agents.agent_rx_agent.AgentRxAgent") as mock_cls:

            mock_chat.return_value = MagicMock()
            mock_cls.return_value = MagicMock()

            first = mod.get_cached_agent_rx()
            second = mod.get_cached_agent_rx()

        assert first is second
        mock_cls.assert_called_once()

        mod._agent_cache.clear()
        mod.LLM_ENDPOINT_AGENT_RX = None
