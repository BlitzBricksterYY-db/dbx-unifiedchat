"""
Chart Generator Agent

Dedicated module for generating interactive chart specifications from query results.
Uses a separate LLM call for chart configuration (type, axes, formatting) and
Python for real data assembly with aggregation and size guards.

Architecture: LLM decides WHAT to visualize, Python provides REAL DATA.
"""

import json
import logging
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)

MAX_CHART_POINTS = 30
MAX_DOWNLOAD_ROWS = 200
MAX_JSON_BYTES = 50_000

CHART_CONFIG_PROMPT = """\
You are a data visualization expert. Given a query result table, output a JSON \
chart configuration describing HOW to visualize the data. Do NOT include the \
actual data values — only the configuration.

**Step 1 — Decide if plottable:**
- Return {{"plottable": false}} ONLY for fundamentally non-visual data: a \
single scalar value, all-text columns with no numeric dimension, or a single \
row with no comparison axis.
- High row count is NEVER a reason to skip — specify an aggregation strategy instead.

**Step 2 — Handle data volume (total rows: {row_count}):**
- <=30 rows: set "aggregation": null (plot all)
- 31-100 rows: use "aggregation": {{"type":"topN","n":20,"metric":"<primary_numeric_col>","otherLabel":"Other"}} \
or null with a line chart
- 100+ rows: ALWAYS specify an aggregation. Options:
  * {{"type":"topN","n":20,"metric":"<col>","otherLabel":"Other"}}
  * {{"type":"timeBucket","field":"<date_col>","bucket":"month","metric":"<col>","function":"sum"}}
  * {{"type":"histogram","field":"<numeric_col>","bins":15}}
  * {{"type":"frequency","field":"<categorical_col>","topN":20}}

**Step 3 — Choose chart type:**
- bar / grouped bar: comparing categories across metrics
- stacked bar (chartType: "bar", set series stack): composition within categories
- line: trends over time or ordered sequences
- pie: single metric distribution (only when ONE numeric column)
- scatter: correlation between two numeric columns

**Step 4 — Output this JSON structure:**
{{
  "plottable": true,
  "chartType": "bar",
  "title": "Descriptive title for the chart",
  "xAxisField": "<column for x-axis>",
  "groupByField": "<optional column to create multiple series>",
  "series": [
    {{"field": "<numeric_col>", "name": "Human-readable name", "format": "currency|percent|number"}}
  ],
  "sortBy": {{"field": "<col>", "order": "desc"}},
  "aggregation": null
}}

**Context:**
- User's question: {original_query}
- Columns: {columns}
- Row count: {row_count} total rows ({preview_count} shown below)
- Data preview:
{data_json}

Return ONLY valid JSON. No markdown, no explanations, no code fences."""


class ChartGenerator:
    """
    Generates interactive chart specifications from query result tables.

    Uses a dedicated LLM call for chart config (type, axes, formatting,
    aggregation strategy) and Python for assembling real data with size guards.
    """

    def __init__(self, llm: Runnable):
        self.llm = llm

    def generate_chart(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        original_query: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a chart specification for one result table.

        Returns a dict with keys (config, chartData, downloadData, totalRows,
        aggregated, aggregationNote) suitable for embedding as an echarts-chart
        code block, or None if not plottable / on error.
        """
        if not data or not columns:
            return None

        total_rows = len(data)

        # Stage 1: LLM generates config
        config = self._get_chart_config(columns, data, original_query, total_rows)
        if config is None or config.get("plottable") is False:
            return None

        # Stage 2: Assemble real data
        result = self._assemble_data(columns, data, config, total_rows)

        # Stage 3: Size guard
        result = self._apply_size_guard(result)

        return result

    # ------------------------------------------------------------------
    # Stage 1: LLM config generation
    # ------------------------------------------------------------------

    def _get_chart_config(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        original_query: str,
        row_count: int,
    ) -> Optional[dict]:
        preview = data[:50]
        data_json = self._safe_json_dumps(preview, indent=2)

        prompt = CHART_CONFIG_PROMPT.format(
            original_query=original_query,
            columns=json.dumps(columns),
            row_count=row_count,
            preview_count=len(preview),
            data_json=data_json,
        )

        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()

            # Strip accidental code fences
            if content.startswith("```"):
                first_newline = content.find("\n")
                content = content[first_newline + 1:] if first_newline != -1 else content[3:]
            if content.endswith("```"):
                content = content[:-3].rstrip()

            spec = json.loads(content)
            logger.info(f"Chart LLM returned config: chartType={spec.get('chartType')}, plottable={spec.get('plottable')}")
            return spec
        except json.JSONDecodeError as e:
            logger.warning(f"Chart LLM returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Chart config generation failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Stage 2: Data assembly
    # ------------------------------------------------------------------

    def _assemble_data(
        self,
        columns: List[str],
        data: List[Dict[str, Any]],
        config: dict,
        total_rows: int,
    ) -> Dict[str, Any]:
        aggregation = config.get("aggregation")
        aggregated = False
        aggregation_note = None

        if aggregation:
            chart_data, aggregation_note = self._apply_aggregation(data, config, aggregation)
            aggregated = True
        else:
            chart_data = data[:MAX_CHART_POINTS]
            if len(data) > MAX_CHART_POINTS:
                aggregated = True
                aggregation_note = f"Showing first {MAX_CHART_POINTS} of {total_rows} rows"

        # Ensure toolbox flag
        config["toolbox"] = True

        download_data = data[:MAX_DOWNLOAD_ROWS]

        return {
            "config": config,
            "chartData": chart_data,
            "downloadData": download_data,
            "totalRows": total_rows,
            "aggregated": aggregated,
            "aggregationNote": aggregation_note,
        }

    def _apply_aggregation(
        self,
        data: List[Dict[str, Any]],
        config: dict,
        aggregation: dict,
    ) -> tuple:
        """Apply the LLM-specified aggregation strategy using exact Python arithmetic."""
        agg_type = aggregation.get("type", "topN")

        try:
            if agg_type == "topN":
                return self._agg_top_n(data, config, aggregation)
            elif agg_type == "frequency":
                return self._agg_frequency(data, aggregation)
            elif agg_type == "histogram":
                return self._agg_histogram(data, aggregation)
            elif agg_type == "timeBucket":
                return self._agg_time_bucket(data, config, aggregation)
            else:
                logger.warning(f"Unknown aggregation type '{agg_type}', falling back to topN")
                return self._agg_top_n(data, config, {"type": "topN", "n": 20, "metric": self._first_numeric_col(data), "otherLabel": "Other"})
        except Exception as e:
            logger.warning(f"Aggregation failed ({agg_type}): {e}, using raw top rows")
            return data[:MAX_CHART_POINTS], f"First {min(len(data), MAX_CHART_POINTS)} of {len(data)} rows (aggregation failed)"

    def _agg_top_n(self, data, config, agg):
        n = min(agg.get("n", 20), MAX_CHART_POINTS - 1)
        metric = agg.get("metric") or self._first_numeric_col(data)
        other_label = agg.get("otherLabel", "Other")

        if not metric:
            return data[:MAX_CHART_POINTS], None

        sorted_data = sorted(data, key=lambda r: self._num(r.get(metric, 0)), reverse=True)
        top = sorted_data[:n]
        rest = sorted_data[n:]

        if rest:
            x_field = config.get("xAxisField", next(iter(data[0].keys())) if data else "category")
            other_row = {x_field: other_label}
            for s in config.get("series", []):
                field = s.get("field", "")
                other_row[field] = sum(self._num(r.get(field, 0)) for r in rest)
            top.append(other_row)

        note = f"Top {n} of {len(data)} by {metric}"
        return top, note

    def _agg_frequency(self, data, agg):
        field = agg.get("field")
        top_n = min(agg.get("topN", 20), MAX_CHART_POINTS)
        if not field:
            return data[:MAX_CHART_POINTS], None

        counter = Counter(str(r.get(field, "")) for r in data)
        most_common = counter.most_common(top_n)
        chart_data = [{field: val, "count": cnt} for val, cnt in most_common]
        return chart_data, f"Top {top_n} most frequent values of {field}"

    def _agg_histogram(self, data, agg):
        field = agg.get("field")
        bins = min(agg.get("bins", 15), MAX_CHART_POINTS)
        if not field:
            return data[:MAX_CHART_POINTS], None

        values = [self._num(r.get(field, 0)) for r in data if r.get(field) is not None]
        if not values:
            return [], "No numeric data for histogram"

        min_val, max_val = min(values), max(values)
        if min_val == max_val:
            return [{f"{field}_range": str(min_val), "count": len(values)}], None

        bin_width = (max_val - min_val) / bins
        chart_data = []
        for i in range(bins):
            lo = min_val + i * bin_width
            hi = lo + bin_width
            count = sum(1 for v in values if (lo <= v < hi) or (i == bins - 1 and v == hi))
            chart_data.append({f"{field}_range": f"{lo:.0f}-{hi:.0f}", "count": count})

        return chart_data, f"Distribution of {field} ({bins} bins)"

    def _agg_time_bucket(self, data, config, agg):
        field = agg.get("field")
        bucket = agg.get("bucket", "month")
        metric = agg.get("metric") or self._first_numeric_col(data)
        func = agg.get("function", "sum")

        if not field or not metric:
            return data[:MAX_CHART_POINTS], None

        buckets: Dict[str, list] = {}
        for row in data:
            val = row.get(field, "")
            key = self._time_bucket_key(val, bucket)
            if key:
                buckets.setdefault(key, []).append(self._num(row.get(metric, 0)))

        chart_data = []
        for key in sorted(buckets.keys()):
            vals = buckets[key]
            if func == "sum":
                agg_val = sum(vals)
            elif func == "avg":
                agg_val = sum(vals) / len(vals) if vals else 0
            elif func == "count":
                agg_val = len(vals)
            else:
                agg_val = sum(vals)
            chart_data.append({field: key, metric: agg_val})

        if len(chart_data) > MAX_CHART_POINTS:
            chart_data = chart_data[:MAX_CHART_POINTS]

        return chart_data, f"{metric} by {bucket} ({func})"

    # ------------------------------------------------------------------
    # Stage 3: Size guard
    # ------------------------------------------------------------------

    def _apply_size_guard(self, result: dict) -> dict:
        serialized = self._safe_json_dumps(result)
        size = len(serialized.encode("utf-8"))

        if size <= MAX_JSON_BYTES:
            return result

        logger.warning(f"Chart block {size} bytes > {MAX_JSON_BYTES} limit, trimming downloadData")

        # Progressively reduce downloadData
        download = result.get("downloadData", [])
        while size > MAX_JSON_BYTES and len(download) > 10:
            download = download[:len(download) // 2]
            result["downloadData"] = download
            serialized = self._safe_json_dumps(result)
            size = len(serialized.encode("utf-8"))

        if size > MAX_JSON_BYTES:
            result["downloadData"] = []
            logger.warning("Dropped downloadData entirely to meet size limit")

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _num(val) -> float:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, Decimal):
            return float(val)
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _first_numeric_col(data: List[dict]) -> Optional[str]:
        if not data:
            return None
        for key, val in data[0].items():
            if isinstance(val, (int, float, Decimal)):
                return key
        return None

    @staticmethod
    def _time_bucket_key(val, bucket: str) -> Optional[str]:
        if isinstance(val, (date, datetime)):
            d = val
        elif isinstance(val, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"):
                try:
                    d = datetime.strptime(val, fmt)
                    break
                except ValueError:
                    continue
            else:
                return val[:7] if len(val) >= 7 else val
        else:
            return str(val)

        if bucket == "month":
            return d.strftime("%Y-%m")
        elif bucket == "quarter":
            q = (d.month - 1) // 3 + 1
            return f"{d.year}-Q{q}"
        elif bucket == "year":
            return str(d.year)
        elif bucket == "week":
            return d.strftime("%Y-W%W")
        elif bucket == "day":
            return d.strftime("%Y-%m-%d")
        return d.strftime("%Y-%m")

    @staticmethod
    def _safe_json_dumps(obj: Any, indent: int = None) -> str:
        def default_handler(o):
            if isinstance(o, (date, datetime)):
                return o.isoformat()
            elif isinstance(o, Decimal):
                return float(o)
            return str(o)
        return json.dumps(obj, indent=indent, default=default_handler)
