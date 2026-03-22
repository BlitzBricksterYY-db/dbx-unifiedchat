from pathlib import Path
from types import SimpleNamespace
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_server.multi_agent.agents.summarize import _build_artifact_entries
from agent_server.multi_agent.agents.summarize_agent import ResultSummarizeAgent
from agent_server.multi_agent.tools.web_search import detect_code_columns


class StubLlm:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _prompt: str):
        return SimpleNamespace(content=self._content)


def test_build_artifact_entries_prefers_execution_result_metadata():
    state = {
        "execution_results": [
            {
                "success": True,
                "sql": "SELECT 1",
                "query_label": "Top 10 members",
                "columns": ["patient_id"],
                "result": [{"patient_id": "a"}],
                "row_count": 1,
            },
            {
                "success": True,
                "sql": "SELECT 2",
                "query_label": "Coverage details",
                "columns": ["benefit_type"],
                "result": [{"benefit_type": "MEDICAL"}],
                "row_count": 1,
            },
        ],
        "sql_queries": ["STALE QUERY"],
        "sql_query_labels": ["Stale label"],
    }

    entries = _build_artifact_entries(state)

    assert [entry["label"] for entry in entries] == [
        "Top 10 members",
        "Coverage details",
    ]
    assert [entry["sql"] for entry in entries] == ["SELECT 1", "SELECT 2"]


def test_summary_prompt_requires_per_result_sections_and_safe_inference():
    agent = ResultSummarizeAgent(llm=None)  # type: ignore[arg-type]

    prompt = agent._build_summary_prompt(
        {
            "original_query": "Analyze top 10 most expensive members",
            "question_clear": True,
            "execution_results": [
                {
                    "success": True,
                    "query_label": "Cost breakdown",
                    "columns": ["patient_id", "total_cost"],
                    "result": [{"patient_id": "a", "total_cost": 10}],
                    "row_count": 1,
                },
                {
                    "success": True,
                    "query_label": "Coverage details",
                    "columns": ["patient_id", "benefit_type"],
                    "result": [{"patient_id": "a", "benefit_type": "MEDICAL"}],
                    "row_count": 1,
                },
            ],
        }
    )

    assert "create one `###` subsection per result set" in prompt
    assert "Do not merge multiple result sets into one markdown table" in prompt
    assert "do NOT infer distinct member counts" in prompt
    assert "Statements about how many charts" in prompt
    assert "Query 1 — Cost breakdown Result" in prompt
    assert "Query 2 — Coverage details Result" in prompt


def test_detect_code_columns_skips_aggregate_metric_columns():
    llm = StubLlm(
        '[{"column":"cpt_procedure_count","code_type":"CPT"},'
        '{"column":"diagnosis_code","code_type":"ICD10"}]'
    )

    detected = detect_code_columns(
        columns=["cpt_procedure_count", "diagnosis_code"],
        sample_data=[
            {"cpt_procedure_count": 578, "diagnosis_code": "C641"},
            {"cpt_procedure_count": 223, "diagnosis_code": "I10"},
        ],
        llm=llm,
    )

    assert detected == [{"column": "diagnosis_code", "code_type": "ICD10"}]
