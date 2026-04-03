from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_server.multi_agent.agents.summarize_agent import ResultSummarizeAgent


class _DummyLLM:
    def stream(self, _prompt):
        return []


def test_safe_json_dumps_serializes_numpy_values():
    payload = [
        {
            "embedding": np.array([1, 2, 3]),
            "score": np.float64(0.75),
            "tags": {"a", "b"},
        }
    ]

    serialized = ResultSummarizeAgent._safe_json_dumps(payload, indent=2)

    assert '"embedding": [' in serialized
    assert "0.75" in serialized


def test_build_summary_prompt_handles_numpy_preview_data():
    agent = ResultSummarizeAgent(_DummyLLM())
    state = {
        "original_query": "Summarize the vector result",
        "execution_results": [
            {
                "success": True,
                "status": "success",
                "row_count": 1,
                "columns": ["member_id", "embedding", "score"],
                "result": [
                    {
                        "member_id": "123",
                        "embedding": np.array([0.1, 0.2, 0.3]),
                        "score": np.float32(0.9),
                    }
                ],
            }
        ],
    }

    prompt = agent._build_summary_prompt(state)

    assert "Summarize the vector result" in prompt
    assert '"embedding": [' in prompt
    assert '"score": 0.8999999761581421' in prompt or '"score": 0.9' in prompt
