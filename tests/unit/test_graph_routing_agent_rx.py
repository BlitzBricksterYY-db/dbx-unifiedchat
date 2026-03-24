"""
Unit tests for AgentRx routing logic in the LangGraph workflow.

Tests route_after_unified behavior and graph structure by inspecting
the StateGraph built by create_super_agent_hybrid().
"""

import pytest
from unittest.mock import patch, MagicMock
from langgraph.graph import END


def _make_state(**overrides):
    """Build a minimal state dict for routing tests."""
    base = {
        "is_irrelevant": False,
        "is_resource_modification": False,
        "is_meta_question": False,
        "question_clear": False,
    }
    base.update(overrides)
    return base


class TestRouteAfterUnified:
    """Test the route_after_unified function extracted from the graph module."""

    @pytest.fixture(autouse=True)
    def _import_routing(self):
        """
        Extract route_after_unified by building the graph and capturing
        the function via the conditional edges registration.
        """
        with patch("multi_agent.core.graph.unified_intent_context_clarification_node"), \
             patch("multi_agent.core.graph.planning_node"), \
             patch("multi_agent.core.graph.sql_synthesis_table_node"), \
             patch("multi_agent.core.graph.sql_synthesis_genie_node"), \
             patch("multi_agent.core.graph.sql_execution_node"), \
             patch("multi_agent.core.graph.summarize_node"), \
             patch("multi_agent.core.graph.agent_rx_node"):

            from multi_agent.core.graph import create_super_agent_hybrid
            workflow = create_super_agent_hybrid()

        branches = workflow.branches.get("unified_intent_context_clarification", {})
        for branch in branches.values():
            path = branch.path
            # LangGraph wraps the routing function in a RunnableCallable;
            # extract the underlying callable via .func attribute.
            self.route_fn = getattr(path, "func", path)
            break

    def test_resource_modification_to_agent_rx(self):
        """is_resource_modification=True returns 'agent_rx'."""
        result = self.route_fn(_make_state(is_resource_modification=True))
        assert result == "agent_rx"

    def test_irrelevant_beats_resource_mod(self):
        """If both is_irrelevant and is_resource_modification, irrelevant wins."""
        result = self.route_fn(_make_state(is_irrelevant=True, is_resource_modification=True))
        assert result == END

    def test_resource_mod_beats_meta(self):
        """Resource modification checked before is_meta_question."""
        result = self.route_fn(_make_state(is_resource_modification=True, is_meta_question=True))
        assert result == "agent_rx"

    def test_normal_query_to_planning(self):
        """question_clear=True without flags goes to 'planning'."""
        result = self.route_fn(_make_state(question_clear=True))
        assert result == "planning"


class TestGraphStructure:
    @pytest.fixture(autouse=True)
    def _build_graph(self):
        with patch("multi_agent.core.graph.unified_intent_context_clarification_node"), \
             patch("multi_agent.core.graph.planning_node"), \
             patch("multi_agent.core.graph.sql_synthesis_table_node"), \
             patch("multi_agent.core.graph.sql_synthesis_genie_node"), \
             patch("multi_agent.core.graph.sql_execution_node"), \
             patch("multi_agent.core.graph.summarize_node"), \
             patch("multi_agent.core.graph.agent_rx_node"):

            from multi_agent.core.graph import create_super_agent_hybrid
            self.workflow = create_super_agent_hybrid()

    def test_agent_rx_node_registered(self):
        """Graph has 'agent_rx' in its nodes."""
        assert "agent_rx" in self.workflow.nodes

    def test_agent_rx_edge_to_end(self):
        """agent_rx has an edge to END."""
        edges = self.workflow.edges
        assert ("agent_rx", "__end__") in edges
