from pathlib import Path
import sys
from datetime import date
from decimal import Decimal

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_server.multi_agent.agents.sql_execution_agent import SQLExecutionAgent


def test_normalize_result_rows_converts_numpy_arrays_and_scalars():
    columns = ["member_id", "embedding", "score"]
    rows = [
        (
            "123",
            np.array([0.1, 0.2, 0.3]),
            np.float32(0.9),
        )
    ]

    normalized = SQLExecutionAgent._normalize_result_rows(columns, rows)

    assert normalized == [
        {
            "member_id": "123",
            "embedding": [0.1, 0.2, 0.3],
            "score": normalized[0]["score"],
        }
    ]
    assert isinstance(normalized[0]["embedding"], list)
    assert isinstance(normalized[0]["score"], float)


def test_normalize_result_value_handles_common_non_json_types():
    normalized = SQLExecutionAgent._normalize_result_value(
        {
            "service_date": date(2026, 3, 30),
            "amount": Decimal("12.50"),
            "tags": {"a", "b"},
        }
    )

    assert normalized["service_date"] == "2026-03-30"
    assert normalized["amount"] == 12.5
    assert sorted(normalized["tags"]) == ["a", "b"]
