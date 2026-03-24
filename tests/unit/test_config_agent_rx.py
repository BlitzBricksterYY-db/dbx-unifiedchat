"""
Unit tests for AgentRx configuration fields.

Validates that LLMConfig includes agent_rx_endpoint and
it loads correctly from environment variables.
"""

import os
import pytest
from unittest.mock import patch


class TestLLMConfigAgentRx:
    def test_has_agent_rx_endpoint(self):
        """LLMConfig dataclass has agent_rx_endpoint field."""
        from multi_agent.core.config import LLMConfig
        import dataclasses
        field_names = [f.name for f in dataclasses.fields(LLMConfig)]
        assert "agent_rx_endpoint" in field_names

    def test_from_env(self):
        """LLM_ENDPOINT_AGENT_RX env var populates agent_rx_endpoint."""
        env = {
            "LLM_ENDPOINT": "default-model",
            "LLM_ENDPOINT_AGENT_RX": "custom-rx-model",
        }
        with patch.dict(os.environ, env, clear=False):
            from multi_agent.core.config import LLMConfig
            cfg = LLMConfig.from_env()

        assert cfg.agent_rx_endpoint == "custom-rx-model"

    def test_defaults_to_base(self):
        """When LLM_ENDPOINT_AGENT_RX unset, falls back to base LLM_ENDPOINT."""
        env = {
            "LLM_ENDPOINT": "base-model",
        }
        env_clear = {"LLM_ENDPOINT_AGENT_RX": ""}
        with patch.dict(os.environ, {**env, **env_clear}, clear=False):
            os.environ.pop("LLM_ENDPOINT_AGENT_RX", None)
            from multi_agent.core.config import LLMConfig
            cfg = LLMConfig.from_env()

        assert cfg.agent_rx_endpoint == "base-model"
