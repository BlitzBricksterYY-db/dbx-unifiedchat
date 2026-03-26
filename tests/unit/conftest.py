"""
Unit test conftest - stubs heavy Databricks dependencies before import.

This conftest runs before any test module imports, so it can safely
stub out modules that require live Databricks connections.
"""

import json
import sys
import os
from unittest.mock import MagicMock

# Stub out modules that require live Databricks connections BEFORE
# any production code is imported. These stubs prevent module-level
# side effects (e.g., databricks.sdk.runtime trying to create a
# remote Spark session).
_STUB_MODULES = [
    "databricks.sdk.runtime",
    "pyspark",
    "pyspark.sql",
    "pyspark.sql.functions",
    "pyspark.sql.types",
    "dbruntime",
    "dbruntime.databricks_repl_context",
    "databricks.sql",
    "databricks.sql.connector",
]
for _mod_name in _STUB_MODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# Ensure src is on the path so `from multi_agent.xxx` works
_src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# Set mock environment variables needed by config validation
os.environ.setdefault("DATABRICKS_HOST", "https://mock-test.cloud.databricks.com")
os.environ.setdefault("DATABRICKS_TOKEN", "dapi-mock-unit-test-token")
os.environ.setdefault("SQL_WAREHOUSE_ID", "mock_warehouse_123")

import pytest


@pytest.fixture
def mock_genie_space_response():
    """Mock full Genie space API response with serialized_space."""
    return {
        "space_id": "test-space-001",
        "title": "Test Space",
        "description": "A test Genie space",
        "warehouse_id": "warehouse-123",
        "serialized_space": json.dumps({
            "data_sources": [{"tables": [
                {"identifier": "catalog.schema.table_a"},
                {"identifier": "catalog.schema.table_b"},
            ]}],
            "instructions": "Test instructions"
        })
    }


@pytest.fixture
def sample_resource_modification_state():
    """Sample state after clarification detects resource modification."""
    return {
        "current_turn": {
            "turn_id": "turn-rx-1",
            "query": "Add table catalog.schema.new_table to the sales space",
            "intent_type": "new_question",
            "context_summary": "User wants to add catalog.schema.new_table to the sales Genie space",
            "timestamp": "2026-03-22T00:00:00",
            "triggered_clarification": False,
            "metadata": {"is_resource_modification": True},
        },
        "turn_history": [],
        "is_resource_modification": True,
        "messages": [],
    }
