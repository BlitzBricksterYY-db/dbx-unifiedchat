"""
Unit tests for ETL trigger tools.

Tests Vector Search sync, full ETL pipeline triggering, and cache invalidation
with mocked SDK/HTTP calls.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

MODULE = "multi_agent.tools.etl_trigger"
MOCK_AUTH = (
    "https://host.databricks.com",
    {"Authorization": "Bearer test-token", "Accept": "application/json", "Content-Type": "application/json"},
)


@pytest.fixture(autouse=True)
def _patch_auth():
    with patch(f"{MODULE}._get_auth", return_value=MOCK_AUTH):
        yield


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestTriggerVectorSearchSync:
    @patch("databricks.vector_search.client.VectorSearchClient")
    def test_success(self, mock_vsc_cls):
        from multi_agent.tools.etl_trigger import trigger_vector_search_sync

        mock_idx = MagicMock()
        mock_vsc_cls.return_value.get_index.return_value = mock_idx

        result = json.loads(trigger_vector_search_sync.invoke({
            "vs_endpoint_name": "ep1",
            "vs_index_name": "cat.sch.idx",
        }))

        assert result["status"] == "success"
        mock_idx.sync.assert_called_once()

    @patch("databricks.vector_search.client.VectorSearchClient")
    def test_error(self, mock_vsc_cls):
        """Returns error JSON on SDK exception."""
        from multi_agent.tools.etl_trigger import trigger_vector_search_sync

        mock_vsc_cls.return_value.get_index.side_effect = RuntimeError("index gone")

        result = json.loads(trigger_vector_search_sync.invoke({
            "vs_endpoint_name": "ep1",
            "vs_index_name": "cat.sch.idx",
        }))

        assert result["status"] == "error"
        assert "index gone" in result["message"]

    def test_no_index_name(self):
        """Returns error when index name unresolvable."""
        from multi_agent.tools.etl_trigger import trigger_vector_search_sync

        with patch("databricks.vector_search.client.VectorSearchClient"), \
             patch("multi_agent.core.config.get_config", side_effect=Exception("no config")):
            result = json.loads(trigger_vector_search_sync.invoke({
                "vs_endpoint_name": None,
                "vs_index_name": None,
            }))

        assert result["status"] == "error"
        assert "index name" in result["message"].lower()


class TestTriggerFullEtlPipeline:
    def test_success(self):
        """Jobs list lookup + run-now called, run_id returned."""
        from multi_agent.tools.etl_trigger import trigger_full_etl_pipeline

        jobs_resp = _mock_response({"jobs": [{"job_id": 42}]})
        run_resp = _mock_response({"run_id": 999})

        with patch(f"{MODULE}.requests") as mock_req:
            mock_req.get.return_value = jobs_resp
            mock_req.post.return_value = run_resp

            result = json.loads(trigger_full_etl_pipeline.invoke({}))

        assert result["status"] == "success"
        assert result["run_id"] == 999
        assert result["job_id"] == 42
        mock_req.post.assert_called_once()

    def test_job_not_found(self):
        """Returns error when job name not found."""
        from multi_agent.tools.etl_trigger import trigger_full_etl_pipeline

        with patch(f"{MODULE}.requests") as mock_req:
            mock_req.get.return_value = _mock_response({"jobs": []})

            result = json.loads(trigger_full_etl_pipeline.invoke({}))

        assert result["status"] == "error"
        assert "No job found" in result["message"]


class TestInvalidateSpaceContextCache:
    def test_cache_cleared(self):
        """Cache dict fields set to None."""
        from multi_agent.tools.etl_trigger import invalidate_space_context_cache

        fake_cache = {"data": "old", "timestamp": "t1", "table_name": "tbl"}
        with patch(f"multi_agent.agents.clarification._space_context_cache", fake_cache):
            result = json.loads(invalidate_space_context_cache.invoke({}))

        assert result["status"] == "success"
        assert fake_cache["data"] is None
        assert fake_cache["timestamp"] is None
        assert fake_cache["table_name"] is None
