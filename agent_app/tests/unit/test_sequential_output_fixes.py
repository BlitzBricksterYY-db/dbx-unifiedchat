from pathlib import Path
from types import SimpleNamespace
import types
import sys


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
    SUPPORTED_CHART_TYPES,
    SUPPORTED_TRANSFORMS,
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
        source_row_count=2,
        total_entries=1,
    )

    assert workspace["workspaceId"] == "query-1"
    assert workspace["table"]["title"] == "Monthly spend"
    assert workspace["charts"][0]["meta"]["sourceTableId"] == "query-1"
    assert workspace["sourceMeta"]["sqlExplanation"] == "Aggregated paid amount by month."

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
    assert payload["config"]["series"][0]["field"] == "count"
    assert len(payload["chartData"]) == 5
    assert sum(row["count"] for row in payload["chartData"]) == 7


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
    assert len(payload["chartData"]) == 3


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
