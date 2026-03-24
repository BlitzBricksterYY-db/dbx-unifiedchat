"""
Unit tests for Knowledge Base Manager tools.

Tests knowledge base CRUD operations with mocked SQL connections,
REST API calls, and config.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

MODULE = "multi_agent.tools.knowledge_base_manager"

MOCK_AUTH = (
    "https://host.databricks.com",
    {"Authorization": "Bearer tok", "Accept": "application/json", "Content-Type": "application/json"},
)

MOCK_TABLES = {
    "enriched_docs": "cat.sch.enriched_genie_docs",
    "chunks": "cat.sch.enriched_genie_docs_chunks",
    "volume_path": "/Volumes/cat/sch/volume/genie_exports",
}


@pytest.fixture(autouse=True)
def _patch_helpers():
    """Patch SQL connection, table names, and auth for all tests."""
    with patch(f"{MODULE}._get_sql_connection") as mock_conn, \
         patch(f"{MODULE}._get_table_names", return_value=MOCK_TABLES):
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=False)
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_connection
        yield {"connection": mock_connection, "cursor": mock_cursor}


class TestListIndexedSpaces:
    def test_success(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import list_indexed_spaces

        cursor = _patch_helpers["cursor"]
        cursor.description = [("space_id",), ("space_title",), ("chunk_count",)]
        cursor.fetchall.return_value = [
            ("s1", "Sales", 42),
            ("s2", "HR", 15),
        ]

        result = json.loads(list_indexed_spaces.invoke({}))

        assert result["status"] == "success"
        assert result["total_spaces"] == 2
        assert result["indexed_spaces"][0]["space_id"] == "s1"
        assert result["indexed_spaces"][1]["chunk_count"] == 15

    def test_empty(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import list_indexed_spaces

        cursor = _patch_helpers["cursor"]
        cursor.description = [("space_id",), ("space_title",), ("chunk_count",)]
        cursor.fetchall.return_value = []

        result = json.loads(list_indexed_spaces.invoke({}))

        assert result["status"] == "success"
        assert result["total_spaces"] == 0
        assert result["indexed_spaces"] == []

    def test_sql_error(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import list_indexed_spaces

        cursor = _patch_helpers["cursor"]
        cursor.execute.side_effect = Exception("connection refused")

        result = json.loads(list_indexed_spaces.invoke({}))

        assert result["status"] == "error"
        assert "connection refused" in result["message"]


class TestRemoveSpaceFromIndex:
    def test_success(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import remove_space_from_index

        mock_list_resp = MagicMock()
        mock_list_resp.status_code = 200
        mock_list_resp.json.return_value = {"contents": [
            {"name": "abc123__Sales.space.json"},
            {"name": "abc123__Sales.serialized.json"},
            {"name": "other__HR.space.json"},
        ]}

        mock_del_resp = MagicMock()
        mock_del_resp.status_code = 204

        vs_ok = json.dumps({"status": "success", "message": "synced"})
        cache_ok = json.dumps({"status": "success", "message": "invalidated"})

        with patch(f"{MODULE}._execute_sql_via_api") as mock_sql_api, \
             patch(f"{MODULE}.requests") as mock_req, \
             patch("multi_agent.tools.genie_space_manager._get_auth", return_value=MOCK_AUTH), \
             patch("multi_agent.tools.etl_trigger.trigger_vector_search_sync") as mock_vs, \
             patch("multi_agent.tools.etl_trigger.invalidate_space_context_cache") as mock_cache:
            mock_sql_api.return_value = {"status": {"state": "SUCCEEDED"}}
            mock_req.get.return_value = mock_list_resp
            mock_req.delete.return_value = mock_del_resp
            mock_vs.invoke.return_value = vs_ok
            mock_cache.invoke.return_value = cache_ok

            result = json.loads(remove_space_from_index.invoke({"space_id": "abc123"}))

        assert result["status"] == "success"
        assert "abc123" in result["message"]
        assert any("Deleted 2 export file" in op for op in result["operations"])
        assert mock_sql_api.call_count == 2

    def test_invalid_space_id(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import remove_space_from_index

        result = json.loads(remove_space_from_index.invoke({"space_id": "'; DROP TABLE --"}))
        assert result["status"] == "error"
        assert "Invalid space_id" in result["message"]


class TestAddSpaceToIndex:
    def test_success(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import add_space_to_index

        mock_genie_resp = MagicMock()
        mock_genie_resp.status_code = 200
        mock_genie_resp.json.return_value = {"title": "New Space", "space_id": "new1"}
        mock_genie_resp.raise_for_status.return_value = None

        mock_put_resp = MagicMock()
        mock_put_resp.status_code = 200

        mock_jobs_list_resp = MagicMock()
        mock_jobs_list_resp.status_code = 200
        mock_jobs_list_resp.json.return_value = {"jobs": [{"job_id": 99}]}
        mock_jobs_list_resp.raise_for_status.return_value = None

        mock_run_resp = MagicMock()
        mock_run_resp.status_code = 200
        mock_run_resp.json.return_value = {"run_id": 555}
        mock_run_resp.raise_for_status.return_value = None

        cache_ok = json.dumps({"status": "success", "message": "invalidated"})

        with patch(f"{MODULE}.requests") as mock_req, \
             patch("multi_agent.tools.genie_space_manager._get_auth", return_value=MOCK_AUTH), \
             patch("multi_agent.tools.etl_trigger.invalidate_space_context_cache") as mock_cache:
            mock_req.get.side_effect = [mock_genie_resp, mock_jobs_list_resp]
            mock_req.put.return_value = mock_put_resp
            mock_req.post.return_value = mock_run_resp
            mock_cache.invoke.return_value = cache_ok

            result = json.loads(add_space_to_index.invoke({"space_id": "new1"}))

        assert result["status"] == "success"
        assert "New Space" in result["message"]
        assert result["run_id"] == 555
        assert any("Exported space JSON" in op for op in result["operations"])
        assert any("incremental indexing job" in op for op in result["operations"])
        mock_req.post.assert_called_once()
        call_json = mock_req.post.call_args.kwargs.get("json") or mock_req.post.call_args[1].get("json")
        assert call_json["job_parameters"]["space_id"] == "new1"

    def test_job_not_found(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import add_space_to_index

        mock_genie_resp = MagicMock()
        mock_genie_resp.status_code = 200
        mock_genie_resp.json.return_value = {"title": "New Space", "space_id": "new1"}
        mock_genie_resp.raise_for_status.return_value = None

        mock_put_resp = MagicMock()
        mock_put_resp.status_code = 200

        mock_jobs_list_resp = MagicMock()
        mock_jobs_list_resp.status_code = 200
        mock_jobs_list_resp.json.return_value = {"jobs": []}
        mock_jobs_list_resp.raise_for_status.return_value = None

        with patch(f"{MODULE}.requests") as mock_req, \
             patch("multi_agent.tools.genie_space_manager._get_auth", return_value=MOCK_AUTH):
            mock_req.get.side_effect = [mock_genie_resp, mock_jobs_list_resp]
            mock_req.put.return_value = mock_put_resp

            result = json.loads(add_space_to_index.invoke({"space_id": "new1"}))

        assert result["status"] == "error"
        assert "No job found" in result["message"]

    def test_invalid_space_id(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import add_space_to_index

        result = json.loads(add_space_to_index.invoke({"space_id": "bad id!"}))
        assert result["status"] == "error"
        assert "Invalid space_id" in result["message"]


class TestGetIndexedSpaceDetails:
    def test_found(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import get_indexed_space_details

        cursor = _patch_helpers["cursor"]

        call_count = 0

        def _execute_side_effect(sql):
            nonlocal call_count
            call_count += 1

        cursor.execute.side_effect = _execute_side_effect

        chunk_desc = [("chunk_type",), ("count",)]
        table_desc = [("table_name",)]
        title_desc = [("space_title",)]

        cursor.description = chunk_desc
        cursor.fetchall.side_effect = [
            [("space_summary", 1), ("table_overview", 5), ("column_detail", 20)],
            [("orders",), ("customers",)],
        ]
        cursor.fetchone.return_value = ("Sales Space",)

        # Need to vary cursor.description per execute call
        descriptions = [chunk_desc, table_desc, title_desc]
        desc_idx = [0]
        original_execute = cursor.execute.side_effect

        def _execute_with_desc(sql):
            cursor.description = descriptions[min(desc_idx[0], len(descriptions) - 1)]
            desc_idx[0] += 1

        cursor.execute.side_effect = _execute_with_desc

        result = json.loads(get_indexed_space_details.invoke({"space_id": "abc123"}))

        assert result["status"] == "success"
        assert result["space_title"] == "Sales Space"
        assert result["total_chunks"] == 26
        assert result["table_count"] == 2

    def test_not_found(self, _patch_helpers):
        from multi_agent.tools.knowledge_base_manager import get_indexed_space_details

        cursor = _patch_helpers["cursor"]
        cursor.description = [("chunk_type",), ("count",)]
        cursor.fetchall.return_value = []

        result = json.loads(get_indexed_space_details.invoke({"space_id": "nonexistent"}))

        assert result["status"] == "not_found"


class TestValidateSpaceId:
    def test_valid_hex(self):
        from multi_agent.tools.knowledge_base_manager import _validate_space_id
        assert _validate_space_id("abc123def456") == "abc123def456"

    def test_valid_with_dashes(self):
        from multi_agent.tools.knowledge_base_manager import _validate_space_id
        assert _validate_space_id("01f123-abc") == "01f123-abc"

    def test_rejects_sql_injection(self):
        from multi_agent.tools.knowledge_base_manager import _validate_space_id
        with pytest.raises(ValueError, match="Invalid space_id"):
            _validate_space_id("'; DROP TABLE --")

    def test_rejects_empty(self):
        from multi_agent.tools.knowledge_base_manager import _validate_space_id
        with pytest.raises(ValueError, match="Invalid space_id"):
            _validate_space_id("")

    def test_strips_whitespace(self):
        from multi_agent.tools.knowledge_base_manager import _validate_space_id
        assert _validate_space_id("  abc123  ") == "abc123"
