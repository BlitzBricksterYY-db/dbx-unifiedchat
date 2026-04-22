"""
Chart Generator for Multi-Agent System.

Three-stage pipeline:
  1. LLM generates a declarative intent spec from a sampled result set.
  2. Python validates and resolves that intent into deterministic chart data.
  3. Size guard ensures the final payload stays below the UI transport limit.
"""

import json
import logging
import math
import re
import threading
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)

MAX_CHART_POINTS = 500
MAX_DOWNLOAD_ROWS = 1000
MAX_JSON_BYTES = 200_000
SAMPLE_ROWS_FOR_LLM = 50
MAX_REFERENCE_LINES = 3

SUPPORTED_FORMATS = ("currency", "number", "percent")
SUPPORTED_CHART_TYPES = (
    "bar",
    "line",
    "scatter",
    "pie",
    "stackedBar",
    "normalizedStackedBar",
    "area",
    "stackedArea",
    "heatmap",
    "boxplot",
    "dualAxis",
    "rankingSlope",
    "deltaComparison",
)
SUPPORTED_LAYOUTS = ("grouped", "stacked", "normalized")
SUPPORTED_TRANSFORMS = (
    "topN",
    "frequency",
    "timeBucket",
    "histogram",
    "percentOfTotal",
    "heatmap",
    "boxplot",
    "rankingSlope",
    "deltaComparison",
)
SUPPORTED_TIME_BUCKETS = ("day", "week", "month", "quarter", "year")
SUPPORTED_AGGREGATIONS = ("sum", "avg", "count", "count_distinct", "min", "max")
SERIES_RENDER_TYPES = ("bar", "line", "area")
_DEDUPED_METRIC_TOKENS = (
    "total_",
    "avg_",
    "average_",
    "distinct_",
    "current_age",
    "year_of_birth",
    "enrollment_period_count",
)
_ID_FIELD_TOKENS = (
    "_id",
    " id",
    "uuid",
    "identifier",
    "member_id",
    "patient_id",
    "claim_id",
    "encounter_id",
)
_LOW_VALUE_NUMERIC_TOKENS = (
    "rank",
    "index",
    "sequence",
    "zip",
    "postal",
)
_CONTINUOUS_NUMERIC_TOKENS = (
    "age",
    "length",
    "duration",
    "days",
    "hours",
    "minutes",
    "score",
    "value",
    "amount",
    "cost",
    "paid",
    "charge",
    "price",
    "spend",
    "distance",
    "weight",
    "height",
    "bmi",
)
_DISCRETE_NUMERIC_CATEGORY_TOKENS = (
    "year",
    "month",
    "week",
    "quarter",
    "day_of_week",
    "weekday",
    "rank",
    "level",
    "tier",
)

CHART_CAPABILITY_MODEL: Dict[str, Dict[str, Any]] = {
    "bar": {"layouts": {"grouped", "stacked", "normalized"}},
    "line": {"layouts": {"grouped"}},
    "scatter": {"layouts": set()},
    "pie": {"layouts": set()},
    "stackedBar": {"layouts": {"stacked"}},
    "normalizedStackedBar": {"layouts": {"normalized"}},
    "area": {"layouts": {"grouped", "stacked"}},
    "stackedArea": {"layouts": {"stacked"}},
    "heatmap": {"layouts": set()},
    "boxplot": {"layouts": set()},
    "dualAxis": {"layouts": set()},
    "rankingSlope": {"layouts": set()},
    "deltaComparison": {"layouts": set()},
}


def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments while preserving quoted strings."""
    out: List[str] = []
    i = 0
    in_single = False
    in_double = False
    in_backtick = False
    length = len(sql)

    while i < length:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < length else ""

        if in_single:
            out.append(ch)
            if ch == "'" and nxt == "'":
                out.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        if in_backtick:
            out.append(ch)
            if ch == "`":
                in_backtick = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            i += 2
            while i < length and sql[i] not in "\r\n":
                i += 1
            continue

        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < length and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2 if i + 1 < length else 1
            continue

        out.append(ch)
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "`":
            in_backtick = True
        i += 1

    return "".join(out)


def _load_sqlglot() -> Tuple[type[Exception], Any, Any]:
    try:
        from sqlglot import ParseError, exp, parse_one  # pyright: ignore[reportMissingImports]

        return ParseError, exp, parse_one
    except ImportError:  # pragma: no cover - dependency is installed in normal environments
        return ValueError, None, None


class ChartGenerator:
    """Generates ECharts-compatible chart specs from query result data."""

    def __init__(self, llm: Runnable):
        self.llm = llm
        # The summarize path shares one ChartGenerator instance across futures.
        # Serialize LLM access so concurrent chart requests cannot interleave
        # streamed model responses and produce partial/invalid intents.
        self._llm_lock = threading.Lock()

    def generate_chart(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        original_query: str = "",
        result_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        End-to-end: LLM intent -> validated resolved spec -> deterministic data -> size guard.
        Returns the final chart payload or None if not plottable / on error.
        """
        if not data or not columns:
            return None

        result_context = result_context or {}

        try:
            llm_intent = self._get_llm_config(columns, data, original_query, result_context)
            heuristic_intent = self._build_heuristic_intent(columns, data, original_query, result_context)
            attempts: List[Tuple[str, Dict[str, Any], List[str]]] = []

            if llm_intent and llm_intent.get("plottable", False):
                attempts.append(("llm" if self.llm is not None else "heuristic", llm_intent, []))
            if heuristic_intent and heuristic_intent.get("plottable", False):
                heuristic_notes: List[str] = []
                if llm_intent is None:
                    heuristic_notes.append("Used best-effort heuristic chart selection because the model did not return a valid intent")
                elif not llm_intent.get("plottable", False):
                    heuristic_notes.append("Used best-effort heuristic chart selection because the model marked the result as not plottable")
                else:
                    heuristic_notes.append("Used best-effort heuristic chart selection because the original chart intent could not be validated or materialized")
                attempts.append(("heuristic", heuristic_intent, heuristic_notes))

            for intent_source, intent, seed_notes in attempts:
                resolved_config, normalization_notes = self._resolve_intent_spec(
                    columns,
                    data,
                    intent,
                    result_context,
                )
                if resolved_config is None:
                    continue

                chart_data, aggregated, agg_note = self._assemble_data(
                    columns,
                    data,
                    resolved_config,
                    result_context,
                )
                if not chart_data:
                    continue

                notes = [note for note in [*seed_notes, agg_note, *normalization_notes] if note]
                chart_meta = self._build_chart_meta(columns, data, resolved_config, result_context, notes)
                chart_meta["businessInsight"] = self._resolve_business_insight(
                    intent=intent,
                    resolved_config=resolved_config,
                    chart_data=chart_data,
                )
                chart_meta["intentSource"] = intent_source
                payload = {
                    "config": {
                        "chartType": resolved_config.get("chartType", "bar"),
                        "title": resolved_config.get("title", ""),
                        "description": chart_meta.get("description"),
                        "xAxisField": resolved_config.get("xAxisField"),
                        "groupByField": resolved_config.get("groupByField"),
                        "yAxisField": resolved_config.get("yAxisField"),
                        "zAxisField": resolved_config.get("zAxisField"),
                        "series": resolved_config.get("series", []),
                        "layout": resolved_config.get("layout"),
                        "sortBy": resolved_config.get("sortBy"),
                        "toolbox": True,
                        "supportedChartTypes": resolved_config.get("supportedChartTypes", ["bar"]),
                        "referenceLines": resolved_config.get("referenceLines", []),
                        "compareLabels": (
                            resolved_config.get("compareLabels")
                            or (resolved_config.get("transform") or {}).get("compareLabels")
                        ),
                        "transform": resolved_config.get("transform"),
                        "style": {
                            "palette": "default",
                            "showLegend": True,
                            "showLabels": False,
                            "showGridLines": True,
                            "showTitle": True,
                            "showDescription": True,
                            "smoothLines": True,
                        },
                    },
                    "chartData": chart_data,
                    "downloadData": data[:MAX_DOWNLOAD_ROWS],
                    "totalRows": len(data),
                    "aggregated": aggregated,
                    "aggregationNote": " | ".join(notes) if notes else None,
                    "meta": chart_meta,
                }

                payload = self._size_guard(payload)
                return payload

            return None

        except Exception as e:
            logger.warning(f"ChartGenerator error: {e}")
            return None

    def _resolve_business_insight(
        self,
        intent: Dict[str, Any],
        resolved_config: Dict[str, Any],
        chart_data: List[Dict[str, Any]],
    ) -> Optional[str]:
        insight = intent.get("businessInsight")
        if isinstance(insight, str) and insight.strip():
            return insight.strip()[:180]

        if not chart_data:
            return None

        chart_type = resolved_config.get("chartType", "bar")
        x_field = resolved_config.get("xAxisField") or "category"
        series = resolved_config.get("series") or []
        primary_field = series[0]["field"] if series else None
        primary_name = series[0].get("name") if series else None

        if chart_type in {"bar", "line", "area", "stackedBar", "normalizedStackedBar", "stackedArea", "dualAxis"} and primary_field:
            ranked = [
                row for row in chart_data
                if isinstance(row, dict) and row.get(x_field) not in (None, "")
            ]
            if ranked:
                aggregated_totals: Dict[str, float] = defaultdict(float)
                for row in ranked:
                    aggregated_totals[str(row.get(x_field, ""))] += _numeric(row.get(primary_field, 0))
                if aggregated_totals:
                    top_label, top_value = max(aggregated_totals.items(), key=lambda item: item[1])
                    if len({round(value, 6) for value in aggregated_totals.values()}) == 1 and chart_type == "normalizedStackedBar":
                        return None
                    label = str(top_label)
                    value = _format_number(top_value)
                    metric = primary_name or primary_field.replace("_", " ")
                    return f"{label} leads on {metric} at {value}."

        if chart_type == "deltaComparison":
            ranked = [row for row in chart_data if isinstance(row, dict)]
            if ranked:
                top_row = max(ranked, key=lambda row: abs(_numeric(row.get("delta", 0))))
                label = str(top_row.get(x_field, ""))
                delta = _numeric(top_row.get("delta", 0))
                direction = "increase" if delta >= 0 else "decline"
                return f"{label} shows the largest {direction} at {_format_number(abs(delta))}."

        if chart_type == "rankingSlope":
            ranked = [row for row in chart_data if isinstance(row, dict)]
            if ranked:
                top_row = min(ranked, key=lambda row: _numeric(row.get("endRank", 999999)))
                label = str(top_row.get(x_field, ""))
                return f"{label} finishes with the strongest ending rank."

        if chart_type == "boxplot":
            ranked = [row for row in chart_data if isinstance(row, dict)]
            if ranked:
                top_row = max(ranked, key=lambda row: _numeric(row.get("median", 0)))
                label_key = x_field if x_field in top_row else "label"
                label = str(top_row.get(label_key, "Overall"))
                return f"{label} has the highest median distribution."

        return None

    # ------------------------------------------------------------------
    # Stage 1: LLM config
    # ------------------------------------------------------------------

    def _get_llm_config(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        original_query: str,
        result_context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self.llm is None:
            return self._build_heuristic_intent(columns, data, original_query, result_context)
        prompt = self._build_prompt(columns, data, original_query, result_context)
        try:
            content = ""
            with self._llm_lock:
                if hasattr(self.llm, "stream"):
                    for chunk in self.llm.stream(prompt):
                        if getattr(chunk, "content", None):
                            content += _content_to_text(chunk.content)
                elif hasattr(self.llm, "invoke"):
                    result = self.llm.invoke(prompt)
                    content = _content_to_text(getattr(result, "content", "") or "")
            content = content.strip()
            parsed = _extract_json_object(content)
            if not isinstance(parsed, dict):
                raise ValueError("Chart intent must be a JSON object")
            if "plottable" in parsed:
                parsed["plottable"] = _normalize_plottable(parsed.get("plottable"))
            return parsed
        except Exception as e:
            logger.warning(f"ChartGenerator LLM parse error: {e}")
            return None

    def _build_prompt(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        original_query: str,
        result_context: Dict[str, Any],
    ) -> str:
        sample = data[:SAMPLE_ROWS_FOR_LLM]
        sample_json = json.dumps(sample, default=_json_default)
        if len(sample_json) > 4000:
            sample_json = sample_json[:4000] + "..."

        label = result_context.get("label") or ""
        sql_explanation = result_context.get("sql_explanation") or ""
        sql_query = result_context.get("sql_query") or ""
        sql_summary = self._summarize_sql(sql_query)
        row_grain_hint = result_context.get("row_grain_hint") or ""
        current_chart = result_context.get("current_chart")
        context_lines = [
            f"User query: {original_query}",
            f"Result label: {label}",
        ]
        if sql_summary:
            context_lines.append(f"SQL summary: {sql_summary}")
        if sql_explanation:
            context_lines.append(f"Result explanation: {sql_explanation}")
        if row_grain_hint:
            context_lines.append(f"Row grain hint: {row_grain_hint}")
        if current_chart:
            context_lines.extend(
                [
                    "Current chart metadata:",
                    json.dumps(current_chart, default=_json_default),
                ]
            )
        context_lines.extend(
            [
                f"Columns: {columns}",
                f"Total rows: {len(data)}",
                f"Sample data ({len(sample)} rows):",
                sample_json,
            ]
        )

        return f"""You are a data-visualization expert who creates visually diverse, insightful charts. Given a query result, choose the BEST chart type for the data shape — not the most common one.

{chr(10).join(context_lines)}

You may ONLY choose options from this capability model:
- chart types: {", ".join(SUPPORTED_CHART_TYPES)}
- layouts: {", ".join(SUPPORTED_LAYOUTS)}
- transforms: {", ".join(SUPPORTED_TRANSFORMS)}
- series render types: {", ".join(SERIES_RENDER_TYPES)}
- time buckets: {", ".join(SUPPORTED_TIME_BUCKETS)}
- aggregate functions: {", ".join(SUPPORTED_AGGREGATIONS)}

CHART SELECTION GUIDE — pick the type that best fits the data:
- bar/grouped bar: comparing discrete categories on ONE metric (e.g. top 10 providers by spend)
- line: trends over time with a date/time x-axis
- area/stackedArea: trends over time where you want to show volume or composition changing
- scatter: relationship between TWO numeric variables (e.g. age vs. cost)
- pie: share/composition when there are <=6 categories and one metric
- stackedBar: composition across categories when you have a groupBy dimension
- normalizedStackedBar: percent-of-total composition across categories
- heatmap: density or magnitude across TWO categorical dimensions (e.g. benefit_type vs. service_year)
- boxplot: distribution spread of a numeric field across groups
- dualAxis: comparing TWO metrics with very different scales (e.g. count on left, dollars on right)
- rankingSlope: how entity rankings change between two periods
- deltaComparison: period-over-period change (e.g. this year vs last year)

Return ONLY valid JSON (no markdown, no explanation):
{{
  "plottable": true,
  "chartType": "<choose the best type from the guide above>",
  "title": "short descriptive chart title",
  "businessInsight": "one concise business interpretation grounded in the actual chart data, max 140 chars",
  "xAxisField": "category_or_time_field",
  "zAxisField": "optional_numeric_size_field",
  "groupByField": "optional_group_field_or_period_field",
  "layout": "grouped"|"stacked"|"normalized"|null,
  "series": [
    {{
      "field": "numeric_column",
      "name": "Display Name",
      "format": "currency"|"number"|"percent",
      "chartType": "bar"|"line"|"area"|null,
      "axis": "primary"|"secondary"|null
    }}
  ],
  "sortBy": {{"field": "field_name", "order": "asc"|"desc"}} or null,
  "transform": null or {{
    "type": "topN"|"frequency"|"timeBucket"|"histogram"|"percentOfTotal"|"heatmap"|"boxplot"|"rankingSlope"|"deltaComparison",
    "...": "transform-specific fields"
  }},
  "referenceLines": [
    {{"value": 0, "label": "optional label", "axis": "primary"|"secondary"|null}}
  ]
}}

Examples for EACH chart type:
- Trend over time: chartType=line, xAxisField="service_date", transform={{"type":"timeBucket","field":"service_date","bucket":"month","metric":"paid_amount","function":"sum"}}
- Pre-aggregated count trend: if rows already contain claim_count/member_count/etc, use transform={{"type":"timeBucket","field":"year","bucket":"year","metric":"claim_count","function":"sum"}} instead of counting rows
- Stacked area trend: chartType=stackedArea, layout=stacked, xAxisField="service_date", groupByField="benefit_type", transform={{"type":"timeBucket","field":"service_date","bucket":"quarter","metric":"paid_amount","function":"sum"}}
- Distribution histogram: chartType=bar, transform={{"type":"histogram","field":"paid_amount","bins":12}}
- Top N categories: chartType=bar, transform={{"type":"topN","metric":"total_paid_amount","n":10,"otherLabel":"Other"}}, sortBy={{"field":"total_paid_amount","order":"desc"}}
- Stacked composition: chartType=stackedBar, layout=stacked, groupByField="benefit_type", transform={{"type":"topN","metric":"paid_amount","n":8,"otherLabel":"Other"}}
- Percent composition: chartType=normalizedStackedBar, layout=normalized, transform={{"type":"percentOfTotal","metric":"member_count"}}
- Scatter correlation: chartType=scatter, xAxisField="current_age", zAxisField="claim_count", series=[{{"field":"total_paid","name":"Total Paid","format":"currency"}}]
- Pie share: chartType=pie, xAxisField="gender", series=[{{"field":"member_count","name":"Members","format":"number"}}]
- Heatmap: chartType=heatmap, xAxisField="service_year", groupByField="benefit_type", transform={{"type":"heatmap","metric":"paid_amount","function":"sum","xOrder":"asc","yOrder":"asc"}}
- Boxplot spread: chartType=boxplot, xAxisField="benefit_type", transform={{"type":"boxplot","field":"paid_amount"}}, sortBy={{"field":"median","order":"desc"}}
- Dual axis comparison: chartType=dualAxis, series=[{{"field":"total_paid","name":"Total Paid","format":"currency","chartType":"bar","axis":"primary"}},{{"field":"claim_count","name":"Claims","format":"number","chartType":"line","axis":"secondary"}}]
- Ranking change: chartType=rankingSlope, xAxisField="provider_name", transform={{"type":"rankingSlope","entityField":"provider_name","periodField":"service_year","metric":"paid_amount","function":"sum","topN":10}}
- Period delta: chartType=deltaComparison, xAxisField="benefit_type", transform={{"type":"deltaComparison","entityField":"benefit_type","periodField":"service_year","metric":"paid_amount","function":"sum"}}, sortBy={{"field":"delta","order":"desc"}}

Rules:
- DO NOT default to bar chart — actively consider which type best reveals the insight
- plottable=false ONLY for single scalars, all-text, or no numeric dimension
- High row count is NEVER a reason to skip; prefer a transform
- Keep total series to <=3
- If two numeric fields exist and no date, strongly consider scatter or dualAxis
- If a date field exists, prefer line, area, or stackedArea over bar
- If the x-axis is a continuous numeric field such as age, cost, score, or length_of_stay, prefer histogram bins instead of plotting raw numeric values as categories
- Do NOT use a high-cardinality numeric field as a categorical x-axis unless you are intentionally binning it with histogram
- If a metric is already an aggregated count-like field such as claim_count, member_count, diagnosis_count, or total_count, use sum/count_distinct/avg/etc on that metric as appropriate; do NOT use function="count" unless you truly mean counting input rows
- If <=6 categories with one metric, consider pie
- If two categorical dimensions with a metric, consider heatmap
- For heatmaps, you may set transform.xOrder and transform.yOrder to "asc" or "desc" for axis ordering
- For charts with a categorical/time x-axis, use sortBy to control x-axis order when helpful
- For charts with continuous x/y values (for example scatter), use sortBy to control row/point order when helpful
- For transformed outputs, sortBy.field may refer to derived fields such as count, delta, min, q1, median, q3, max, startRank, or endRank when applicable
- If you see period/year columns, consider rankingSlope or deltaComparison
- Prefer charts that match the current result label/explanation, not a previous result
- If row grain indicates repeated detail rows (diagnosis, procedure, coverage, code-level rows),
  do NOT choose a configuration that would sum repeated patient-level totals across those rows
- Do NOT invent fields or chart options outside the capability model
- businessInsight must describe what the chart shows in business terms, not how the chart was built
"""

    def _summarize_sql(self, sql_query: Any) -> str:
        sql = str(sql_query or "").strip()
        if not sql:
            return ""
        parse_error, exp_module, parse_one_fn = _load_sqlglot()
        if parse_one_fn and exp_module is not None:
            try:
                expression = parse_one_fn(sql)
                summary = self._summarize_sql_expression(expression, exp_module)
                if summary:
                    return summary
            except (parse_error, ValueError, TypeError) as exc:
                logger.debug("sqlglot failed to summarize chart SQL: %s", exc)
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning("Unexpected sqlglot error during chart SQL summary: %s", exc)

        return self._fallback_sql_summary(sql)

    def _summarize_sql_expression(self, expression: Any, exp_module: Any) -> str:
        if isinstance(expression, exp_module.SetOperation):
            return self._summarize_set_operation(expression, exp_module)
        if isinstance(expression, exp_module.Select):
            return self._summarize_select_expression(expression, exp_module)
        select = expression.find(exp_module.Select)
        if select:
            return self._summarize_select_expression(select, exp_module)
        return ""

    def _summarize_select_expression(self, expression: Any, exp_module: Any) -> str:
        bits: List[str] = []
        with_clause = expression.args.get("with_")
        if with_clause and getattr(with_clause, "expressions", None):
            cte_count = len(with_clause.expressions)
            bits.append(f"{cte_count} CTE{'s' if cte_count != 1 else ''}")

        if expression.args.get("distinct"):
            bits.append("uses DISTINCT")

        metric_summary = self._summarize_select_metrics(expression, exp_module)
        if not metric_summary and with_clause and getattr(with_clause, "expressions", None):
            metric_summary = self._summarize_with_clause_metrics(with_clause, exp_module)
        if metric_summary:
            bits.append(metric_summary)

        group_clause = expression.args.get("group")
        if group_clause and getattr(group_clause, "expressions", None):
            group_fields = ", ".join(self._compact_sql(group.sql(), 32) for group in group_clause.expressions[:3])
            suffix = " +" if len(group_clause.expressions) > 3 else ""
            bits.append(f"grouped by {group_fields}{suffix}")

        join_count = len(expression.args.get("joins") or [])
        if join_count:
            bits.append(f"{join_count} join{'s' if join_count != 1 else ''}")

        if expression.args.get("where"):
            bits.append("has filters")
        if expression.find(exp_module.Window):
            bits.append("uses window functions")

        order_clause = expression.args.get("order")
        if order_clause and getattr(order_clause, "expressions", None):
            order_fields = ", ".join(self._compact_sql(item.sql(), 36) for item in order_clause.expressions[:2])
            suffix = " +" if len(order_clause.expressions) > 2 else ""
            bits.append(f"ordered by {order_fields}{suffix}")

        limit_clause = expression.args.get("limit")
        if limit_clause is not None:
            limit_value = getattr(limit_clause, "expression", None)
            if limit_value is not None:
                bits.append(f"limit {limit_value.sql()}")

        return self._finalize_sql_summary(bits)

    def _summarize_set_operation(self, expression: Any, exp_module: Any) -> str:
        bits: List[str] = []
        branches = self._flatten_set_operation_branches(expression, exp_module)
        operation_label = self._set_operation_label(expression, exp_module)
        bits.append(f"combines {len(branches)} SELECT branches via {operation_label}")

        with_clause = expression.args.get("with_")
        if with_clause and getattr(with_clause, "expressions", None):
            cte_count = len(with_clause.expressions)
            bits.append(f"{cte_count} CTE{'s' if cte_count != 1 else ''}")

        if expression.find(exp_module.Window):
            bits.append("uses window functions")

        order_clause = expression.args.get("order")
        if order_clause and getattr(order_clause, "expressions", None):
            order_fields = ", ".join(self._compact_sql(item.sql(), 36) for item in order_clause.expressions[:2])
            suffix = " +" if len(order_clause.expressions) > 2 else ""
            bits.append(f"ordered by {order_fields}{suffix}")

        limit_clause = expression.args.get("limit")
        if limit_clause is not None:
            limit_value = getattr(limit_clause, "expression", None)
            if limit_value is not None:
                bits.append(f"limit {limit_value.sql()}")

        aggregate_names: List[str] = []
        for branch in branches:
            branch_label = self._infer_select_branch_label(branch, exp_module)
            branch_metric_summary = self._summarize_select_metrics(branch, exp_module)
            if branch_metric_summary:
                metric_clause = branch_metric_summary.removeprefix("metrics ")
                for metric in metric_clause.split(", "):
                    labeled_metric = f"{branch_label}.{metric}" if branch_label else metric
                    if labeled_metric not in aggregate_names:
                        aggregate_names.append(labeled_metric)
                if len(aggregate_names) >= 3:
                    break
            if len(aggregate_names) >= 3:
                break
        if aggregate_names:
            suffix = " +" if len(aggregate_names) > 3 else ""
            bits.append(f"branch metrics {', '.join(aggregate_names[:3])}{suffix}")

        return self._finalize_sql_summary(bits)

    def _summarize_select_metrics(self, expression: Any, exp_module: Any) -> str:
        metric_bits: List[str] = []
        select_expressions = list(getattr(expression, "expressions", None) or [])
        for select_item in select_expressions:
            raw_expression = select_item.this if isinstance(select_item, exp_module.Alias) else select_item
            agg_expression = None
            if isinstance(raw_expression, exp_module.AggFunc):
                agg_expression = raw_expression
            elif hasattr(raw_expression, "find"):
                agg_expression = raw_expression.find(exp_module.AggFunc)
            if agg_expression is None:
                continue

            alias = str(getattr(select_item, "alias_or_name", "") or "").strip()
            metric_expr = self._compact_sql(
                raw_expression.sql() if alias else agg_expression.sql(),
                48,
            )
            metric_bit = f"{alias}={metric_expr}" if alias else metric_expr
            if metric_bit not in metric_bits:
                metric_bits.append(metric_bit)
            if len(metric_bits) >= 3:
                break

        if not metric_bits:
            return ""
        return f"metrics {', '.join(metric_bits[:3])}"

    def _summarize_with_clause_metrics(self, with_clause: Any, exp_module: Any) -> str:
        for cte in reversed(list(getattr(with_clause, "expressions", None) or [])):
            cte_body = getattr(cte, "this", None)
            if cte_body is None:
                continue
            if isinstance(cte_body, exp_module.Select):
                metric_summary = self._summarize_select_metrics(cte_body, exp_module)
            elif hasattr(cte_body, "find"):
                select = cte_body.find(exp_module.Select)
                metric_summary = self._summarize_select_metrics(select, exp_module) if select else ""
            else:
                metric_summary = ""
            if metric_summary:
                return metric_summary
        return ""

    def _infer_select_branch_label(self, expression: Any, exp_module: Any) -> str:
        select_expressions = list(getattr(expression, "expressions", None) or [])
        for select_item in select_expressions:
            if not isinstance(select_item, exp_module.Alias):
                continue
            raw_expression = getattr(select_item, "this", None)
            if isinstance(raw_expression, exp_module.Literal) and getattr(raw_expression, "is_string", False):
                literal_value = str(getattr(raw_expression, "this", "") or "").strip()
                if literal_value:
                    return self._compact_sql(literal_value, 20)

        table_iter = getattr(expression, "find_all", None)
        if callable(table_iter):
            for table in expression.find_all(exp_module.Table):
                table_name = getattr(table, "name", None) or getattr(table, "this", None)
                table_label = str(table_name or "").strip()
                if table_label:
                    return self._compact_sql(table_label, 24)
        return ""

    def _finalize_sql_summary(self, bits: List[str]) -> str:
        return "; ".join(bits[:7])[:360]

    def _flatten_set_operation_branches(self, expression: Any, exp_module: Any) -> List[Any]:
        if not isinstance(expression, exp_module.SetOperation):
            return []

        branches: List[Any] = []
        for child in (expression.this, expression.expression):
            if isinstance(child, type(expression)):
                branches.extend(self._flatten_set_operation_branches(child, exp_module))
            elif isinstance(child, exp_module.Select):
                branches.append(child)
            else:
                select = child.find(exp_module.Select) if child else None
                if select:
                    branches.append(select)
        return branches

    def _set_operation_label(self, expression: Any, exp_module: Any) -> str:
        if isinstance(expression, exp_module.Union):
            return "UNION" if expression.args.get("distinct") else "UNION ALL"
        if isinstance(expression, exp_module.Intersect):
            return "INTERSECT"
        if isinstance(expression, exp_module.Except):
            return "EXCEPT"
        return expression.key.upper() if getattr(expression, "key", None) else "set operation"

    def _fallback_sql_summary(self, sql_query: str) -> str:
        normalized = re.sub(r"\s+", " ", _strip_sql_comments(sql_query)).strip().rstrip(";")
        if not normalized:
            return ""
        lowered = normalized.lower()
        bits: List[str] = []

        if re.search(r"\bunion all\b", lowered):
            bits.append("combines result sets via UNION ALL")
        elif re.search(r"\bunion\b", lowered):
            bits.append("combines result sets via UNION")
        elif re.search(r"\bintersect\b", lowered):
            bits.append("combines result sets via INTERSECT")
        elif re.search(r"\bexcept\b", lowered):
            bits.append("combines result sets via EXCEPT")

        if re.search(r"\bwith\b", lowered):
            bits.append("uses CTEs")
        if re.search(r"\bselect\s+distinct\b", lowered):
            bits.append("uses DISTINCT")

        aggregates = re.findall(
            r"\b(count|sum|avg|min|max|median|percentile(?:_approx)?|stddev(?:_pop|_samp)?)\s*\((.*?)\)",
            normalized,
            flags=re.IGNORECASE,
        )
        if aggregates:
            metric_bits = [f"{fn.lower()}({self._compact_sql(arg, 40)})" for fn, arg in aggregates[:3]]
            suffix = " +" if len(aggregates) > 3 else ""
            bits.append(f"metrics {', '.join(metric_bits)}{suffix}")

        join_count = len(re.findall(r"\bjoin\b", lowered))
        if join_count:
            bits.append(f"{join_count} join{'s' if join_count != 1 else ''}")
        if re.search(r"\bwhere\b", lowered):
            bits.append("has filters")
        if re.search(r"\bover\s*\(", lowered):
            bits.append("uses window functions")

        group_match = re.search(r"\bgroup by\b\s+(.*?)(?=\bhaving\b|\border by\b|\blimit\b|$)", normalized, flags=re.IGNORECASE)
        if group_match:
            bits.append(f"grouped by {self._compact_sql(group_match.group(1), 96)}")

        order_match = re.search(r"\border by\b\s+(.*?)(?=\blimit\b|$)", normalized, flags=re.IGNORECASE)
        if order_match:
            bits.append(f"ordered by {self._compact_sql(order_match.group(1), 96)}")

        limit_match = re.search(r"\blimit\b\s+(\d+)", lowered)
        if limit_match:
            bits.append(f"limit {limit_match.group(1)}")

        return self._finalize_sql_summary(bits)

    def _compact_sql(self, text: str, limit: int = 72) -> str:
        compacted = re.sub(r"\s+", " ", text).strip()
        if len(compacted) <= limit:
            return compacted
        return compacted[: limit - 3].rstrip() + "..."

    # ------------------------------------------------------------------
    # Stage 2: Python validation + assembly
    # ------------------------------------------------------------------

    def _resolve_intent_spec(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        intent: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        notes: List[str] = []
        kinds = self._infer_field_kinds(columns, data)

        x_field = self._coerce_field(intent.get("xAxisField"), columns)
        z_field = self._coerce_field(intent.get("zAxisField"), columns)
        group_field = self._coerce_field(intent.get("groupByField"), columns)

        series = self._normalize_series(intent.get("series"), columns, data, notes)
        transform = self._normalize_transform(
            intent.get("transform") or intent.get("aggregation"),
            columns,
            kinds,
            x_field,
            group_field,
            series,
            notes,
        )

        chart_type = self._normalize_chart_type(
            intent.get("chartType"),
            transform,
            series,
            x_field,
            group_field,
            kinds,
            notes,
        )
        layout = self._normalize_layout(intent.get("layout"), chart_type, group_field, notes)

        if chart_type == "stackedBar":
            layout = "stacked"
        elif chart_type == "normalizedStackedBar":
            layout = "normalized"
        elif chart_type == "stackedArea":
            layout = "stacked"
        elif chart_type == "area" and layout == "stacked":
            chart_type = "stackedArea"

        if chart_type == "heatmap":
            x_field = x_field or self._pick_categorical_field(columns, kinds)
            group_field = group_field or self._pick_secondary_dimension(columns, kinds, x_field)
        elif chart_type == "boxplot":
            x_field = x_field or self._pick_categorical_field(columns, kinds)
        elif chart_type in {"rankingSlope", "deltaComparison"}:
            x_field = x_field or self._pick_categorical_field(columns, kinds)
            group_field = (
                (transform or {}).get("periodField")
                or group_field
                or self._pick_date_or_categorical_field(columns, kinds, exclude=x_field)
            )
        else:
            x_field = x_field or self._pick_default_x_field(columns, kinds)

        if chart_type in {"heatmap", "boxplot", "rankingSlope", "deltaComparison"}:
            special_transform = self._normalize_transform(
                {**(transform or {}), "type": chart_type},
                columns,
                kinds,
                x_field,
                group_field,
                series,
                notes,
            )
            if special_transform:
                transform = special_transform
                if chart_type == "heatmap":
                    group_field = transform.get("yField") or group_field
                if chart_type in {"rankingSlope", "deltaComparison"}:
                    group_field = transform.get("periodField") or group_field
            else:
                notes.append(f"Downgraded {chart_type} to bar because required fields could not be inferred")
                chart_type = "bar"
                transform = None
                x_field = x_field or self._pick_default_x_field(columns, kinds)
                layout = "grouped" if group_field else None

        if chart_type == "scatter" and not x_field:
            numeric_candidates = self._rank_numeric_fields_for_series(columns, kinds, data)
            primary_field = series[0]["field"] if series else None
            x_field = next((field for field in numeric_candidates if field != primary_field), None)
            if x_field:
                notes.append(f"Filled missing scatter x-axis with numeric field '{x_field}'")

        if chart_type == "scatter":
            numeric_candidates = self._rank_numeric_fields_for_series(columns, kinds, data)
            primary_field = series[0]["field"] if series else None
            if z_field and (kinds.get(z_field) != "numeric" or z_field in {x_field, primary_field}):
                z_field = None
            if not z_field:
                z_field = next(
                    (field for field in numeric_candidates if field not in {x_field, primary_field}),
                    None,
                )

        if chart_type == "dualAxis" and len(series) < 2:
            chart_type = "bar"
            notes.append("Downgraded dualAxis to bar because fewer than two valid series remained")

        if x_field and self._looks_like_identifier_field(x_field) and chart_type not in {"scatter", "dualAxis", "heatmap", "boxplot", "rankingSlope", "deltaComparison"} and series:
            primary_metric = series[0]["field"]
            if self._should_bucket_numeric_field(primary_metric, data):
                x_field = primary_metric
                group_field = None
                layout = None
                transform = self._build_histogram_transform(primary_metric, data)
                chart_type = "bar"
                notes.append(f"Swapped identifier x-axis for histogram on '{primary_metric}'")

        if (
            x_field
            and chart_type not in {"scatter", "dualAxis", "rankingSlope", "deltaComparison"}
            and self._should_bucket_numeric_field(x_field, data)
        ):
            transform_type = transform.get("type") if transform else None
            if transform_type in {None, "topN", "frequency"}:
                group_field = None
                layout = None
                transform = self._build_histogram_transform(x_field, data)
                chart_type = "bar"
                notes.append(f"Bucketed continuous numeric x-axis '{x_field}' into histogram bins")

        if chart_type == "pie":
            layout = None
            group_field = None
            series = series[:1]

        if chart_type == "scatter":
            layout = None
            group_field = None
            if len(series) < 1:
                return None, notes

        effective_series = transform.get("syntheticSeries") if transform else None
        if not (effective_series or series) and chart_type not in {"heatmap", "rankingSlope", "deltaComparison"}:
            return None, notes

        if not x_field and chart_type not in {"boxplot", "dualAxis"}:
            if series:
                field = series[0]["field"]
                transform = {
                    "type": "boxplot",
                    "field": field,
                    "groupField": None,
                    "syntheticSeries": [
                        {
                            "field": field,
                            "name": series[0].get("name") or field.replace("_", " ").title(),
                            "format": series[0].get("format") or self._infer_format(field),
                            "chartType": None,
                            "axis": "primary",
                        }
                    ],
                }
                chart_type = "boxplot"
                layout = None
                group_field = None
                notes.append("Downgraded to boxplot because no suitable x-axis field was available")
            else:
                notes.append("Skipped chart because no suitable x-axis field was available")
                return None, notes

        if not self._is_chart_type_supported(chart_type, layout):
            notes.append(f"Downgraded unsupported chart combination to bar")
            chart_type = "bar"
            layout = "grouped" if group_field else None

        reference_lines = self._normalize_reference_lines(intent.get("referenceLines"), notes)
        sort_by = self._normalize_sort(
            intent.get("sortBy"),
            columns,
            self._resolve_sortable_fields(chart_type, x_field, group_field, transform),
            allow_source_columns=not bool(transform),
        )
        if transform and transform.get("type") == "histogram" and sort_by:
            histogram_field = transform.get("field")
            if sort_by.get("field") in {x_field, histogram_field, "bucket"}:
                sort_by = {"field": "bucketStart", "order": sort_by.get("order", "desc")}
        if chart_type == "scatter" and x_field and not sort_by:
            sort_by = {"field": x_field, "order": "asc"}
        if chart_type == "heatmap" and transform and sort_by:
            sort_field = sort_by.get("field")
            if sort_field == transform.get("xField"):
                transform["xOrder"] = sort_by.get("order", "asc")
            elif sort_field == transform.get("yField"):
                transform["yOrder"] = sort_by.get("order", "asc")
            else:
                sort_by = None
        supported_types = self._resolve_supported_chart_types(chart_type, group_field, layout, transform)

        resolved = {
            "chartType": chart_type,
            "title": intent.get("title") or "",
            "xAxisField": "bucket" if transform and transform.get("type") == "histogram" else x_field,
            "groupByField": group_field,
            "yAxisField": transform.get("yField") if transform else None,
            "zAxisField": z_field if chart_type == "scatter" else None,
            "series": series,
            "layout": layout,
            "transform": transform,
            "sortBy": sort_by,
            "referenceLines": reference_lines,
            "supportedChartTypes": supported_types,
            "compareLabels": transform.get("compareLabels") if transform else None,
            "resultContext": result_context,
        }

        if transform and transform.get("syntheticSeries"):
            resolved["series"] = transform["syntheticSeries"]

        return resolved, notes

    def _normalize_series(
        self,
        raw_series: Any,
        columns: Sequence[str],
        data: List[Dict[str, Any]],
        notes: List[str],
    ) -> List[Dict[str, Any]]:
        kinds = self._infer_field_kinds(columns, data)
        numeric_fields = self._rank_numeric_fields_for_series(columns, kinds, data)
        series_list = raw_series if isinstance(raw_series, list) else []
        normalized: List[Dict[str, Any]] = []

        for item in series_list[:3]:
            if not isinstance(item, dict):
                continue
            field = self._coerce_field(item.get("field"), columns)
            if not field or kinds.get(field) != "numeric":
                continue
            fmt = item.get("format") if item.get("format") in SUPPORTED_FORMATS else "number"
            render_type = item.get("chartType")
            if render_type not in SERIES_RENDER_TYPES:
                render_type = None
            axis = item.get("axis") if item.get("axis") in {"primary", "secondary"} else "primary"
            normalized.append(
                {
                    "field": field,
                    "name": item.get("name") or field.replace("_", " ").title(),
                    "format": fmt,
                    "chartType": render_type,
                    "axis": axis,
                }
            )

        if normalized:
            return normalized

        for field in numeric_fields[:2]:
            normalized.append(
                {
                    "field": field,
                    "name": field.replace("_", " ").title(),
                    "format": self._infer_format(field),
                    "chartType": None,
                    "axis": "primary",
                }
            )

        if normalized and len(series_list) == 0:
            notes.append("Filled missing series from numeric columns")
        return normalized

    def _normalize_transform(
        self,
        raw_transform: Any,
        columns: Sequence[str],
        kinds: Dict[str, str],
        x_field: Optional[str],
        group_field: Optional[str],
        series: List[Dict[str, Any]],
        notes: List[str],
    ) -> Optional[Dict[str, Any]]:
        if not raw_transform:
            return None
        if not isinstance(raw_transform, dict):
            notes.append("Ignored malformed transform payload from the model")
            return None

        transform_type = raw_transform.get("type")
        if transform_type not in SUPPORTED_TRANSFORMS:
            notes.append(f"Ignored unsupported transform '{transform_type}'")
            return None

        metric = self._coerce_field(raw_transform.get("metric"), columns)
        if not metric and series:
            metric = series[0]["field"]

        normalized: Dict[str, Any] = {"type": transform_type}

        if transform_type == "topN":
            normalized["metric"] = metric
            normalized["n"] = _clamp_int(raw_transform.get("n"), default=10, minimum=2, maximum=20)
            normalized["otherLabel"] = raw_transform.get("otherLabel") or "Other"
            return normalized

        if transform_type == "frequency":
            normalized["field"] = self._coerce_field(raw_transform.get("field"), columns) or x_field
            normalized["topN"] = _clamp_int(raw_transform.get("topN"), default=10, minimum=2, maximum=20)
            normalized["syntheticSeries"] = [
                {
                    "field": "count",
                    "name": "Count",
                    "format": "number",
                    "chartType": None,
                    "axis": "primary",
                }
            ]
            return normalized

        if transform_type == "timeBucket":
            field = self._coerce_field(raw_transform.get("field"), columns) or x_field
            if not field or kinds.get(field) != "date":
                notes.append("Skipped invalid timeBucket field; using fallback chart")
                return None
            normalized["field"] = field
            normalized["bucket"] = (
                raw_transform.get("bucket")
                if raw_transform.get("bucket") in SUPPORTED_TIME_BUCKETS
                else "month"
            )
            normalized["metric"] = metric
            normalized["function"] = (
                raw_transform.get("function")
                if raw_transform.get("function") in SUPPORTED_AGGREGATIONS
                else ("count" if not metric else "sum")
            )
            if metric and normalized["function"] == "count" and _is_count_like_metric_name(metric):
                normalized["function"] = "sum"
                notes.append(
                    f"Converted timeBucket aggregation for pre-aggregated metric '{metric}' from count to sum"
                )
            if metric and normalized["function"] in {"count", "count_distinct"}:
                synthetic_name = "Count"
                if normalized["function"] == "count_distinct":
                    synthetic_name = f"Distinct {metric.replace('_', ' ').title()} Count"
                elif metric != "count":
                    synthetic_name = metric.replace("_", " ").title()
                normalized["syntheticSeries"] = [
                    {
                        "field": metric,
                        "name": synthetic_name,
                        "format": "number",
                        "chartType": None,
                        "axis": "primary",
                    }
                ]
            return normalized

        if transform_type == "histogram":
            field = self._coerce_field(raw_transform.get("field"), columns) or metric
            if not field or kinds.get(field) != "numeric":
                notes.append("Skipped invalid histogram field; using fallback chart")
                return None
            explicit_metric = self._coerce_field(raw_transform.get("metric"), columns)
            normalized["field"] = field
            normalized["bins"] = _clamp_int(raw_transform.get("bins"), default=12, minimum=5, maximum=20)
            normalized["metric"] = explicit_metric
            normalized["function"] = (
                raw_transform.get("function")
                if raw_transform.get("function") in SUPPORTED_AGGREGATIONS
                else ("count" if not explicit_metric else "sum")
            )
            synthetic_field = explicit_metric or "count"
            synthetic_name = "Count"
            if explicit_metric and normalized["function"] == "count_distinct":
                synthetic_name = f"Distinct {explicit_metric.replace('_', ' ').title()} Count"
            elif explicit_metric and normalized["function"] != "count":
                synthetic_name = explicit_metric.replace("_", " ").title()
            normalized["syntheticSeries"] = [
                {
                    "field": synthetic_field,
                    "name": synthetic_name,
                    "format": "number" if normalized["function"] in {"count", "count_distinct"} else self._infer_format(explicit_metric or "count"),
                    "chartType": None,
                    "axis": "primary",
                }
            ]
            return normalized

        if transform_type == "percentOfTotal":
            normalized["metric"] = metric
            normalized["within"] = "x" if group_field else "global"
            return normalized

        if transform_type == "heatmap":
            normalized["xField"] = x_field or self._pick_categorical_field(columns, kinds)
            normalized["yField"] = self._coerce_field(raw_transform.get("yField"), columns) or group_field
            normalized["metric"] = metric
            normalized["xOrder"] = self._normalize_axis_order(raw_transform.get("xOrder"))
            normalized["yOrder"] = self._normalize_axis_order(raw_transform.get("yOrder"))
            normalized["function"] = (
                raw_transform.get("function")
                if raw_transform.get("function") in SUPPORTED_AGGREGATIONS
                else ("count" if not metric else "sum")
            )
            normalized["syntheticSeries"] = [
                {
                    "field": metric or "value",
                    "name": (metric or "value").replace("_", " ").title(),
                    "format": self._infer_format(metric or "value"),
                    "chartType": None,
                    "axis": "primary",
                }
            ]
            return normalized if normalized["xField"] and normalized["yField"] else None

        if transform_type == "boxplot":
            field = self._coerce_field(raw_transform.get("field"), columns) or metric
            if not field or kinds.get(field) != "numeric":
                notes.append("Skipped invalid boxplot field; using fallback chart")
                return None
            normalized["field"] = field
            normalized["groupField"] = x_field
            normalized["syntheticSeries"] = [
                {
                    "field": field,
                    "name": field.replace("_", " ").title(),
                    "format": self._infer_format(field),
                    "chartType": None,
                    "axis": "primary",
                }
            ]
            return normalized

        if transform_type in {"rankingSlope", "deltaComparison"}:
            entity_field = x_field or self._pick_categorical_field(columns, kinds)
            period_field = self._coerce_field(raw_transform.get("periodField"), columns) or group_field
            if not entity_field or not period_field:
                notes.append(f"Skipped invalid {transform_type} transform; using fallback chart")
                return None
            normalized["entityField"] = entity_field
            normalized["periodField"] = period_field
            normalized["metric"] = metric
            normalized["topN"] = _clamp_int(raw_transform.get("topN"), default=10, minimum=2, maximum=15)
            normalized["function"] = (
                raw_transform.get("function")
                if raw_transform.get("function") in SUPPORTED_AGGREGATIONS
                else ("count" if not metric else "sum")
            )
            normalized["syntheticSeries"] = [
                {
                    "field": metric or "count",
                    "name": (metric or "count").replace("_", " ").title(),
                    "format": self._infer_format(metric or "count"),
                    "chartType": None,
                    "axis": "primary",
                }
            ]
            return normalized

        return None

    def _normalize_chart_type(
        self,
        requested: Any,
        transform: Optional[Dict[str, Any]],
        series: List[Dict[str, Any]],
        x_field: Optional[str],
        group_field: Optional[str],
        kinds: Dict[str, str],
        notes: List[str],
    ) -> str:
        chart_type = requested if requested in SUPPORTED_CHART_TYPES or requested == "combo" else None

        if transform:
            transform_type = transform["type"]
            if transform_type == "heatmap":
                chart_type = "heatmap"
            elif transform_type == "boxplot":
                chart_type = "boxplot"
            elif transform_type == "rankingSlope":
                chart_type = "rankingSlope"
            elif transform_type == "deltaComparison":
                chart_type = "deltaComparison"
            elif transform_type == "histogram":
                chart_type = chart_type or "bar"
            elif transform_type == "timeBucket":
                chart_type = chart_type or "line"

        if chart_type == "combo":
            chart_type = "dualAxis"

        if chart_type:
            return chart_type

        if x_field and kinds.get(x_field) == "date":
            if group_field:
                return "stackedArea"
            return "line"
        if group_field and len(series) >= 1:
            return "stackedBar"

        num_numeric = sum(1 for k in kinds.values() if k == "numeric")
        num_categorical = sum(1 for k in kinds.values() if k == "text")

        if num_numeric >= 2 and x_field and kinds.get(x_field) == "numeric":
            return "scatter"
        if num_categorical <= 6 and num_categorical >= 1 and len(series) == 1:
            return "pie"
        if len(series) >= 2:
            return "dualAxis"
        if len(series) == 1:
            return "bar"

        notes.append("Defaulted chart type to bar")
        return "bar"

    def _normalize_layout(
        self,
        requested: Any,
        chart_type: str,
        group_field: Optional[str],
        notes: List[str],
    ) -> Optional[str]:
        if chart_type in {"stackedBar", "stackedArea"}:
            return "stacked"
        if chart_type == "normalizedStackedBar":
            return "normalized"
        if chart_type in {"pie", "heatmap", "boxplot", "dualAxis", "rankingSlope", "deltaComparison", "scatter"}:
            return None
        if requested in SUPPORTED_LAYOUTS:
            return requested
        if group_field and chart_type in {"bar", "area", "line"}:
            return "grouped"
        if requested and requested not in SUPPORTED_LAYOUTS:
            notes.append(f"Ignored unsupported layout '{requested}'")
        return None

    def _normalize_reference_lines(self, raw: Any, notes: List[str]) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in raw[:MAX_REFERENCE_LINES]:
            if not isinstance(item, dict):
                continue
            value = _numeric(item.get("value"))
            axis = item.get("axis") if item.get("axis") in {"primary", "secondary"} else "primary"
            normalized.append(
                {
                    "value": value,
                    "label": item.get("label") or "",
                    "axis": axis,
                }
            )
        if raw and not normalized:
            notes.append("Dropped invalid reference line definitions")
        return normalized

    def _normalize_axis_order(self, raw: Any) -> str:
        return raw if raw in {"asc", "desc"} else "asc"

    def _normalize_sort(
        self,
        raw: Any,
        columns: Sequence[str],
        extra_fields: Optional[Sequence[str]] = None,
        allow_source_columns: bool = True,
    ) -> Optional[Dict[str, str]]:
        if not isinstance(raw, dict):
            return None
        field = raw.get("field")
        allowed_fields = {"count", "delta", "value"} | {field for field in (extra_fields or []) if field}
        if allow_source_columns:
            allowed_fields |= set(columns)
        if field not in allowed_fields:
            return None
        order = raw.get("order") if raw.get("order") in {"asc", "desc"} else "desc"
        return {"field": field, "order": order}

    def _resolve_sortable_fields(
        self,
        chart_type: str,
        x_field: Optional[str],
        group_field: Optional[str],
        transform: Optional[Dict[str, Any]],
    ) -> List[str]:
        if not transform:
            return [field for field in [x_field, group_field] if field]

        transform_type = transform.get("type")
        if transform_type == "frequency":
            return [field for field in [x_field, "count"] if field]
        if transform_type == "histogram":
            return [field for field in ["bucket", transform.get("field"), "bucketStart", "bucketEnd", "count"] if field]
        if transform_type == "timeBucket":
            return [
                field
                for field in [x_field, group_field, transform.get("metric") or "count"]
                if field
            ]
        if transform_type == "percentOfTotal":
            return [field for field in [x_field, group_field, transform.get("metric")] if field]
        if transform_type == "heatmap":
            return [
                field
                for field in [transform.get("xField") or x_field, transform.get("yField") or group_field, transform.get("metric") or "value"]
                if field
            ]
        if transform_type == "boxplot":
            return [field for field in [x_field, "min", "q1", "median", "q3", "max"] if field]
        if transform_type == "deltaComparison":
            return [field for field in [x_field, "startValue", "endValue", "delta"] if field]
        if transform_type == "rankingSlope":
            return [field for field in [x_field, "startValue", "endValue", "delta", "startRank", "endRank"] if field]

        return [field for field in [x_field, group_field] if field]

    def _resolve_supported_chart_types(
        self,
        chart_type: str,
        group_field: Optional[str],
        layout: Optional[str],
        transform: Optional[Dict[str, Any]],
    ) -> List[str]:
        if chart_type in {"heatmap", "boxplot", "rankingSlope", "deltaComparison"}:
            return [chart_type]
        if chart_type == "dualAxis":
            return ["dualAxis", "bar", "line"]
        if transform and transform.get("type") == "histogram":
            return ["bar", "line"]
        if layout == "normalized":
            return ["normalizedStackedBar", "stackedBar", "bar"]
        if layout == "stacked" and chart_type in {"stackedArea", "area"}:
            return ["stackedArea", "area", "line"]
        if layout == "stacked":
            return ["stackedBar", "bar", "line"]
        if group_field:
            return ["bar", "line", "area", "stackedBar", "normalizedStackedBar"]
        return ["bar", "line", "scatter", "pie"]

    def _assemble_data(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        config: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict], bool, Optional[str]]:
        transform = config.get("transform")
        if transform:
            chart_data, note = self._apply_transform(data, config, transform, result_context)
            sorted_chart_data = self._sort_chart_rows(chart_data, config)
            if transform.get("type") == "heatmap":
                trimmed_chart_data, trim_note = self._trim_heatmap_matrix(sorted_chart_data, config)
                combined_note = " | ".join(part for part in [note, trim_note] if part)
                return trimmed_chart_data, True, combined_note or None
            return sorted_chart_data[:MAX_CHART_POINTS], True, note

        working = self._sort_chart_rows(list(data), config)

        if config.get("layout") == "normalized" and config.get("groupByField"):
            normalized_data = self._normalize_percent_by_group(working, config, result_context)
            return normalized_data[:MAX_CHART_POINTS], True, "Converted grouped values to percent-of-total composition"

        if len(working) > MAX_CHART_POINTS:
            compacted, note = self._auto_compact_rows(working, config, result_context)
            if compacted:
                return compacted[:MAX_CHART_POINTS], True, note
            note = f"Showing first {MAX_CHART_POINTS} of {len(working)} rows"
            return working[:MAX_CHART_POINTS], True, note

        return working, False, None

    def _trim_heatmap_matrix(
        self,
        rows: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if len(rows) <= MAX_CHART_POINTS:
            return rows, None

        x_field = config.get("xAxisField")
        y_field = config.get("yAxisField") or config.get("groupByField")
        if not x_field or not y_field:
            return rows[:MAX_CHART_POINTS], f"Trimmed heatmap to first {MAX_CHART_POINTS} cells"

        x_values = list(dict.fromkeys(row.get(x_field) for row in rows))
        y_values = list(dict.fromkeys(row.get(y_field) for row in rows))
        if not x_values or not y_values:
            return rows[:MAX_CHART_POINTS], f"Trimmed heatmap to first {MAX_CHART_POINTS} cells"

        x_count = len(x_values)
        y_count = len(y_values)
        if x_count * y_count <= MAX_CHART_POINTS:
            return rows, None

        target_x = min(x_count, max(1, int(math.sqrt(MAX_CHART_POINTS * x_count / y_count))))
        target_y = min(y_count, max(1, MAX_CHART_POINTS // max(target_x, 1)))
        target_x = min(x_count, max(1, MAX_CHART_POINTS // max(target_y, 1)))

        kept_x = set(x_values[:target_x])
        kept_y = set(y_values[:target_y])
        trimmed_rows = [
            row for row in rows if row.get(x_field) in kept_x and row.get(y_field) in kept_y
        ]
        trim_note = (
            f"Trimmed heatmap matrix to {target_x} x-axis values and {target_y} y-axis values "
            f"({len(trimmed_rows)} cells) to stay within point limits"
        )
        return trimmed_rows, trim_note

    def _sort_chart_rows(
        self,
        rows: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not rows:
            return rows

        sort_by = config.get("sortBy")
        if not sort_by:
            return rows

        chart_type = config.get("chartType")
        if chart_type == "heatmap":
            return rows

        x_field = config.get("xAxisField")
        group_field = config.get("groupByField")
        sort_field = sort_by.get("field", "")
        reverse = sort_by.get("order", "desc") == "desc"

        if group_field and x_field and chart_type not in {"scatter", "pie", "boxplot", "rankingSlope", "deltaComparison"}:
            return self._sort_grouped_chart_rows(rows, x_field, group_field, sort_field, reverse)

        try:
            return sorted(rows, key=lambda row: _sort_value(row.get(sort_field)), reverse=reverse)
        except Exception:
            return rows

    def _sort_grouped_chart_rows(
        self,
        rows: List[Dict[str, Any]],
        x_field: str,
        group_field: str,
        sort_field: str,
        reverse: bool,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(x_field, ""))].append(row)

        ordered_x_values = list(grouped.keys())
        ordered_group_values = sorted(
            {str(row.get(group_field, "")) for row in rows},
            key=_sort_value,
            reverse=reverse if sort_field == group_field else False,
        )
        group_positions = {value: index for index, value in enumerate(ordered_group_values)}
        if sort_field == x_field:
            ordered_x_values = sorted(ordered_x_values, key=_sort_value, reverse=reverse)
        elif sort_field and sort_field != group_field:
            ordered_x_values = sorted(
                ordered_x_values,
                key=lambda x_value: self._group_sort_value(grouped[x_value], sort_field),
                reverse=reverse,
            )

        sorted_rows: List[Dict[str, Any]] = []
        for x_value in ordered_x_values:
            x_rows = grouped[x_value]
            if sort_field == group_field:
                x_rows = sorted(
                    x_rows,
                    key=lambda row: group_positions.get(str(row.get(group_field, "")), len(group_positions)),
                )
            else:
                x_rows = sorted(
                    x_rows,
                    key=lambda row: group_positions.get(str(row.get(group_field, "")), len(group_positions)),
                )
            sorted_rows.extend(x_rows)
        return sorted_rows

    def _group_sort_value(self, rows: List[Dict[str, Any]], sort_field: str) -> Any:
        if not rows:
            return _sort_value("")

        if all(row.get(sort_field) in (None, "") or _is_numeric_like(row.get(sort_field)) for row in rows):
            return (1, sum(_numeric(row.get(sort_field, 0)) for row in rows))

        first_value = next((row.get(sort_field) for row in rows if row.get(sort_field) not in (None, "")), "")
        return _sort_value(first_value)

    def _aggregate_group_metric_values(
        self,
        rows: List[Dict[str, Any]],
        field: str,
        result_context: Dict[str, Any],
    ) -> float:
        values = [_numeric(row.get(field, 0)) for row in rows]
        return _aggregate_values(values, "sum", field, rows, result_context, self._should_dedupe_metric)

    def _apply_transform(
        self,
        data: List[Dict[str, Any]],
        config: Dict[str, Any],
        transform: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict], str]:
        transform_type = transform.get("type")
        if transform_type == "topN":
            return self._agg_top_n(
                data=data,
                x_field=config.get("xAxisField", ""),
                metric=transform.get("metric", ""),
                group_field=config.get("groupByField"),
                series=config.get("series", []),
                n=transform.get("n", 10),
                other_label=transform.get("otherLabel", "Other"),
                result_context=result_context,
            )
        if transform_type == "frequency":
            return self._agg_frequency(
                data,
                transform.get("field") or config.get("xAxisField", ""),
                transform.get("topN", 10),
                config.get("xAxisField") or transform.get("field") or "value",
            )
        if transform_type == "timeBucket":
            return self._agg_time_bucket(data, config, transform, result_context)
        if transform_type == "histogram":
            return self._agg_histogram(data, transform, result_context)
        if transform_type == "percentOfTotal":
            return self._agg_percent_of_total(data, config, transform, result_context)
        if transform_type == "heatmap":
            return self._agg_heatmap(data, transform, result_context)
        if transform_type == "boxplot":
            return self._agg_boxplot(data, transform)
        if transform_type == "rankingSlope":
            return self._agg_period_comparison(
                data,
                transform,
                comparison_type="rankingSlope",
                result_context=result_context,
                sort_by=config.get("sortBy"),
            )
        if transform_type == "deltaComparison":
            return self._agg_period_comparison(
                data,
                transform,
                comparison_type="deltaComparison",
                result_context=result_context,
                sort_by=config.get("sortBy"),
            )
        return data[:MAX_CHART_POINTS], f"Showing first {MAX_CHART_POINTS} rows"

    def _agg_top_n(
        self,
        data: List[Dict],
        x_field: str,
        metric: str,
        series: List[Dict],
        n: int,
        other_label: str,
        result_context: Dict[str, Any],
        group_field: Optional[str] = None,
    ) -> Tuple[List[Dict], str]:
        groups: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        grouped_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        group_rows: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        series_fields = [s["field"] for s in series] if series else ([metric] if metric else [])
        deduped_fields: set[str] = set()

        for row in data:
            key = str(row.get(x_field, ""))
            grouped_rows[key].append(row)

        for key, rows in grouped_rows.items():
            for field in series_fields:
                values = [_numeric(row.get(field, 0)) for row in rows]
                if self._should_dedupe_metric(field, rows, result_context):
                    groups[key][field] = max(values) if values else 0.0
                    deduped_fields.add(field)
                else:
                    groups[key][field] = sum(values)

        sort_field = metric or (series_fields[0] if series_fields else "")
        sorted_keys = sorted(groups.keys(), key=lambda item: groups[item].get(sort_field, 0), reverse=True)
        top_keys = sorted_keys[:n]
        rest_keys = sorted_keys[n:]

        if not group_field:
            chart_data = [{x_field: key, **{field: groups[key][field] for field in series_fields}} for key in top_keys]
        else:
            for row in data:
                row_key = str(row.get(x_field, ""))
                if row_key not in top_keys:
                    continue
                group_value = str(row.get(group_field, ""))
                group_rows[row_key][group_value].append(row)
            chart_data = []
            for key in top_keys:
                for group_value, rows in sorted(group_rows[key].items(), key=lambda item: _sort_value(item[0])):
                    values = {
                        field: self._aggregate_group_metric_values(rows, field, result_context)
                        for field in series_fields
                    }
                    for field in series_fields:
                        if self._should_dedupe_metric(field, rows, result_context):
                            deduped_fields.add(field)
                    chart_data.append({x_field: key, group_field: group_value, **values})

        if rest_keys:
            if not group_field:
                other = {x_field: other_label}
                for field in series_fields:
                    other[field] = sum(groups[key][field] for key in rest_keys)
                chart_data.append(other)
            else:
                other_group_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
                for row in data:
                    row_key = str(row.get(x_field, ""))
                    if row_key not in rest_keys:
                        continue
                    group_value = str(row.get(group_field, ""))
                    other_group_rows[group_value].append(row)
                for group_value, rows in sorted(other_group_rows.items(), key=lambda item: _sort_value(item[0])):
                    values = {
                        field: self._aggregate_group_metric_values(rows, field, result_context)
                        for field in series_fields
                    }
                    for field in series_fields:
                        if self._should_dedupe_metric(field, rows, result_context):
                            deduped_fields.add(field)
                    chart_data.append({x_field: other_label, group_field: group_value, **values})

        note = f"Top {n} of {len(groups)} categories by {sort_field}"
        if deduped_fields:
            deduped_list = ", ".join(sorted(deduped_fields))
            note += f"; repeated-grain guardrail used max/unique semantics for {deduped_list}"
        return chart_data, note

    def _agg_frequency(
        self,
        data: List[Dict[str, Any]],
        field: str,
        top_n: int,
        x_field: str,
    ) -> Tuple[List[Dict], str]:
        counts: Dict[str, int] = defaultdict(int)
        for row in data:
            counts[str(row.get(field, ""))] += 1
        sorted_items = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        chart_data = [{x_field: key, "count": value} for key, value in sorted_items[:top_n]]
        note = f"Top {top_n} of {len(counts)} unique values by frequency"
        return chart_data, note

    def _agg_time_bucket(
        self,
        data: List[Dict[str, Any]],
        config: Dict[str, Any],
        transform: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict], str]:
        field = transform["field"]
        metric = transform.get("metric")
        function = transform.get("function", "sum")
        bucket = transform.get("bucket", "month")
        group_field = config.get("groupByField")
        series = config.get("series", [])
        series_fields = [series[0]["field"]] if not metric and series else []
        metric_fields = [metric] if metric else series_fields or ["count"]

        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        skipped_rows = 0
        for row in data:
            dt = _coerce_datetime(row.get(field))
            if not dt:
                skipped_rows += 1
                continue
            bucket_label = _bucket_datetime(dt, bucket)
            group_value = str(row.get(group_field, "")) if group_field else ""
            grouped[(bucket_label, group_value)].append(row)

        chart_data: List[Dict[str, Any]] = []
        coerced_metrics: set[str] = set()
        for (bucket_label, group_value), rows in sorted(grouped.items(), key=lambda item: item[0][0]):
            row_out: Dict[str, Any] = {config["xAxisField"]: bucket_label}
            if group_field:
                row_out[group_field] = group_value
            for field_name in metric_fields:
                if field_name == "count":
                    row_out["count"] = len(rows)
                    continue
                values = [_numeric(r.get(field_name, 0)) for r in rows]
                effective_function = function
                if effective_function == "count" and _is_count_like_metric_name(field_name):
                    effective_function = "sum"
                    coerced_metrics.add(field_name)
                row_out[field_name] = _aggregate_values(
                    values,
                    effective_function,
                    field_name,
                    rows,
                    result_context,
                    self._should_dedupe_metric,
                )
            chart_data.append(row_out)

        note = f"Bucketed {len(chart_data)} points by {bucket}"
        if coerced_metrics:
            note += "; used sum instead of count for pre-aggregated metrics: " + ", ".join(sorted(coerced_metrics))
        if skipped_rows:
            note += f"; skipped {skipped_rows} rows with unparseable {field} values"
        return chart_data, note

    def _agg_histogram(
        self,
        data: List[Dict[str, Any]],
        transform: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict], str]:
        field = transform["field"]
        bins = transform.get("bins", 12)
        metric = transform.get("metric")
        function = transform.get("function", "count")
        numeric_rows = [
            (row, _numeric(row.get(field)))
            for row in data
            if row.get(field) is not None
        ]
        numeric_rows = [(row, value) for row, value in numeric_rows if math.isfinite(value)]
        values = sorted(value for _, value in numeric_rows)
        if not values:
            return [], "No numeric values available for histogram"
        lo, hi = values[0], values[-1]
        value_field = metric or "count"
        if math.isclose(lo, hi):
            rows = [row for row, _ in numeric_rows]
            values_for_metric = [_numeric(row.get(metric, 0)) for row in rows] if metric else []
            aggregated_value = (
                _aggregate_values(values_for_metric, function, metric, rows, result_context, self._should_dedupe_metric)
                if metric
                else float(len(rows))
            )
            return [{"bucket": f"{lo:g}", "bucketStart": lo, "bucketEnd": hi, value_field: aggregated_value}], "Single-value histogram"
        width = (hi - lo) / bins
        bucket_rows: List[List[Dict[str, Any]]] = [[] for _ in range(bins)]
        for row, value in numeric_rows:
            index = min(int((value - lo) / width), bins - 1)
            bucket_rows[index].append(row)
        chart_data = []
        for index, rows in enumerate(bucket_rows):
            start = lo + index * width
            end = lo + (index + 1) * width
            values_for_metric = [_numeric(row.get(metric, 0)) for row in rows] if metric else []
            aggregated_value = (
                _aggregate_values(values_for_metric, function, metric, rows, result_context, self._should_dedupe_metric)
                if metric
                else float(len(rows))
            )
            chart_data.append(
                {
                    "bucket": f"{start:.1f}–{end:.1f}",
                    "bucketStart": start,
                    "bucketEnd": end,
                    value_field: aggregated_value,
                }
            )
        return chart_data, f"Histogram with {bins} bins for {field}"

    def _agg_percent_of_total(
        self,
        data: List[Dict[str, Any]],
        config: Dict[str, Any],
        transform: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict], str]:
        metric = transform.get("metric") or (config.get("series", [{}])[0].get("field") if config.get("series") else "")
        if not metric:
            return [], "Percent-of-total skipped because no metric was available"
        x_field = config.get("xAxisField")
        group_field = config.get("groupByField")
        if not x_field:
            return [], "Percent-of-total skipped because no x-axis field was available"
        if group_field:
            grouped = self._pivot_group_metric(data, x_field, group_field, metric, result_context)
            normalized: List[Dict[str, Any]] = []
            for x_value, groups in grouped.items():
                total = sum(groups.values()) or 1.0
                for group_value, value in groups.items():
                    normalized.append(
                        {
                            x_field: x_value,
                            group_field: group_value,
                            metric: round((value / total) * 100, 4),
                        }
                    )
            return normalized, f"Converted grouped {metric} values to percent-of-total within each {x_field}"

        totals: Dict[str, float] = defaultdict(float)
        grouped_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in data:
            key = str(row.get(x_field, ""))
            grouped_rows[key].append(row)
        for key, rows in grouped_rows.items():
            values = [_numeric(row.get(metric, 0)) for row in rows]
            totals[key] = _aggregate_values(values, "sum", metric, rows, result_context, self._should_dedupe_metric)
        grand_total = sum(totals.values()) or 1.0
        chart_data = [{x_field: key, metric: round((value / grand_total) * 100, 4)} for key, value in totals.items()]
        chart_data.sort(key=lambda row: row[metric], reverse=True)
        return chart_data, f"Converted {metric} values to percent-of-total"

    def _agg_heatmap(
        self,
        data: List[Dict[str, Any]],
        transform: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict], str]:
        x_field = transform["xField"]
        y_field = transform["yField"]
        metric = transform.get("metric")
        function = transform.get("function", "sum")
        x_order = transform.get("xOrder", "asc")
        y_order = transform.get("yOrder", "asc")
        cells: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for row in data:
            cells[(str(row.get(x_field, "")), str(row.get(y_field, "")))].append(row)
        chart_data: List[Dict[str, Any]] = []
        value_field = metric or "value"
        x_values = sorted({x_value for x_value, _ in cells.keys()}, key=_sort_value, reverse=x_order == "desc")
        y_values = sorted({y_value for _, y_value in cells.keys()}, key=_sort_value, reverse=y_order == "desc")
        populated_cells = 0
        for x_value in x_values:
            for y_value in y_values:
                rows = cells.get((x_value, y_value), [])
                if rows:
                    populated_cells += 1
                if metric:
                    values = [_numeric(row.get(metric, 0)) for row in rows]
                    value = _aggregate_values(values, function, metric, rows, result_context, self._should_dedupe_metric)
                else:
                    value = float(len(rows))
                chart_data.append({x_field: x_value, y_field: y_value, value_field: value})
        note = f"Built heatmap matrix with {len(chart_data)} cells ({populated_cells} populated)"
        return chart_data, note

    def _agg_boxplot(
        self,
        data: List[Dict[str, Any]],
        transform: Dict[str, Any],
    ) -> Tuple[List[Dict], str]:
        field = transform["field"]
        group_field = transform.get("groupField")
        grouped_values: Dict[str, List[float]] = defaultdict(list)
        if group_field:
            for row in data:
                grouped_values[str(row.get(group_field, ""))].append(_numeric(row.get(field)))
        else:
            grouped_values[field] = [_numeric(row.get(field)) for row in data]

        chart_data: List[Dict[str, Any]] = []
        for label, values in grouped_values.items():
            clean = sorted(value for value in values if not math.isnan(value))
            if not clean:
                continue
            q1, median, q3 = _quartiles(clean)
            chart_data.append(
                {
                    transform.get("groupField") or "label": label,
                    "min": clean[0],
                    "q1": q1,
                    "median": median,
                    "q3": q3,
                    "max": clean[-1],
                }
            )
        chart_data.sort(key=lambda row: str(next(iter(row.values()))))
        note = f"Summarized {field} into boxplot statistics"
        return chart_data, note

    def _agg_period_comparison(
        self,
        data: List[Dict[str, Any]],
        transform: Dict[str, Any],
        comparison_type: str,
        result_context: Dict[str, Any],
        sort_by: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Dict], str]:
        entity_field = transform["entityField"]
        period_field = transform["periodField"]
        metric = transform.get("metric")
        function = transform.get("function", "sum")
        top_n = transform.get("topN", 10)

        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        periods: List[str] = []
        for row in data:
            entity = str(row.get(entity_field, ""))
            period = str(row.get(period_field, ""))
            if not entity or not period:
                continue
            grouped[(entity, period)].append(row)
            periods.append(period)

        ordered_periods = sorted({period for period in periods}, key=_period_sort_value)
        if len(ordered_periods) < 2:
            return [], f"{comparison_type} skipped because fewer than two periods were available"
        start_label, end_label = ordered_periods[-2], ordered_periods[-1]

        entity_values: Dict[str, Dict[str, float]] = defaultdict(dict)
        for (entity, period), rows in grouped.items():
            if metric:
                values = [_numeric(row.get(metric, 0)) for row in rows]
                entity_values[entity][period] = _aggregate_values(
                    values,
                    function,
                    metric,
                    rows,
                    result_context,
                    self._should_dedupe_metric,
                )
            else:
                entity_values[entity][period] = float(len(rows))

        comparison_rows: List[Dict[str, Any]] = []
        excluded_entities = 0
        for entity, period_map in entity_values.items():
            if start_label not in period_map or end_label not in period_map:
                excluded_entities += 1
                continue
            start_value = period_map[start_label]
            end_value = period_map[end_label]
            comparison_rows.append(
                {
                    entity_field: entity,
                    "startLabel": start_label,
                    "endLabel": end_label,
                    "startValue": start_value,
                    "endValue": end_value,
                    "delta": end_value - start_value,
                }
            )

        if not comparison_rows:
            transform["compareLabels"] = [start_label, end_label]
            return [], f"{comparison_type} skipped because no entities had data in both {start_label} and {end_label}"

        if comparison_type == "rankingSlope":
            start_ranks = self._rank_rows(comparison_rows, entity_field, "startValue")
            end_ranks = self._rank_rows(comparison_rows, entity_field, "endValue")
            for row in comparison_rows:
                row["startRank"] = start_ranks[row[entity_field]]
                row["endRank"] = end_ranks[row[entity_field]]
            note = f"Compared {len(comparison_rows)} entities across {start_label} and {end_label} with rank alignment"
        else:
            note = f"Computed deltas across {start_label} and {end_label}"

        if excluded_entities:
            note += f"; excluded {excluded_entities} entities without both periods"

        ranked_rows = self._sort_period_comparison_rows(comparison_rows, comparison_type, entity_field, sort_by)
        trimmed = ranked_rows[:top_n]
        transform["compareLabels"] = [start_label, end_label]
        return trimmed, note

    def _sort_period_comparison_rows(
        self,
        rows: List[Dict[str, Any]],
        comparison_type: str,
        entity_field: str,
        sort_by: Optional[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        if not rows:
            return rows

        if sort_by:
            field = sort_by.get("field", "")
            reverse = sort_by.get("order", "desc") == "desc"
            if all(field in row for row in rows):
                return sorted(rows, key=lambda row: _sort_value(row.get(field)), reverse=reverse)
            if field == entity_field:
                return sorted(rows, key=lambda row: _sort_value(row.get(entity_field)), reverse=reverse)

        if comparison_type == "rankingSlope":
            return sorted(rows, key=lambda row: min(_numeric(row.get("startRank", 999999)), _numeric(row.get("endRank", 999999))))
        return sorted(rows, key=lambda row: abs(_numeric(row.get("delta", 0))), reverse=True)

    def _normalize_percent_by_group(
        self,
        rows: List[Dict[str, Any]],
        config: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        x_field = config["xAxisField"]
        group_field = config["groupByField"]
        series_fields = [series["field"] for series in config.get("series", [])]
        grouped_rows: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        x_order: List[str] = []
        group_order: Dict[str, List[str]] = defaultdict(list)

        for row in rows:
            key = str(row.get(x_field, ""))
            group_value = str(row.get(group_field, ""))
            if key not in grouped_rows:
                x_order.append(key)
            if group_value not in grouped_rows[key]:
                group_order[key].append(group_value)
            grouped_rows[key][group_value].append(row)

        aggregated_rows: List[Dict[str, Any]] = []
        totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for key in x_order:
            for group_value in group_order[key]:
                bucket_rows = grouped_rows[key][group_value]
                aggregated_row: Dict[str, Any] = {x_field: key, group_field: group_value}
                for field in series_fields:
                    values = [_numeric(row.get(field, 0)) for row in bucket_rows]
                    aggregated_value = _aggregate_values(
                        values,
                        "sum",
                        field,
                        bucket_rows,
                        result_context,
                        self._should_dedupe_metric,
                    )
                    aggregated_row[field] = aggregated_value
                    totals[key][field] += aggregated_value
                aggregated_rows.append(aggregated_row)

        normalized: List[Dict[str, Any]] = []
        for row in aggregated_rows:
            key = str(row.get(x_field, ""))
            new_row = {x_field: key, group_field: row.get(group_field, "")}
            for field in series_fields:
                total = totals[key][field] or 1.0
                new_row[field] = round((_numeric(row.get(field, 0)) / total) * 100, 4)
            normalized.append(new_row)
        return normalized

    def _pivot_group_metric(
        self,
        data: List[Dict[str, Any]],
        x_field: str,
        group_field: str,
        metric: str,
        result_context: Dict[str, Any],
    ) -> Dict[str, Dict[str, float]]:
        grouped: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        grouped_rows: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for row in data:
            x_value = str(row.get(x_field, ""))
            group_value = str(row.get(group_field, ""))
            grouped[x_value][group_value].append(_numeric(row.get(metric, 0)))
            grouped_rows[x_value][group_value].append(row)

        resolved: Dict[str, Dict[str, float]] = defaultdict(dict)
        for x_value, groups in grouped.items():
            for group_value, values in groups.items():
                rows = grouped_rows[x_value][group_value]
                resolved[x_value][group_value] = _aggregate_values(values, "sum", metric, rows, result_context, self._should_dedupe_metric)
        return resolved

    def _should_dedupe_metric(
        self,
        field: str,
        rows: List[Dict[str, Any]],
        result_context: Dict[str, Any],
    ) -> bool:
        """Avoid summing repeated higher-level metrics across detail rows."""
        if len(rows) <= 1:
            return False

        repeated_grain = bool(result_context.get("row_grain_hint"))
        lower_field = field.lower()

        if repeated_grain and any(token in lower_field for token in _DEDUPED_METRIC_TOKENS):
            return True

        if repeated_grain:
            values = [_numeric(row.get(field, 0)) for row in rows]
            if len({round(value, 9) for value in values}) == 1:
                return True

        return False

    def _infer_field_kinds(self, columns: Sequence[str], data: List[Dict[str, Any]]) -> Dict[str, str]:
        kinds: Dict[str, str] = {}
        sample = data[: min(len(data), 25)]
        for column in columns:
            values = [row.get(column) for row in sample if row.get(column) is not None]
            if not values:
                kinds[column] = "text"
                continue
            if all(_is_numeric_like(value) for value in values):
                kinds[column] = "numeric"
            elif all(_is_date_like(value) for value in values):
                kinds[column] = "date"
            else:
                kinds[column] = "text"
        return kinds

    def _rank_numeric_fields_for_series(
        self,
        columns: Sequence[str],
        kinds: Dict[str, str],
        data: List[Dict[str, Any]],
    ) -> List[str]:
        scored: List[Tuple[float, str]] = []
        sample = data[: min(len(data), 50)]
        for column in columns:
            if kinds.get(column) != "numeric":
                continue
            lowered = column.lower()
            if any(token in lowered for token in _ID_FIELD_TOKENS):
                continue
            score = 0.0
            if any(token in lowered for token in ("amount", "cost", "paid", "charge", "price", "revenue", "sales", "count", "total", "avg", "average", "percent", "ratio", "share", "rate")):
                score += 5.0
            if any(token in lowered for token in _LOW_VALUE_NUMERIC_TOKENS):
                score -= 2.0
            values = [row.get(column) for row in sample if row.get(column) is not None]
            unique_ratio = (len({str(value) for value in values}) / len(values)) if values else 0.0
            if unique_ratio > 0.95 and not any(token in lowered for token in ("age", "year", "month", "day", "week", "quarter", "bucket", "bin")):
                score -= 3.0
            if values:
                score += min(len(values), 10) / 10.0
            scored.append((score, column))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [column for _, column in scored]

    def _rank_dimension_fields(
        self,
        columns: Sequence[str],
        kinds: Dict[str, str],
        data: List[Dict[str, Any]],
        exclude: Optional[str] = None,
    ) -> List[str]:
        scored: List[Tuple[float, str]] = []
        sample = data[: min(len(data), 50)]
        for column in columns:
            if column == exclude or kinds.get(column) not in {"text", "date"}:
                continue
            lowered = column.lower()
            values = [row.get(column) for row in sample if row.get(column) not in (None, "")]
            unique_count = len({str(value) for value in values})
            unique_ratio = (unique_count / len(values)) if values else 0.0
            score = 0.0
            if kinds.get(column) == "date":
                score += 6.0
            if any(token in lowered for token in ("date", "time", "month", "year", "week", "quarter", "day", "period")):
                score += 5.0
            if any(token in lowered for token in ("name", "type", "category", "status", "segment", "region", "state", "gender", "provider", "plan", "benefit")):
                score += 3.0
            if any(token in lowered for token in _ID_FIELD_TOKENS):
                score -= 4.0
            if unique_ratio > 0.9:
                score -= 3.0
            elif unique_count <= 12:
                score += 2.5
            elif unique_count <= 24:
                score += 1.0
            scored.append((score, column))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [column for _, column in scored]

    def _build_heuristic_intent(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        original_query: str,
        result_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        kinds = self._infer_field_kinds(columns, data)
        numeric_fields = self._rank_numeric_fields_for_series(columns, kinds, data)
        dimension_fields = self._rank_dimension_fields(columns, kinds, data)
        if not numeric_fields:
            return {"plottable": False}

        x_field = dimension_fields[0] if dimension_fields else None
        group_field = dimension_fields[1] if len(dimension_fields) > 1 else None
        if x_field and group_field and self._dimensions_are_redundant(x_field, group_field, data):
            group_field = None
        primary_metric = numeric_fields[0]
        secondary_metric = numeric_fields[1] if len(numeric_fields) > 1 else None
        tertiary_metric = numeric_fields[2] if len(numeric_fields) > 2 else None
        chart_type = "bar"
        layout = None
        transform: Optional[Dict[str, Any]] = None
        sort_by: Optional[Dict[str, str]] = None
        z_axis_field: Optional[str] = None
        query_lower = (original_query or "").lower()

        if x_field and self._looks_like_identifier_field(x_field) and primary_metric:
            x_field = primary_metric
            group_field = None
            chart_type = "bar"
            transform = {
                "type": "histogram",
                "field": primary_metric,
                "bins": 10,
            }
        if x_field and kinds.get(x_field) == "date":
            chart_type = "stackedArea" if group_field else "line"
            layout = "stacked" if group_field else None
            sort_by = {"field": x_field, "order": "asc"}
            bucket = "month"
            if any(token in query_lower for token in ("year", "yearly", "annual")):
                bucket = "year"
            elif any(token in query_lower for token in ("quarter", "quarterly")):
                bucket = "quarter"
            elif any(token in query_lower for token in ("week", "weekly")):
                bucket = "week"
            transform = {
                "type": "timeBucket",
                "field": x_field,
                "bucket": bucket,
                "metric": primary_metric,
                "function": "sum",
            }
        elif (
            (len(numeric_fields) >= 2 and any(token in query_lower for token in ("correlation", "relationship", "vs", "versus", "compare")))
            or (len(numeric_fields) >= 2 and not x_field)
        ):
            chart_type = "scatter" if not x_field or kinds.get(x_field) == "numeric" else "dualAxis"
            if chart_type == "scatter" and x_field:
                sort_by = {"field": x_field, "order": "asc"}
                z_axis_field = tertiary_metric if tertiary_metric not in {x_field, primary_metric} else None
        elif group_field:
            chart_type = "stackedBar"
            layout = "stacked"
            sort_by = {"field": primary_metric, "order": "desc"}
            if len(data) > 12:
                transform = {
                    "type": "topN",
                    "metric": primary_metric,
                    "n": 10,
                    "otherLabel": "Other",
                }
        elif x_field:
            unique_count = len({str(row.get(x_field, "")) for row in data if row.get(x_field) not in (None, "")})
            if unique_count <= 6 and any(token in query_lower for token in ("share", "mix", "composition", "breakdown", "percent")):
                chart_type = "pie"
            else:
                chart_type = "bar"
                sort_by = {"field": primary_metric, "order": "desc"}
                if unique_count > 12:
                    transform = {
                        "type": "topN",
                        "metric": primary_metric,
                        "n": 10,
                        "otherLabel": "Other",
                    }

        if x_field and self._should_bucket_numeric_field(x_field, data) and chart_type not in {"scatter", "dualAxis"}:
            chart_type = "bar"
            layout = None
            group_field = None
            transform = self._build_histogram_transform(x_field, data)

        series = [
            {
                "field": primary_metric,
                "name": primary_metric.replace("_", " ").title(),
                "format": self._infer_format(primary_metric),
                "chartType": "bar" if chart_type == "dualAxis" else None,
                "axis": "primary",
            }
        ]
        if chart_type == "dualAxis" and secondary_metric:
            series.append(
                {
                    "field": secondary_metric,
                    "name": secondary_metric.replace("_", " ").title(),
                    "format": self._infer_format(secondary_metric),
                    "chartType": "line",
                    "axis": "secondary",
                }
            )

        label = result_context.get("label") or "Chart"
        title = label if label else f"{chart_type.title()} chart"
        return {
            "plottable": True,
            "chartType": chart_type,
            "title": title,
            "xAxisField": x_field,
            "zAxisField": z_axis_field if chart_type == "scatter" else None,
            "groupByField": group_field if chart_type not in {"scatter", "pie", "dualAxis"} else None,
            "layout": layout,
            "series": series,
            "sortBy": sort_by,
            "transform": transform,
            "referenceLines": [],
        }

    def _looks_like_identifier_field(self, field: str) -> bool:
        lowered = field.lower()
        return any(token in lowered for token in _ID_FIELD_TOKENS)

    def _should_bucket_numeric_field(self, field: Optional[str], data: List[Dict[str, Any]]) -> bool:
        if not field:
            return False

        lowered = field.lower()
        if self._looks_like_identifier_field(field):
            return False
        if any(token in lowered for token in _DISCRETE_NUMERIC_CATEGORY_TOKENS):
            return False

        sample = data[: min(len(data), 100)]
        values = [_numeric(row.get(field)) for row in sample if row.get(field) is not None]
        finite_values = [value for value in values if math.isfinite(value)]
        if len(finite_values) < 5:
            return False

        unique_count = len({round(value, 6) for value in finite_values})
        unique_ratio = unique_count / len(finite_values)
        if unique_count < 5:
            return False

        if any(token in lowered for token in _CONTINUOUS_NUMERIC_TOKENS):
            return True

        return unique_ratio >= 0.6 and unique_count >= 8

    def _build_histogram_transform(self, field: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        sample = data[: min(len(data), 200)]
        values = [_numeric(row.get(field)) for row in sample if row.get(field) is not None]
        unique_count = len({round(value, 6) for value in values if math.isfinite(value)})
        bins = 12 if unique_count >= 20 else 10 if unique_count >= 10 else 8
        return {
            "type": "histogram",
            "field": field,
            "bins": bins,
            "syntheticSeries": [
                {
                    "field": "count",
                    "name": "Count",
                    "format": "number",
                    "chartType": None,
                    "axis": "primary",
                }
            ],
        }

    def _dimensions_are_redundant(
        self,
        primary_field: str,
        secondary_field: str,
        data: List[Dict[str, Any]],
    ) -> bool:
        sample = data[: min(len(data), 100)]
        pairs = [
            (str(row.get(primary_field, "")), str(row.get(secondary_field, "")))
            for row in sample
            if row.get(primary_field) not in (None, "") and row.get(secondary_field) not in (None, "")
        ]
        if len(pairs) < 2:
            return False

        primary_to_secondary: Dict[str, set[str]] = defaultdict(set)
        secondary_to_primary: Dict[str, set[str]] = defaultdict(set)
        for primary_value, secondary_value in pairs:
            primary_to_secondary[primary_value].add(secondary_value)
            secondary_to_primary[secondary_value].add(primary_value)

        looks_like_code_description = (
            ("code" in primary_field.lower() and "description" in secondary_field.lower())
            or ("description" in primary_field.lower() and "code" in secondary_field.lower())
        )
        one_to_one = all(len(values) == 1 for values in primary_to_secondary.values()) and all(
            len(values) == 1 for values in secondary_to_primary.values()
        )
        return looks_like_code_description or one_to_one

    def _build_chart_meta(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        resolved_config: Dict[str, Any],
        result_context: Dict[str, Any],
        notes: List[str],
    ) -> Dict[str, Any]:
        chart_type = resolved_config.get("chartType", "bar")
        x_field = resolved_config.get("xAxisField")
        group_field = resolved_config.get("groupByField")
        series = resolved_config.get("series") or []
        primary_series = series[0]["field"] if series else None
        rationale_bits = []
        if x_field and primary_series:
            rationale_bits.append(
                f"{chart_type} selected for {primary_series.replace('_', ' ')} by {x_field.replace('_', ' ')}"
            )
        if group_field:
            rationale_bits.append(f"with breakdown by {group_field.replace('_', ' ')}")
        if result_context.get("row_grain_hint"):
            rationale_bits.append("row-grain guardrails applied")
        confidence = 0.86
        if resolved_config.get("transform"):
            confidence -= 0.05
        if any("Downgraded" in note or "Filled missing" in note for note in notes):
            confidence -= 0.12
        description_bits = [result_context.get("row_grain_hint") or ""]
        return {
            "source": "auto",
            "rationale": " • ".join(bit for bit in rationale_bits if bit) or "Automatically generated chart.",
            "confidence": max(0.35, min(confidence, 0.99)),
            "description": " • ".join(bit for bit in description_bits if bit) or None,
            "normalizationNotes": notes,
            "fallbackApplied": any(
                "best-effort" in note.lower()
                or "downgraded" in note.lower()
                or "filled missing" in note.lower()
                for note in notes
            ),
            "candidateFields": {
                "dimensions": self._rank_dimension_fields(columns, self._infer_field_kinds(columns, data), data)[:5],
                "measures": self._rank_numeric_fields_for_series(columns, self._infer_field_kinds(columns, data), data)[:5],
            },
        }

    def _auto_compact_rows(
        self,
        rows: List[Dict[str, Any]],
        config: Dict[str, Any],
        result_context: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], str]:
        x_field = config.get("xAxisField")
        group_field = config.get("groupByField")
        series = config.get("series") or []
        metric = series[0]["field"] if series else ""
        if not x_field:
            return [], ""

        sample_rows = rows[: min(len(rows), 50)]
        kinds = self._infer_field_kinds(list(sample_rows[0].keys()) if sample_rows else [], sample_rows)

        if kinds.get(x_field) == "date":
            transform = {"field": x_field, "metric": metric, "function": "sum", "bucket": "month"}
            compacted, note = self._agg_time_bucket(rows, config, transform, result_context)
            return compacted, note

        if group_field:
            compacted, note = self._agg_top_n(
                data=rows,
                x_field=x_field,
                metric=metric,
                series=series,
                n=min(10, MAX_CHART_POINTS),
                other_label="Other",
                result_context=result_context,
                group_field=group_field,
            )
            return compacted, note

        if metric:
            compacted, note = self._agg_top_n(
                data=rows,
                x_field=x_field,
                metric=metric,
                series=series,
                n=min(10, MAX_CHART_POINTS),
                other_label="Other",
                result_context=result_context,
            )
            return compacted, note

        compacted, note = self._agg_frequency(rows, x_field, min(10, MAX_CHART_POINTS), x_field)
        return compacted, note

    def _coerce_field(self, candidate: Any, columns: Sequence[str]) -> Optional[str]:
        return candidate if isinstance(candidate, str) and candidate in columns else None

    def _pick_default_x_field(self, columns: Sequence[str], kinds: Dict[str, str]) -> Optional[str]:
        return self._pick_date_or_categorical_field(columns, kinds)

    def _pick_date_or_categorical_field(
        self,
        columns: Sequence[str],
        kinds: Dict[str, str],
        exclude: Optional[str] = None,
    ) -> Optional[str]:
        for preferred_kind in ("date", "text"):
            for column in columns:
                if column == exclude:
                    continue
                if kinds.get(column) == preferred_kind:
                    return column
        return None

    def _pick_categorical_field(self, columns: Sequence[str], kinds: Dict[str, str]) -> Optional[str]:
        for column in columns:
            if kinds.get(column) == "text":
                return column
        for column in columns:
            if kinds.get(column) == "date":
                return column
        return None

    def _pick_secondary_dimension(
        self,
        columns: Sequence[str],
        kinds: Dict[str, str],
        primary: Optional[str],
    ) -> Optional[str]:
        for column in columns:
            if column == primary:
                continue
            if kinds.get(column) in {"text", "date"}:
                return column
        return None

    def _infer_format(self, field: str) -> str:
        lowered = field.lower()
        if any(token in lowered for token in ("cost", "amount", "price", "paid", "charge", "copay", "coinsurance")):
            return "currency"
        if any(token in lowered for token in ("percent", "pct", "ratio", "share")):
            return "percent"
        return "number"

    def _is_chart_type_supported(self, chart_type: str, layout: Optional[str]) -> bool:
        capability = CHART_CAPABILITY_MODEL.get(chart_type)
        if not capability:
            return False
        if layout is None:
            return True
        return layout in capability.get("layouts", set())

    def _rank_rows(
        self,
        rows: List[Dict[str, Any]],
        entity_field: str,
        value_field: str,
    ) -> Dict[str, int]:
        sorted_rows = sorted(rows, key=lambda row: _numeric(row.get(value_field, 0)), reverse=True)
        ranks: Dict[str, int] = {}
        current_rank = 0
        previous_value: Optional[float] = None
        for index, row in enumerate(sorted_rows, start=1):
            value = _numeric(row.get(value_field, 0))
            if previous_value is None or not math.isclose(value, previous_value, rel_tol=1e-9, abs_tol=1e-9):
                current_rank = index
                previous_value = value
            ranks[str(row.get(entity_field, ""))] = current_rank
        return ranks

    # ------------------------------------------------------------------
    # Stage 3: Size guard
    # ------------------------------------------------------------------

    def _size_guard(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if _payload_size_bytes(payload) <= MAX_JSON_BYTES:
            return payload

        logger.warning(f"Chart payload {_payload_size_bytes(payload)}B exceeds {MAX_JSON_BYTES}B, trimming downloadData")
        download_data = payload.get("downloadData", [])
        while download_data and _payload_size_bytes(payload) > MAX_JSON_BYTES:
            download_data = download_data[: len(download_data) // 2]
            payload["downloadData"] = download_data

        if _payload_size_bytes(payload) > MAX_JSON_BYTES:
            payload.pop("downloadData", None)
            logger.warning("Dropped downloadData entirely to meet size limit")

        chart_data = payload.get("chartData", [])
        while chart_data and _payload_size_bytes(payload) > MAX_JSON_BYTES:
            if len(chart_data) == 1:
                chart_data = []
            else:
                chart_data = chart_data[: max(1, len(chart_data) // 2)]
            payload["chartData"] = chart_data

        if _payload_size_bytes(payload) > MAX_JSON_BYTES:
            logger.warning("Payload still exceeds size limit after trimming rows, truncating long strings")
            for max_length in (2048, 1024, 512, 256, 128):
                payload = _truncate_payload_strings(payload, max_length)
                if _payload_size_bytes(payload) <= MAX_JSON_BYTES:
                    break

        return payload


def _payload_size_bytes(payload: Dict[str, Any]) -> int:
    return len(json.dumps(payload, default=_json_default).encode())


def _truncate_payload_strings(value: Any, max_length: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_length else f"{value[:max_length]}..."
    if isinstance(value, list):
        return [_truncate_payload_strings(item, max_length) for item in value]
    if isinstance(value, dict):
        return {key: _truncate_payload_strings(item, max_length) for key, item in value.items()}
    return value


def _normalize_plottable(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0", ""}:
            return False
    return bool(value)


def _extract_json_object(content: str) -> Any:
    decoder = json.JSONDecoder()
    stripped = content.strip()
    if stripped:
        try:
            parsed, _ = decoder.raw_decode(stripped)
            return parsed
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(stripped[start:])
            return parsed
        except json.JSONDecodeError:
            start = stripped.find("{", start + 1)
    raise ValueError("No valid JSON object found in model response")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _numeric(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _is_numeric_like(val: Any) -> bool:
    if isinstance(val, bool):
        return False
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _is_date_like(val: Any) -> bool:
    if isinstance(val, (date, datetime)):
        return True
    if not isinstance(val, str):
        return False
    try:
        datetime.fromisoformat(val.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _coerce_datetime(val: Any) -> Optional[datetime]:
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _bucket_datetime(dt: datetime, bucket: str) -> str:
    if bucket == "day":
        return dt.strftime("%Y-%m-%d")
    if bucket == "week":
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    if bucket == "month":
        return dt.strftime("%Y-%m")
    if bucket == "quarter":
        quarter = ((dt.month - 1) // 3) + 1
        return f"{dt.year}-Q{quarter}"
    return dt.strftime("%Y")


def _aggregate_values(
    values: Sequence[float],
    function: str,
    field: str,
    rows: List[Dict[str, Any]],
    result_context: Dict[str, Any],
    dedupe_checker: Any,
) -> float:
    if function == "count_distinct":
        return float(len({str(row.get(field, "")) for row in rows if row.get(field) not in (None, "")}))
    if not values:
        return 0.0
    if function == "count":
        return float(len(rows))
    if function == "min":
        return min(values)
    if function == "max":
        return max(values)
    if function == "avg":
        return sum(values) / len(values)
    if dedupe_checker(field, rows, result_context):
        return max(values)
    return sum(values)


def _is_count_like_metric_name(field: str) -> bool:
    lowered = field.lower()
    if lowered in {"count", "cnt", "num", "number"}:
        return True
    return (
        lowered.endswith(("_count", "_cnt", "_num", "_number"))
        or lowered.startswith(("count_", "cnt_", "num_", "number_"))
        or "_count_" in lowered
        or "_cnt_" in lowered
        or "_num_" in lowered
        or "_number_" in lowered
    )


def _quartiles(values: Sequence[float]) -> Tuple[float, float, float]:
    sorted_values = sorted(values)
    if not sorted_values:
        return 0.0, 0.0, 0.0
    median = _median(sorted_values)
    midpoint = len(sorted_values) // 2
    lower = sorted_values[:midpoint]
    upper = sorted_values[midpoint + (0 if len(sorted_values) % 2 == 0 else 1):]
    q1 = _median(lower or sorted_values)
    q3 = _median(upper or sorted_values)
    return q1, median, q3


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(coerced, maximum))


def _format_number(value: float) -> str:
    if not math.isfinite(value):
        return "0"
    if abs(value) >= 100 or math.isclose(value, round(value)):
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _period_sort_value(value: Any) -> Any:
    if _is_date_like(value):
        dt = _coerce_datetime(value)
        if dt:
            return (0, dt.year, dt.month, dt.day)

    if isinstance(value, str):
        clean = value.strip()
        match = re.fullmatch(r"(\d{4})[-/](\d{1,2})$", clean)
        if match:
            return (1, int(match.group(1)), int(match.group(2)))
        match = re.fullmatch(r"(\d{4})[-/]Q([1-4])$", clean, re.IGNORECASE)
        if match:
            return (2, int(match.group(1)), int(match.group(2)))
        match = re.fullmatch(r"(\d{4})[-/]W(\d{1,2})$", clean, re.IGNORECASE)
        if match:
            return (3, int(match.group(1)), int(match.group(2)))

    if _is_numeric_like(value):
        return (4, _numeric(value))

    return (5, str(value or ""))


def _sort_value(value: Any) -> Any:
    if _is_date_like(value):
        dt = _coerce_datetime(value)
        if dt:
            return (0, dt.isoformat())
    if _is_numeric_like(value):
        return (1, _numeric(value))
    return (2, str(value or ""))
