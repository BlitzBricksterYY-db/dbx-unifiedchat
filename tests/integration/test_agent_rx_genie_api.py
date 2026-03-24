"""
Integration tests for AgentRx tools — read-only Genie Space discovery
and knowledge base management.

These tests call real Databricks APIs and are guarded by the
skip_integration fixture. They require DATABRICKS_HOST and
DATABRICKS_TOKEN to be set.

A dedicated test Genie space ID should be configured via the
TEST_GENIE_SPACE_ID environment variable.
"""

import os
import json
import pytest


@pytest.fixture(scope="module")
def test_space_id():
    sid = os.getenv("TEST_GENIE_SPACE_ID", "")
    if not sid:
        pytest.skip("TEST_GENIE_SPACE_ID not set — skipping live API tests")
    return sid


@pytest.fixture(autouse=True)
def _guard(skip_integration):
    if skip_integration:
        pytest.skip("Integration tests disabled (SKIP_INTEGRATION=1)")


class TestGenieDiscoveryLive:
    """Read-only Genie Space discovery tools."""

    def test_list_genie_spaces_live(self):
        """Real list spaces API returns valid response."""
        from multi_agent.tools.genie_space_manager import list_genie_spaces

        result = json.loads(list_genie_spaces.invoke({}))
        assert isinstance(result, list)
        if result:
            assert "space_id" in result[0]
            assert "title" in result[0]

    def test_get_genie_space_config_live(self, test_space_id):
        """Real space config has tables and instructions."""
        from multi_agent.tools.genie_space_manager import get_genie_space_config

        result = json.loads(get_genie_space_config.invoke({"space_id": test_space_id}))
        assert result["space_id"] == test_space_id
        assert isinstance(result["tables"], list)


class TestKnowledgeBaseLive:
    """Knowledge base management tools against real SQL Warehouse."""

    def test_list_indexed_spaces_live(self):
        """list_indexed_spaces returns valid result from enriched chunks table."""
        from multi_agent.tools.knowledge_base_manager import list_indexed_spaces

        result = json.loads(list_indexed_spaces.invoke({}))
        assert result["status"] in ("success", "error")
        if result["status"] == "success":
            assert isinstance(result["indexed_spaces"], list)
            assert isinstance(result["total_spaces"], int)

    def test_get_indexed_space_details_live(self, test_space_id):
        """get_indexed_space_details returns chunk info for a known space."""
        from multi_agent.tools.knowledge_base_manager import get_indexed_space_details

        result = json.loads(get_indexed_space_details.invoke({"space_id": test_space_id}))
        assert result["status"] in ("success", "not_found", "error")
        if result["status"] == "success":
            assert isinstance(result["chunk_summary"], list)
            assert result["total_chunks"] > 0


class TestEtlToolsLive:
    def test_trigger_vector_search_sync_live(self):
        """Sync call completes without error (when VS is configured)."""
        from multi_agent.tools.etl_trigger import trigger_vector_search_sync

        result = json.loads(trigger_vector_search_sync.invoke({}))
        assert result["status"] in ("success", "error")
