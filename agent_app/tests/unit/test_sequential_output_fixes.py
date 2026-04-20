import json
from pathlib import Path
from types import SimpleNamespace
import concurrent.futures
import threading
import time
import types
import sys
import uuid

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

multi_agent_root = Path(__file__).resolve().parents[2] / "agent_server" / "multi_agent"
multi_agent_pkg = types.ModuleType("agent_server.multi_agent")
multi_agent_pkg.__path__ = [str(multi_agent_root)]
sys.modules.setdefault("agent_server.multi_agent", multi_agent_pkg)

core_pkg = types.ModuleType("agent_server.multi_agent.core")
core_pkg.__path__ = [str(multi_agent_root / "core")]
sys.modules.setdefault("agent_server.multi_agent.core", core_pkg)

agents_pkg = types.ModuleType("agent_server.multi_agent.agents")
agents_pkg.__path__ = [str(multi_agent_root / "agents")]
sys.modules.setdefault("agent_server.multi_agent.agents", agents_pkg)

langchain_core_pkg = types.ModuleType("langchain_core")
sys.modules.setdefault("langchain_core", langchain_core_pkg)

runnables_stub = types.ModuleType("langchain_core.runnables")
runnables_stub.Runnable = object
sys.modules.setdefault("langchain_core.runnables", runnables_stub)

messages_stub = types.ModuleType("langchain_core.messages")
messages_stub.AIMessage = SimpleNamespace
messages_stub.HumanMessage = SimpleNamespace
messages_stub.SystemMessage = SimpleNamespace
sys.modules.setdefault("langchain_core.messages", messages_stub)

langgraph_pkg = types.ModuleType("langgraph")
sys.modules.setdefault("langgraph", langgraph_pkg)

langgraph_config_stub = types.ModuleType("langgraph.config")
langgraph_config_stub.get_stream_writer = lambda: (lambda *_args, **_kwargs: None)
sys.modules.setdefault("langgraph.config", langgraph_config_stub)

graph_stub = types.ModuleType("agent_server.multi_agent.core.graph")
graph_stub.create_super_agent_hybrid = lambda *args, **kwargs: None
graph_stub.create_agent_graph = lambda *args, **kwargs: None
graph_stub.get_space_context_table_name = lambda _config: "catalog.schema.source_table"
sys.modules.setdefault("agent_server.multi_agent.core.graph", graph_stub)

from agent_server.multi_agent.agents.chart_generator import (
    ChartGenerator,
    MAX_JSON_BYTES,
    SUPPORTED_CHART_TYPES,
    SUPPORTED_TRANSFORMS,
    _load_sqlglot,
)
from agent_server.multi_agent.agents.sql_execution import _append_remaining_skipped_artifacts
from agent_server.multi_agent.agents.summarize import (
    _build_artifact_entries,
    _build_visualization_workspace_payload,
)
from agent_server.multi_agent.agents.summarize_agent import ResultSummarizeAgent
from agent_server.multi_agent.tools.web_search import detect_code_columns


class StubLlm:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _prompt: str):
        return SimpleNamespace(content=self._content)

    def stream(self, _prompt: str):
        yield SimpleNamespace(content=self._content)


class NonConcurrentLlm:
    def __init__(self, content: str, delay: float = 0.05):
        self._content = content
        self._delay = delay
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def invoke(self, _prompt: str):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(self._delay)
        with self._lock:
            self._active -= 1
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


def test_append_remaining_skipped_artifacts_pads_sequential_results():
    state = {
        "total_sub_questions": 5,
        "sub_questions": [
            "Cost breakdown",
            "Utilization",
            "Comorbidities",
            "Demographics",
            "Coverage details",
        ],
    }
    preserved = [
        {
            "status": "success",
            "success": True,
            "query_number": 1,
            "query_label": "Cost breakdown",
            "sql": "SELECT 1",
            "columns": ["patient_id"],
            "result": [{"patient_id": "a"}],
            "row_count": 1,
        },
        {
            "status": "success",
            "success": True,
            "query_number": 2,
            "query_label": "Utilization",
            "sql": "SELECT 2",
            "columns": ["patient_id"],
            "result": [{"patient_id": "a"}],
            "row_count": 1,
        },
        {
            "status": "success",
            "success": True,
            "query_number": 3,
            "query_label": "Comorbidities",
            "sql": "SELECT 3",
            "columns": ["patient_id"],
            "result": [{"patient_id": "a"}],
            "row_count": 1,
        },
        {
            "status": "success",
            "success": True,
            "query_number": 4,
            "query_label": "Demographics",
            "sql": "SELECT 4",
            "columns": ["patient_id"],
            "result": [{"patient_id": "a"}],
            "row_count": 1,
        },
    ]

    padded = _append_remaining_skipped_artifacts(
        state,
        preserved,
        start_step=4,
        reason="Skipped because already covered by prior results.",
    )

    assert len(padded) == 5
    assert padded[-1]["status"] == "skipped"
    assert padded[-1]["query_number"] == 5
    assert padded[-1]["query_label"] == "Coverage details"
    assert "already covered" in padded[-1]["skip_reason"]


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


def test_sql_sections_are_keyed_by_final_artifact_labels():
    artifact_entries = [
        {
            "label": "Cost breakdown",
            "status": "success",
            "sql": "SELECT 1",
            "sql_explanation": "Built from medical and pharmacy claims.",
        },
        {
            "label": "Coverage details",
            "status": "skipped",
            "sql": "",
            "skip_reason": "Skipped because already covered by demographics result.",
            "sql_explanation": "Skipped because already covered by demographics result.",
        },
    ]

    sql_block = ResultSummarizeAgent.format_sql_download(artifact_entries)
    explanation_block = ResultSummarizeAgent.format_sql_explanation(artifact_entries)

    assert "**Cost breakdown**" in sql_block
    assert "**Coverage details**" in sql_block
    assert "No SQL generated for this planned query" in sql_block

    assert "### Query 1 — Cost breakdown" in explanation_block
    assert "### Query 2 — Coverage details" in explanation_block
    assert "Skipped / already covered" in explanation_block


def test_chart_generator_dedupes_repeated_patient_totals():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    chart_data, note = generator._agg_top_n(
        data=[
            {
                "patient_id": "a",
                "diagnosis_code": "D1",
                "total_paid_amount": 100.0,
            },
            {
                "patient_id": "a",
                "diagnosis_code": "D2",
                "total_paid_amount": 100.0,
            },
            {
                "patient_id": "b",
                "diagnosis_code": "D3",
                "total_paid_amount": 50.0,
            },
        ],
        x_field="patient_id",
        metric="total_paid_amount",
        series=[{"field": "total_paid_amount", "name": "Total Paid", "format": "currency"}],
        n=10,
        other_label="Other",
        result_context={
            "label": "Comorbidities",
            "row_grain_hint": "Rows are diagnosis-level detail.",
        },
    )

    assert chart_data == [
        {"patient_id": "a", "total_paid_amount": 100.0},
        {"patient_id": "b", "total_paid_amount": 50.0},
    ]
    assert "guardrail" in note


def test_chart_generator_does_not_dedupe_equal_values_without_repeated_grain_hint():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    chart_data, note = generator._agg_top_n(
        data=[
            {"patient_id": "a", "paid_amount": 100.0},
            {"patient_id": "a", "paid_amount": 100.0},
            {"patient_id": "b", "paid_amount": 50.0},
        ],
        x_field="patient_id",
        metric="paid_amount",
        series=[{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
        n=10,
        other_label="Other",
        result_context={"label": "Paid amounts"},
    )

    assert chart_data == [
        {"patient_id": "a", "paid_amount": 200.0},
        {"patient_id": "b", "paid_amount": 50.0},
    ]
    assert "guardrail" not in note


def test_chart_generator_grouped_top_n_dedupes_repeated_metrics_within_groups():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    chart_data, note = generator._agg_top_n(
        data=[
            {
                "patient_id": "a",
                "benefit_type": "Medical",
                "total_paid_amount": 100.0,
            },
            {
                "patient_id": "a",
                "benefit_type": "Medical",
                "total_paid_amount": 100.0,
            },
            {
                "patient_id": "a",
                "benefit_type": "Rx",
                "total_paid_amount": 40.0,
            },
            {
                "patient_id": "a",
                "benefit_type": "Rx",
                "total_paid_amount": 40.0,
            },
        ],
        x_field="patient_id",
        metric="total_paid_amount",
        series=[{"field": "total_paid_amount", "name": "Total Paid", "format": "currency"}],
        n=10,
        other_label="Other",
        result_context={
            "label": "Coverage mix",
            "row_grain_hint": "Rows are repeated coverage-level detail.",
        },
        group_field="benefit_type",
    )

    assert chart_data == [
        {"patient_id": "a", "benefit_type": "Medical", "total_paid_amount": 100.0},
        {"patient_id": "a", "benefit_type": "Rx", "total_paid_amount": 40.0},
    ]
    assert "guardrail" in note


def test_chart_generator_prompt_lists_supported_capabilities():
    generator = ChartGenerator(llm=StubLlm("{}"))  # type: ignore[arg-type]

    prompt = generator._build_prompt(
        columns=["service_month", "paid_amount", "claim_count"],
        data=[{"service_month": "2024-01-01", "paid_amount": 10, "claim_count": 1}],
        original_query="Show utilization trends",
        result_context={"label": "Utilization"},
    )

    for chart_type in SUPPORTED_CHART_TYPES:
        assert chart_type in prompt
    for transform_type in SUPPORTED_TRANSFORMS:
        assert transform_type in prompt


def test_chart_generator_sql_summary_prefers_outer_cte_query_shape():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]
    _parse_error, exp_module, parse_one_fn = _load_sqlglot()
    if parse_one_fn is None or exp_module is None:
        pytest.skip("sqlglot is not importable in this pytest harness")

    summary = generator._summarize_sql_expression(
        parse_one_fn(
        """
        WITH member_totals AS (
            SELECT patient_id, SUM(paid_amount) AS total_paid
            FROM claims
            GROUP BY patient_id
        ),
        ranked_members AS (
            SELECT patient_id, total_paid
            FROM member_totals
            WHERE total_paid > 100
        )
        SELECT patient_id, total_paid
        FROM ranked_members
        ORDER BY total_paid DESC
        LIMIT 10
        """
        ),
        exp_module,
    )

    assert "2 CTEs" in summary
    assert "ordered by total_paid DESC" in summary
    assert "limit 10" in summary
    assert "grouped by patient_id" not in summary


def test_chart_generator_sql_summary_handles_union_all():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]
    _parse_error, exp_module, parse_one_fn = _load_sqlglot()
    if parse_one_fn is None or exp_module is None:
        pytest.skip("sqlglot is not importable in this pytest harness")

    summary = generator._summarize_sql_expression(
        parse_one_fn(
        """
        SELECT service_year, paid_amount
        FROM medical_claims
        UNION ALL
        SELECT service_year, paid_amount
        FROM pharmacy_claims
        ORDER BY service_year
        LIMIT 25
        """
        ),
        exp_module,
    )

    assert "combines 2 SELECT branches via UNION ALL" in summary
    assert "ordered by service_year" in summary
    assert "limit 25" in summary


def test_chart_generator_without_llm_prefers_time_series_rollup():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_date", "paid_amount", "benefit_type"],
        data=[
            {"service_date": "2024-01-01", "paid_amount": 10, "benefit_type": "Medical"},
            {"service_date": "2024-01-15", "paid_amount": 15, "benefit_type": "Rx"},
            {"service_date": "2024-02-01", "paid_amount": 25, "benefit_type": "Medical"},
        ],
        original_query="Show monthly spend trends",
        result_context={"label": "Monthly spend"},
    )

    assert payload is not None
    assert payload["config"]["chartType"] in {"line", "stackedArea"}
    assert payload["config"]["transform"]["type"] == "timeBucket"
    assert payload["meta"]["source"] == "auto"
    assert payload["meta"]["confidence"] is not None


def test_chart_generator_without_llm_uses_histogram_for_id_plus_numeric_preview():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "age"],
        data=[
            {"patient_id": "a", "age": 7},
            {"patient_id": "b", "age": 9},
            {"patient_id": "c", "age": 11},
            {"patient_id": "d", "age": 11},
            {"patient_id": "e", "age": 13},
        ],
        original_query="Show pediatric members",
        result_context={"label": "Pediatric members"},
    )

    assert payload is not None
    assert payload["config"]["transform"]["type"] == "histogram"
    assert payload["config"]["xAxisField"] == "bucket"


def test_chart_generator_without_llm_avoids_code_description_grouping():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["diagnosis_code", "Description", "total_diagnosis_count", "unique_patient_count"],
        data=[
            {
                "diagnosis_code": "Z00129",
                "Description": "Routine child health examination without abnormal findings",
                "total_diagnosis_count": 1160,
                "unique_patient_count": 202,
            },
            {
                "diagnosis_code": "Z23",
                "Description": "Encounter for immunization",
                "total_diagnosis_count": 969,
                "unique_patient_count": 197,
            },
            {
                "diagnosis_code": "J069",
                "Description": "Acute upper respiratory infection, unspecified",
                "total_diagnosis_count": 627,
                "unique_patient_count": 151,
            },
        ],
        original_query="Group-level diagnosis distribution",
        result_context={"label": "Diagnosis distribution"},
    )

    assert payload is not None
    assert payload["config"]["groupByField"] is None
    assert payload["config"]["chartType"] in {"bar", "dualAxis"}


def test_chart_generator_serializes_shared_llm_access():
    llm = NonConcurrentLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Age",
          "xAxisField": "patient_id",
          "series": [{"field": "age", "name": "Age", "format": "number"}]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    def run_once():
        return generator.generate_chart(
            columns=["patient_id", "age"],
            data=[
                {"patient_id": "a", "age": 7},
                {"patient_id": "b", "age": 9},
            ],
            original_query="Show ages",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        payloads = list(pool.map(lambda _i: run_once(), range(4)))

    assert all(payload is not None for payload in payloads)
    assert llm.max_active == 1


def test_build_visualization_workspace_payload_groups_table_and_chart():
    entry = {
        "index": 0,
        "label": "Monthly spend",
        "sql_explanation": "Aggregated paid amount by month.",
        "row_grain_hint": "Rows are claim-level detail.",
        "result": {
            "success": True,
            "columns": ["service_month", "paid_amount"],
            "result": [
                {"service_month": "2024-01", "paid_amount": 100},
                {"service_month": "2024-02", "paid_amount": 150},
            ],
        },
    }
    chart_payload = {
        "config": {
            "chartType": "line",
            "title": "Monthly spend",
            "xAxisField": "service_month",
            "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
        },
        "chartData": [
            {"service_month": "2024-01", "paid_amount": 100},
            {"service_month": "2024-02", "paid_amount": 150},
        ],
        "downloadData": [
            {"service_month": "2024-01", "paid_amount": 100},
            {"service_month": "2024-02", "paid_amount": 150},
        ],
        "meta": {"source": "auto"},
    }

    workspace = _build_visualization_workspace_payload(
        entry=entry,
        chart_payload=chart_payload,
        preview_rows=entry["result"]["result"],
        full_rows=entry["result"]["result"],
        source_row_count=2,
        total_entries=1,
    )

    assert workspace["workspaceId"] == "query-1"
    assert workspace["table"]["title"] == "Monthly spend"
    assert workspace["charts"][0]["meta"]["sourceTableId"] == "query-1"
    assert workspace["description"] == "Aggregated paid amount by month."
    assert workspace["sourceMeta"]["sqlExplanation"] is None

def test_chart_generator_frequency_rewrites_to_count_series():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Diagnosis Frequency",
          "xAxisField": "diagnosis_code",
          "series": [],
          "transform": {"type": "frequency", "field": "diagnosis_code", "topN": 5}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["diagnosis_code"],
        data=[
            {"diagnosis_code": "I10"},
            {"diagnosis_code": "I10"},
            {"diagnosis_code": "E11"},
        ],
        original_query="Top diagnoses",
    )

    assert payload is not None
    assert payload["config"]["series"] == [
        {"field": "count", "name": "Count", "format": "number", "chartType": None, "axis": "primary"}
    ]
    assert payload["chartData"][0]["diagnosis_code"] == "I10"
    assert payload["chartData"][0]["count"] == 2


def test_chart_generator_time_bucket_rolls_up_monthly_values():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "line",
          "title": "Monthly Spend",
          "xAxisField": "service_date",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "timeBucket", "field": "service_date", "bucket": "month", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_date", "paid_amount"],
        data=[
            {"service_date": "2024-01-01", "paid_amount": 10},
            {"service_date": "2024-01-15", "paid_amount": 15},
            {"service_date": "2024-02-01", "paid_amount": 25},
        ],
        original_query="Monthly spend",
    )

    assert payload is not None
    assert payload["chartData"] == [
        {"service_date": "2024-01", "paid_amount": 25.0},
        {"service_date": "2024-02", "paid_amount": 25.0},
    ]
    assert "Bucketed" in payload["aggregationNote"]


def test_chart_generator_histogram_builds_count_bins():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Paid Amount Distribution",
          "xAxisField": "paid_amount",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "histogram", "field": "paid_amount", "bins": 5}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["paid_amount"],
        data=[{"paid_amount": value} for value in (10, 12, 15, 18, 20, 25, 30)],
        original_query="Distribution of paid amount",
    )

    assert payload is not None
    assert payload["config"]["xAxisField"] == "bucket"
    assert payload["config"]["series"][0]["field"] == "count"
    assert len(payload["chartData"]) == 5
    assert sum(row["count"] for row in payload["chartData"]) == 7


def test_chart_generator_histogram_ignores_nan_values():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Paid Amount Distribution",
          "xAxisField": "paid_amount",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "histogram", "field": "paid_amount", "bins": 4}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["paid_amount"],
        data=[{"paid_amount": value} for value in (10, 12, float("nan"), 18, 20)],
        original_query="Distribution of paid amount",
    )

    assert payload is not None
    assert sum(row["count"] for row in payload["chartData"]) == 4


def test_chart_generator_histogram_supports_count_distinct_metric():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Distinct Patients by Age Bucket",
          "xAxisField": "age",
          "series": [{"field": "patient_id", "name": "Patient", "format": "number"}],
          "transform": {"type": "histogram", "field": "age", "bins": 2, "metric": "patient_id", "function": "count_distinct"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "patient_id"],
        data=[
            {"age": 10, "patient_id": "A"},
            {"age": 12, "patient_id": "B"},
            {"age": 20, "patient_id": "A"},
            {"age": 22, "patient_id": "C"},
        ],
        original_query="Distinct patients by age bucket",
    )

    assert payload is not None
    assert payload["config"]["xAxisField"] == "bucket"
    assert payload["config"]["series"][0]["field"] == "patient_id"
    assert payload["config"]["transform"]["function"] == "count_distinct"
    assert sum(row["patient_id"] for row in payload["chartData"]) == 4


def test_chart_generator_llm_numeric_x_axis_is_bucketed_to_histogram():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Age Spend",
          "xAxisField": "age",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": null
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "paid_amount"],
        data=[
            {"age": 5, "paid_amount": 10},
            {"age": 8, "paid_amount": 15},
            {"age": 12, "paid_amount": 20},
            {"age": 17, "paid_amount": 25},
            {"age": 21, "paid_amount": 30},
            {"age": 26, "paid_amount": 35},
            {"age": 34, "paid_amount": 40},
            {"age": 42, "paid_amount": 45},
        ],
        original_query="Show spend by age",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "bar"
    assert payload["config"]["transform"]["type"] == "histogram"
    assert payload["config"]["xAxisField"] == "bucket"
    assert payload["config"]["series"][0]["field"] == "count"


def test_chart_generator_histogram_remaps_x_sort_to_bucket_boundaries():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "bar",
          "title": "Age Distribution",
          "xAxisField": "age",
          "sortBy": {"field": "age", "order": "desc"},
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "histogram", "field": "age", "bins": 4}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "paid_amount"],
        data=[
            {"age": 5, "paid_amount": 10},
            {"age": 10, "paid_amount": 15},
            {"age": 20, "paid_amount": 20},
            {"age": 40, "paid_amount": 25},
        ],
        original_query="Distribution of age",
    )

    assert payload is not None
    assert payload["config"]["sortBy"] == {"field": "bucketStart", "order": "desc"}
    bucket_starts = [row["bucketStart"] for row in payload["chartData"]]
    assert bucket_starts == sorted(bucket_starts, reverse=True)


def test_chart_generator_heatmap_builds_dense_matrix_cells():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "heatmap",
          "title": "State by Benefit",
          "xAxisField": "patient_state",
          "groupByField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "heatmap", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_state", "benefit_type", "paid_amount"],
        data=[
            {"patient_state": "MI", "benefit_type": "Medical", "paid_amount": 100},
            {"patient_state": "MI", "benefit_type": "Rx", "paid_amount": 50},
            {"patient_state": "TX", "benefit_type": "Medical", "paid_amount": 30},
        ],
        original_query="Heatmap of spend by state and benefit",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "heatmap"
    assert payload["config"]["yAxisField"] == "benefit_type"
    assert len(payload["chartData"]) == 4
    assert payload["chartData"][-1] == {
        "patient_state": "TX",
        "benefit_type": "Rx",
        "paid_amount": 0.0,
    }


def test_chart_generator_llm_plottable_string_false_falls_back_to_heuristic():
    llm = StubLlm(
        """
        {
          "plottable": "false",
          "chartType": "bar",
          "title": "Should not plot"
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_month", "paid_amount"],
        data=[
            {"service_month": "2024-01", "paid_amount": 100},
            {"service_month": "2024-02", "paid_amount": 150},
        ],
        original_query="Monthly spend",
    )

    assert payload is not None
    assert payload["meta"]["intentSource"] == "heuristic"


def test_chart_generator_llm_json_extraction_ignores_trailing_prose():
    llm = StubLlm(
        """
        {"plottable": true, "chartType": "bar", "title": "Monthly spend", "xAxisField": "service_month", "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}]}

        Additional explanation after the JSON block.
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_month", "paid_amount"],
        data=[
            {"service_month": "2024-01", "paid_amount": 100},
            {"service_month": "2024-02", "paid_amount": 150},
        ],
        original_query="Monthly spend",
    )

    assert payload is not None
    assert payload["meta"]["intentSource"] == "llm"


def test_chart_generator_llm_parse_failure_uses_heuristic_intent_source():
    llm = StubLlm("{not valid json")
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_month", "paid_amount"],
        data=[
            {"service_month": "2024-01", "paid_amount": 100},
            {"service_month": "2024-02", "paid_amount": 150},
        ],
        original_query="Monthly spend",
    )

    assert payload is not None
    assert payload["meta"]["intentSource"] == "heuristic"


def test_chart_generator_heatmap_infers_transform_when_model_omits_one():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "heatmap",
          "title": "State by Benefit",
          "xAxisField": "patient_state",
          "groupByField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_state", "benefit_type", "paid_amount"],
        data=[
            {"patient_state": "MI", "benefit_type": "Medical", "paid_amount": 100},
            {"patient_state": "TX", "benefit_type": "Rx", "paid_amount": 50},
        ],
        original_query="Heatmap of spend by state and benefit",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "heatmap"
    assert payload["config"]["transform"]["type"] == "heatmap"
    assert payload["config"]["yAxisField"] == "benefit_type"
    assert len(payload["chartData"]) == 4


def test_chart_generator_heatmap_aligns_groupby_with_resolved_y_axis_field():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "heatmap",
          "title": "State by Channel",
          "xAxisField": "patient_state",
          "groupByField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "heatmap", "yField": "channel", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_state", "benefit_type", "channel", "paid_amount"],
        data=[
            {"patient_state": "MI", "benefit_type": "Medical", "channel": "A", "paid_amount": 100},
            {"patient_state": "MI", "benefit_type": "Medical", "channel": "B", "paid_amount": 50},
        ],
        original_query="Heatmap of spend by state and channel",
    )

    assert payload is not None
    assert payload["config"]["yAxisField"] == "channel"
    assert payload["config"]["groupByField"] == "channel"


def test_chart_generator_heatmap_sorts_x_and_y_axes_independently():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "heatmap",
          "title": "Year by Benefit",
          "xAxisField": "service_year",
          "groupByField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {
            "type": "heatmap",
            "metric": "paid_amount",
            "function": "sum",
            "xOrder": "desc",
            "yOrder": "desc"
          }
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_year", "benefit_type", "paid_amount"],
        data=[
            {"service_year": 2, "benefit_type": "A", "paid_amount": 20},
            {"service_year": 10, "benefit_type": "B", "paid_amount": 100},
            {"service_year": 2, "benefit_type": "C", "paid_amount": 40},
            {"service_year": 10, "benefit_type": "A", "paid_amount": 10},
        ],
        original_query="Heatmap of spend by year and benefit",
    )

    assert payload is not None
    assert payload["chartData"] == [
        {"service_year": "10", "benefit_type": "C", "paid_amount": 0.0},
        {"service_year": "10", "benefit_type": "B", "paid_amount": 100.0},
        {"service_year": "10", "benefit_type": "A", "paid_amount": 10.0},
        {"service_year": "2", "benefit_type": "C", "paid_amount": 40.0},
        {"service_year": "2", "benefit_type": "B", "paid_amount": 0.0},
        {"service_year": "2", "benefit_type": "A", "paid_amount": 20.0},
    ]


def test_chart_generator_heatmap_rejects_metric_based_sortby():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "heatmap",
          "title": "Year by Benefit",
          "xAxisField": "service_year",
          "groupByField": "benefit_type",
          "sortBy": {"field": "paid_amount", "order": "desc"},
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "heatmap", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_year", "benefit_type", "paid_amount"],
        data=[
            {"service_year": 2, "benefit_type": "B", "paid_amount": 20},
            {"service_year": 10, "benefit_type": "A", "paid_amount": 100},
        ],
        original_query="Heatmap of spend by year and benefit",
    )

    assert payload is not None
    assert payload["config"]["sortBy"] is None
    assert payload["chartData"] == [
        {"service_year": "2", "benefit_type": "A", "paid_amount": 0.0},
        {"service_year": "2", "benefit_type": "B", "paid_amount": 20.0},
        {"service_year": "10", "benefit_type": "A", "paid_amount": 100.0},
        {"service_year": "10", "benefit_type": "B", "paid_amount": 0.0},
    ]


def test_chart_generator_large_heatmap_trims_full_matrix_not_partial_cells():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "heatmap",
          "title": "Large Heatmap",
          "xAxisField": "service_year",
          "groupByField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "heatmap", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_year", "benefit_type", "paid_amount"],
        data=[
            {"service_year": f"Y{index:02d}", "benefit_type": f"B{index:02d}", "paid_amount": float(index)}
            for index in range(30)
        ],
        original_query="Heatmap of spend by year and benefit",
    )

    assert payload is not None
    x_values = {row["service_year"] for row in payload["chartData"]}
    y_values = {row["benefit_type"] for row in payload["chartData"]}
    assert len(payload["chartData"]) <= 500
    assert len(payload["chartData"]) == len(x_values) * len(y_values)
    assert "Trimmed heatmap matrix" in (payload["aggregationNote"] or "")


def test_chart_generator_time_bucket_respects_x_axis_sort_order():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "line",
          "title": "Monthly Spend",
          "xAxisField": "service_date",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "sortBy": {"field": "service_date", "order": "desc"},
          "transform": {"type": "timeBucket", "field": "service_date", "bucket": "month", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_date", "paid_amount"],
        data=[
            {"service_date": "2024-01-10", "paid_amount": 10},
            {"service_date": "2024-03-02", "paid_amount": 30},
            {"service_date": "2024-02-05", "paid_amount": 20},
        ],
        original_query="Monthly spend trend",
    )

    assert payload is not None
    assert [row["service_date"] for row in payload["chartData"]] == ["2024-03", "2024-02", "2024-01"]


def test_chart_generator_time_bucket_reports_skipped_unparseable_dates():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "line",
          "title": "Monthly spend",
          "xAxisField": "service_date",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "timeBucket", "field": "service_date", "bucket": "month", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_date", "paid_amount"],
        data=[
            {"service_date": "2024-01-01", "paid_amount": 10},
            {"service_date": None, "paid_amount": 15},
            {"service_date": "2024-02-01", "paid_amount": 25},
        ],
        original_query="Monthly spend",
    )

    assert payload is not None
    assert "skipped 1 rows with unparseable service_date values" in (payload["aggregationNote"] or "")


def test_chart_generator_grouped_rows_use_global_group_sort_order():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    sorted_rows = generator._sort_chart_rows(
        [
            {"service_month": "2024-01", "benefit_type": "Rx", "paid_amount": 20},
            {"service_month": "2024-01", "benefit_type": "Medical", "paid_amount": 10},
            {"service_month": "2024-02", "benefit_type": "Medical", "paid_amount": 30},
            {"service_month": "2024-02", "benefit_type": "Rx", "paid_amount": 40},
        ],
        {
            "chartType": "stackedBar",
            "xAxisField": "service_month",
            "groupByField": "benefit_type",
            "sortBy": {"field": "benefit_type", "order": "desc"},
        },
    )

    assert [(row["service_month"], row["benefit_type"]) for row in sorted_rows] == [
        ("2024-01", "Rx"),
        ("2024-01", "Medical"),
        ("2024-02", "Rx"),
        ("2024-02", "Medical"),
    ]


def test_chart_generator_normalized_layout_aggregates_repeated_grain_before_percentages():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "normalizedStackedBar",
          "title": "Benefit Mix",
          "xAxisField": "service_year",
          "groupByField": "benefit_type",
          "layout": "normalized",
          "series": [{"field": "total_paid_amount", "name": "Total Paid Amount", "format": "currency"}],
          "transform": null
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_year", "benefit_type", "total_paid_amount"],
        data=[
            {"service_year": "2024", "benefit_type": "Medical", "total_paid_amount": 100},
            {"service_year": "2024", "benefit_type": "Medical", "total_paid_amount": 100},
            {"service_year": "2024", "benefit_type": "Rx", "total_paid_amount": 40},
            {"service_year": "2024", "benefit_type": "Rx", "total_paid_amount": 40},
        ],
        original_query="Normalized benefit mix",
        result_context={"row_grain_hint": "Rows are repeated detail-level records."},
    )

    assert payload is not None
    assert payload["config"]["layout"] == "normalized"
    assert payload["chartData"] == [
        {"service_year": "2024", "benefit_type": "Medical", "total_paid_amount": 71.4286},
        {"service_year": "2024", "benefit_type": "Rx", "total_paid_amount": 28.5714},
    ]


def test_chart_generator_boxplot_respects_boxplot_sort_fields():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "boxplot",
          "title": "Spend Distribution",
          "xAxisField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "sortBy": {"field": "median", "order": "desc"},
          "transform": {"type": "boxplot", "field": "paid_amount"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "paid_amount"],
        data=[
            {"benefit_type": "Medical", "paid_amount": 10},
            {"benefit_type": "Medical", "paid_amount": 20},
            {"benefit_type": "Rx", "paid_amount": 50},
            {"benefit_type": "Rx", "paid_amount": 60},
            {"benefit_type": "Dental", "paid_amount": 30},
            {"benefit_type": "Dental", "paid_amount": 40},
        ],
        original_query="Distribution of spend by benefit type",
    )

    assert payload is not None
    assert [row["benefit_type"] for row in payload["chartData"]] == ["Rx", "Dental", "Medical"]


def test_chart_generator_boxplot_rejects_source_metric_sortby():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "boxplot",
          "title": "Spend Distribution",
          "xAxisField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "sortBy": {"field": "paid_amount", "order": "desc"},
          "transform": {"type": "boxplot", "field": "paid_amount"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "paid_amount"],
        data=[
            {"benefit_type": "Medical", "paid_amount": 10},
            {"benefit_type": "Rx", "paid_amount": 50},
        ],
        original_query="Distribution of spend by benefit type",
    )

    assert payload is not None
    assert payload["config"]["sortBy"] is None


def test_chart_generator_delta_comparison_respects_explicit_delta_sort_order():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "deltaComparison",
          "title": "Year Over Year Change",
          "xAxisField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "sortBy": {"field": "delta", "order": "asc"},
          "transform": {"type": "deltaComparison", "entityField": "benefit_type", "periodField": "service_year", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "service_year", "paid_amount"],
        data=[
            {"benefit_type": "Medical", "service_year": 2023, "paid_amount": 100},
            {"benefit_type": "Medical", "service_year": 2024, "paid_amount": 80},
            {"benefit_type": "Rx", "service_year": 2023, "paid_amount": 100},
            {"benefit_type": "Rx", "service_year": 2024, "paid_amount": 120},
            {"benefit_type": "Dental", "service_year": 2023, "paid_amount": 100},
            {"benefit_type": "Dental", "service_year": 2024, "paid_amount": 100},
        ],
        original_query="Year over year change in spend by benefit type",
    )

    assert payload is not None
    assert [(row["benefit_type"], row["delta"]) for row in payload["chartData"]] == [
        ("Medical", -20.0),
        ("Dental", 0.0),
        ("Rx", 20.0),
    ]


def test_chart_generator_delta_comparison_respects_repeated_grain_guardrail():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "deltaComparison",
          "title": "Year Over Year Change",
          "xAxisField": "benefit_type",
          "series": [{"field": "total_paid_amount", "name": "Total Paid Amount", "format": "currency"}],
          "transform": {"type": "deltaComparison", "entityField": "benefit_type", "periodField": "service_year", "metric": "total_paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "service_year", "total_paid_amount"],
        data=[
            {"benefit_type": "Medical", "service_year": 2023, "total_paid_amount": 100},
            {"benefit_type": "Medical", "service_year": 2023, "total_paid_amount": 100},
            {"benefit_type": "Medical", "service_year": 2024, "total_paid_amount": 120},
            {"benefit_type": "Medical", "service_year": 2024, "total_paid_amount": 120},
        ],
        original_query="Year over year change in spend by benefit type",
        result_context={"row_grain_hint": "Rows are repeated detail-level records."},
    )

    assert payload is not None
    assert payload["chartData"] == [
        {
            "benefit_type": "Medical",
            "startLabel": "2023",
            "endLabel": "2024",
            "startValue": 100.0,
            "endValue": 120.0,
            "delta": 20.0,
        }
    ]


def test_chart_generator_delta_comparison_uses_period_aware_ordering():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "deltaComparison",
          "title": "Month Over Month Change",
          "xAxisField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "deltaComparison", "entityField": "benefit_type", "periodField": "service_month", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "service_month", "paid_amount"],
        data=[
            {"benefit_type": "Medical", "service_month": "2024-2", "paid_amount": 100},
            {"benefit_type": "Medical", "service_month": "2024-10", "paid_amount": 140},
        ],
        original_query="Month over month change in spend by benefit type",
    )

    assert payload is not None
    assert payload["config"]["compareLabels"] == ["2024-2", "2024-10"]
    assert payload["chartData"][0]["delta"] == 40.0


def test_chart_generator_delta_comparison_uses_latest_two_periods():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "deltaComparison",
          "title": "Month Over Month Change",
          "xAxisField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "deltaComparison", "entityField": "benefit_type", "periodField": "service_month", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "service_month", "paid_amount"],
        data=[
            {"benefit_type": "Medical", "service_month": "2024-01", "paid_amount": 80},
            {"benefit_type": "Medical", "service_month": "2024-02", "paid_amount": 100},
            {"benefit_type": "Medical", "service_month": "2024-03", "paid_amount": 140},
        ],
        original_query="Month over month change in spend by benefit type",
    )

    assert payload is not None
    assert payload["config"]["compareLabels"] == ["2024-02", "2024-03"]
    assert payload["chartData"][0]["startValue"] == 100.0
    assert payload["chartData"][0]["delta"] == 40.0


def test_chart_generator_delta_comparison_excludes_entities_missing_selected_period():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "deltaComparison",
          "title": "Month Over Month Change",
          "xAxisField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "deltaComparison", "entityField": "benefit_type", "periodField": "service_month", "metric": "paid_amount", "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "service_month", "paid_amount"],
        data=[
            {"benefit_type": "Medical", "service_month": "2024-02", "paid_amount": 100},
            {"benefit_type": "Medical", "service_month": "2024-03", "paid_amount": 140},
            {"benefit_type": "Rx", "service_month": "2024-02", "paid_amount": 50},
        ],
        original_query="Month over month change in spend by benefit type",
    )

    assert payload is not None
    assert [row["benefit_type"] for row in payload["chartData"]] == ["Medical"]
    assert "excluded 1 entities without both periods" in (payload["aggregationNote"] or "")


def test_chart_generator_delta_comparison_topn_respects_explicit_sort_selection():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "deltaComparison",
          "title": "Year Over Year Change",
          "xAxisField": "benefit_type",
          "sortBy": {"field": "delta", "order": "asc"},
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "deltaComparison", "entityField": "benefit_type", "periodField": "service_year", "metric": "paid_amount", "function": "sum", "topN": 2}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["benefit_type", "service_year", "paid_amount"],
        data=[
            {"benefit_type": "A", "service_year": 2023, "paid_amount": 100},
            {"benefit_type": "A", "service_year": 2024, "paid_amount": 50},
            {"benefit_type": "B", "service_year": 2023, "paid_amount": 100},
            {"benefit_type": "B", "service_year": 2024, "paid_amount": 110},
            {"benefit_type": "C", "service_year": 2023, "paid_amount": 100},
            {"benefit_type": "C", "service_year": 2024, "paid_amount": 130},
        ],
        original_query="Year over year change in spend by benefit type",
    )

    assert payload is not None
    assert [(row["benefit_type"], row["delta"]) for row in payload["chartData"]] == [
        ("A", -50.0),
        ("B", 10.0),
    ]


def test_chart_generator_scatter_respects_continuous_axis_sort_order():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "scatter",
          "title": "Age vs Spend",
          "xAxisField": "age",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "sortBy": {"field": "paid_amount", "order": "asc"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "paid_amount"],
        data=[
            {"age": 55, "paid_amount": 400},
            {"age": 40, "paid_amount": 150},
            {"age": 48, "paid_amount": 250},
        ],
        original_query="Relationship between age and spend",
    )

    assert payload is not None
    assert [(row["age"], row["paid_amount"]) for row in payload["chartData"]] == [
        (40, 150),
        (48, 250),
        (55, 400),
    ]


def test_chart_generator_without_llm_sorts_scatter_by_continuous_x_axis():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "paid_amount"],
        data=[
            {"age": 55, "paid_amount": 400},
            {"age": 40, "paid_amount": 150},
            {"age": 48, "paid_amount": 250},
        ],
        original_query="Compare age versus paid amount",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "scatter"
    assert payload["config"]["sortBy"] == {"field": "age", "order": "asc"}
    assert [row["age"] for row in payload["chartData"]] == [40, 48, 55]
    assert payload["meta"]["intentSource"] == "heuristic"


def test_chart_generator_scatter_keeps_numeric_z_axis_field():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "scatter",
          "title": "Age vs Spend",
          "xAxisField": "age",
          "zAxisField": "claim_count",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "paid_amount", "claim_count"],
        data=[
            {"age": 40, "paid_amount": 150, "claim_count": 3},
            {"age": 48, "paid_amount": 250, "claim_count": 5},
        ],
        original_query="Relationship between age and spend",
    )

    assert payload is not None
    assert payload["config"]["zAxisField"] == "claim_count"


def test_chart_generator_without_llm_adds_scatter_bubble_size_when_available():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["age", "paid_amount", "claim_count"],
        data=[
            {"age": 55, "paid_amount": 400, "claim_count": 8},
            {"age": 40, "paid_amount": 150, "claim_count": 3},
            {"age": 48, "paid_amount": 250, "claim_count": 5},
        ],
        original_query="Compare age versus paid amount",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "scatter"
    assert payload["config"]["zAxisField"] is not None
    assert payload["config"]["zAxisField"] != payload["config"]["xAxisField"]
    assert payload["config"]["zAxisField"] != payload["config"]["series"][0]["field"]


def test_chart_generator_business_insight_aggregates_grouped_categories():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "stackedBar",
          "title": "Yearly Spend by Benefit",
          "xAxisField": "service_year",
          "groupByField": "benefit_type",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_year", "benefit_type", "paid_amount"],
        data=[
            {"service_year": "2024", "benefit_type": "Medical", "paid_amount": 60},
            {"service_year": "2024", "benefit_type": "Rx", "paid_amount": 60},
            {"service_year": "2023", "benefit_type": "Medical", "paid_amount": 100},
        ],
        original_query="Yearly spend by benefit",
    )

    assert payload is not None
    assert payload["meta"]["businessInsight"] == "2024 leads on Paid Amount at 120."


def test_chart_generator_dual_axis_keeps_allowlisted_series_metadata():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "dualAxis",
          "title": "Claims vs Spend",
          "xAxisField": "service_month",
          "series": [
            {"field": "claim_count", "name": "Claim Count", "format": "number", "chartType": "bar", "axis": "primary"},
            {"field": "paid_amount", "name": "Paid Amount", "format": "currency", "chartType": "line", "axis": "secondary"}
          ]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["service_month", "claim_count", "paid_amount"],
        data=[
            {"service_month": "2024-01", "claim_count": 10, "paid_amount": 1000},
            {"service_month": "2024-02", "claim_count": 20, "paid_amount": 1800},
        ],
        original_query="Compare volume and spend",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "dualAxis"
    assert payload["config"]["series"][1]["axis"] == "secondary"


def test_chart_generator_ranking_slope_aligns_two_periods():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "rankingSlope",
          "title": "Member rank shift",
          "xAxisField": "patient_id",
          "groupByField": "service_year",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "rankingSlope", "metric": "paid_amount", "periodField": "service_year", "topN": 5, "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "service_year", "paid_amount"],
        data=[
            {"patient_id": "a", "service_year": "2023", "paid_amount": 100},
            {"patient_id": "a", "service_year": "2024", "paid_amount": 80},
            {"patient_id": "b", "service_year": "2023", "paid_amount": 90},
            {"patient_id": "b", "service_year": "2024", "paid_amount": 120},
        ],
        original_query="How did spend rank change by member?",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "rankingSlope"
    assert payload["config"]["transform"]["compareLabels"] == ["2023", "2024"]
    assert {"startRank", "endRank"} <= set(payload["chartData"][0].keys())


def test_chart_generator_ranking_slope_infers_transform_when_model_omits_one():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "rankingSlope",
          "title": "Member rank shift",
          "xAxisField": "patient_id",
          "groupByField": "service_year",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "service_year", "paid_amount"],
        data=[
            {"patient_id": "a", "service_year": "2023", "paid_amount": 100},
            {"patient_id": "a", "service_year": "2024", "paid_amount": 80},
            {"patient_id": "b", "service_year": "2023", "paid_amount": 90},
            {"patient_id": "b", "service_year": "2024", "paid_amount": 120},
        ],
        original_query="How did spend rank change by member?",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "rankingSlope"
    assert payload["config"]["transform"]["type"] == "rankingSlope"
    assert payload["config"]["transform"]["compareLabels"] == ["2023", "2024"]


def test_chart_generator_ranking_slope_without_metric_still_emits_series():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "rankingSlope",
          "title": "Member rank shift",
          "xAxisField": "patient_id",
          "groupByField": "service_year",
          "series": [],
          "transform": {"type": "rankingSlope", "periodField": "service_year", "topN": 5, "function": "count"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "service_year"],
        data=[
            {"patient_id": "a", "service_year": "2023"},
            {"patient_id": "a", "service_year": "2024"},
            {"patient_id": "b", "service_year": "2023"},
            {"patient_id": "b", "service_year": "2024"},
        ],
        original_query="How member rankings changed year over year",
    )

    assert payload is not None
    assert payload["config"]["series"]


def test_chart_generator_ranking_slope_is_not_rewritten_to_histogram_for_identifier_x_axis():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "rankingSlope",
          "title": "Member rank shift",
          "xAxisField": "patient_id",
          "groupByField": "service_year",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}]
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "service_year", "paid_amount"],
        data=[
            {"patient_id": f"member-{index}", "service_year": "2023", "paid_amount": float(index * 11 + 5)}
            for index in range(10)
        ] + [
            {"patient_id": f"member-{index}", "service_year": "2024", "paid_amount": float(index * 13 + 7)}
            for index in range(10)
        ],
        original_query="How did spend rank change by member?",
    )

    assert payload is not None
    assert payload["config"]["chartType"] == "rankingSlope"
    assert payload["config"]["transform"]["type"] == "rankingSlope"


def test_chart_generator_ranking_slope_uses_shared_ranks_for_ties():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "rankingSlope",
          "title": "Member rank shift",
          "xAxisField": "patient_id",
          "groupByField": "service_year",
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "rankingSlope", "metric": "paid_amount", "periodField": "service_year", "topN": 5, "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "service_year", "paid_amount"],
        data=[
            {"patient_id": "a", "service_year": "2023", "paid_amount": 100},
            {"patient_id": "b", "service_year": "2023", "paid_amount": 100},
            {"patient_id": "c", "service_year": "2023", "paid_amount": 90},
            {"patient_id": "a", "service_year": "2024", "paid_amount": 80},
            {"patient_id": "b", "service_year": "2024", "paid_amount": 80},
            {"patient_id": "c", "service_year": "2024", "paid_amount": 120},
        ],
        original_query="How did spend rank change by member?",
    )

    assert payload is not None
    by_member = {row["patient_id"]: row for row in payload["chartData"]}
    assert by_member["a"]["startRank"] == 1
    assert by_member["b"]["startRank"] == 1
    assert by_member["a"]["endRank"] == 2
    assert by_member["b"]["endRank"] == 2


def test_chart_generator_ranking_slope_respects_explicit_delta_sort_order():
    llm = StubLlm(
        """
        {
          "plottable": true,
          "chartType": "rankingSlope",
          "title": "Member rank shift",
          "xAxisField": "patient_id",
          "sortBy": {"field": "delta", "order": "asc"},
          "series": [{"field": "paid_amount", "name": "Paid Amount", "format": "currency"}],
          "transform": {"type": "rankingSlope", "metric": "paid_amount", "periodField": "service_year", "topN": 3, "function": "sum"}
        }
        """
    )
    generator = ChartGenerator(llm=llm)  # type: ignore[arg-type]

    payload = generator.generate_chart(
        columns=["patient_id", "service_year", "paid_amount"],
        data=[
            {"patient_id": "A", "service_year": 2023, "paid_amount": 100},
            {"patient_id": "A", "service_year": 2024, "paid_amount": 80},
            {"patient_id": "B", "service_year": 2023, "paid_amount": 100},
            {"patient_id": "B", "service_year": 2024, "paid_amount": 100},
            {"patient_id": "C", "service_year": 2023, "paid_amount": 100},
            {"patient_id": "C", "service_year": 2024, "paid_amount": 130},
        ],
        original_query="How member rankings changed year over year",
    )

    assert payload is not None
    assert payload["config"]["sortBy"] == {"field": "delta", "order": "asc"}
    assert [(row["patient_id"], row["delta"]) for row in payload["chartData"]] == [
        ("A", -20.0),
        ("B", 0.0),
        ("C", 30.0),
    ]


def test_detect_code_columns_skips_aggregate_metric_columns():
    llm = StubLlm(
        '[{"column":"distinct_cpt_codes","code_type":"CPT"},'
        '{"column":"diagnosis_code","code_type":"ICD10"}]'
    )

    detected = detect_code_columns(
        columns=["distinct_cpt_codes", "diagnosis_code"],
        sample_data=[
            {"distinct_cpt_codes": 578, "diagnosis_code": "C641"},
            {"distinct_cpt_codes": 223, "diagnosis_code": "I10"},
        ],
        llm=llm,
    )

    assert detected == [{"column": "diagnosis_code", "code_type": "ICD10"}]


def test_chart_generator_size_guard_enforces_transport_limit_after_dropping_download_data():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]
    long_text = "x" * 20_000
    payload = {
        "config": {
            "chartType": "bar",
            "title": "Oversized payload",
            "xAxisField": "category",
            "series": [{"field": "value", "name": "Value", "format": "number"}],
        },
        "chartData": [
            {"category": f"Category {index}", "value": index, "detail": long_text}
            for index in range(20)
        ],
        "downloadData": [
            {"category": f"Row {index}", "value": index, "detail": long_text}
            for index in range(20)
        ],
        "meta": {"source": "auto", "note": long_text},
    }

    guarded = generator._size_guard(payload)

    assert len(json.dumps(guarded).encode()) <= MAX_JSON_BYTES


def test_chart_generator_size_guard_handles_uuid_values():
    generator = ChartGenerator(llm=None)  # type: ignore[arg-type]
    payload = {
        "config": {
            "chartType": "bar",
            "title": "UUID payload",
            "xAxisField": "category",
            "series": [{"field": "value", "name": "Value", "format": "number"}],
        },
        "chartData": [{"category": uuid.uuid4(), "value": 1}],
        "downloadData": [{"category": uuid.uuid4(), "value": 1}],
        "meta": {"source": "auto"},
    }

    guarded = generator._size_guard(payload)

    assert len(json.dumps(guarded, default=str).encode()) <= MAX_JSON_BYTES
