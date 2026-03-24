"""
Unit tests for AgentRx-related state fields.

Validates that AgentState includes the new fields and that
reset/initial state functions handle them correctly.
"""

import pytest


class TestAgentStateFields:
    def test_has_resource_modification_field(self):
        """AgentState TypedDict includes is_resource_modification."""
        from multi_agent.core.state import AgentState
        assert "is_resource_modification" in AgentState.__annotations__

    def test_has_agent_rx_result_field(self):
        """AgentState TypedDict includes agent_rx_result."""
        from multi_agent.core.state import AgentState
        assert "agent_rx_result" in AgentState.__annotations__


class TestResetState:
    def test_clears_agent_rx_fields(self):
        """get_reset_state_template() has correct defaults for agentRx fields."""
        from multi_agent.core.state import get_reset_state_template
        template = get_reset_state_template()

        assert template["is_resource_modification"] is False
        assert template["agent_rx_result"] is None


class TestInitialState:
    def test_initial_state_agent_rx_fields(self):
        """get_initial_state() includes the new fields with correct defaults."""
        from multi_agent.core.state import get_initial_state
        state = get_initial_state()

        assert state["is_resource_modification"] is False
        assert state["agent_rx_result"] is None
