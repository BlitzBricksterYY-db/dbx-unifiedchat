"""
Unit tests for Genie Space Manager tools.

Tests read-only discovery operations on Databricks Genie Spaces with mocked HTTP calls.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

MODULE = "multi_agent.tools.genie_space_manager"
MOCK_AUTH = (
    "https://host.databricks.com",
    {"Authorization": "Bearer test-token", "Accept": "application/json", "Content-Type": "application/json"},
)


@pytest.fixture(autouse=True)
def _patch_auth(request):
    """Patch auth for all tests except TestGetAuth."""
    if request.node.cls and request.node.cls.__name__ == "TestGetAuth":
        yield
    else:
        with patch(f"{MODULE}._get_auth", return_value=MOCK_AUTH):
            yield


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestListGenieSpaces:
    def test_returns_paginated(self):
        """Paginated GET, two pages of spaces parsed correctly."""
        from multi_agent.tools.genie_space_manager import list_genie_spaces

        page1 = {
            "spaces": [{"space_id": "s1", "title": "Space 1", "description": "d1"}],
            "next_page_token": "tok2",
        }
        page2 = {
            "spaces": [{"space_id": "s2", "title": "Space 2", "description": "d2"}],
        }

        with patch(f"{MODULE}.requests") as mock_req:
            mock_req.get.side_effect = [_mock_response(page1), _mock_response(page2)]
            result = json.loads(list_genie_spaces.invoke({}))

        assert len(result) == 2
        assert result[0]["space_id"] == "s1"
        assert result[1]["space_id"] == "s2"
        assert mock_req.get.call_count == 2

    def test_empty(self):
        """Empty workspace returns []."""
        from multi_agent.tools.genie_space_manager import list_genie_spaces

        with patch(f"{MODULE}.requests") as mock_req:
            mock_req.get.return_value = _mock_response({"spaces": []})
            result = json.loads(list_genie_spaces.invoke({}))

        assert result == []


class TestGetGenieSpaceConfig:
    def test_parses_tables(self, mock_genie_space_response):
        """Serialized space JSON parsed into tables list and instructions."""
        from multi_agent.tools.genie_space_manager import get_genie_space_config

        with patch(f"{MODULE}.requests") as mock_req:
            mock_req.get.return_value = _mock_response(mock_genie_space_response)
            result = json.loads(get_genie_space_config.invoke({"space_id": "test-space-001"}))

        assert result["space_id"] == "test-space-001"
        assert result["tables"] == ["catalog.schema.table_a", "catalog.schema.table_b"]
        assert result["instructions"] == "Test instructions"


class TestGetAuth:
    """Tests for _get_auth (autouse patch is skipped for this class)."""

    def test_from_env(self):
        """_get_auth reads from os.environ when both HOST and TOKEN are set."""
        from multi_agent.tools.genie_space_manager import _get_auth

        env = {
            "DATABRICKS_HOST": "https://test.cloud.databricks.com",
            "DATABRICKS_TOKEN": "dapi-test-123",
        }
        with patch.dict("os.environ", env, clear=False):
            host, headers = _get_auth()

        assert host == "https://test.cloud.databricks.com"
        assert headers["Authorization"] == "Bearer dapi-test-123"
        assert "Accept" in headers

    def test_from_sdk_config(self):
        """_get_auth falls back to Config() when env vars are empty."""
        from multi_agent.tools.genie_space_manager import _get_auth

        mock_cfg = MagicMock()
        mock_cfg.host = "https://sdk-host.databricks.com"
        mock_cfg.authenticate.return_value = {"Authorization": "Bearer sdk-oauth-token"}

        env = {"DATABRICKS_HOST": "", "DATABRICKS_TOKEN": ""}
        with patch.dict("os.environ", env, clear=False), \
             patch("databricks.sdk.core.Config", return_value=mock_cfg) as mock_config_cls:
            host, headers = _get_auth()

        assert host == "https://sdk-host.databricks.com"
        assert headers["Authorization"] == "Bearer sdk-oauth-token"
        mock_config_cls.assert_called_once()

    def test_missing_raises(self):
        """Raises RuntimeError when all auth methods fail."""
        from multi_agent.tools.genie_space_manager import _get_auth
        import builtins

        real_import = builtins.__import__

        def _block_fallbacks(name, *args, **kwargs):
            if name in ("databricks.sdk.core", "pyspark.sql", "dbruntime.databricks_repl_context"):
                raise ImportError(f"stubbed out {name}")
            return real_import(name, *args, **kwargs)

        env = {"DATABRICKS_HOST": "", "DATABRICKS_TOKEN": ""}
        with patch.dict("os.environ", env, clear=False), \
             patch("builtins.__import__", side_effect=_block_fallbacks):
            with pytest.raises(RuntimeError, match="Cannot resolve Databricks credentials"):
                _get_auth()
