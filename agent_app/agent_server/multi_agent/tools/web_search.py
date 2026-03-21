"""
Web search utility for code enrichment.

Provides DuckDuckGo-based web search, LLM-powered code column detection,
and end-to-end enrichment that adds human-readable descriptions to coded
identifiers (NDC, ICD-10, CPT, tickers, FIPS, etc.) in query result tables.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from duckduckgo_search import DDGS


_SEARCH_TIMEOUT = 5
_ENRICHMENT_TIMEOUT = 15
_MAX_CODES_TO_LOOKUP = 20
_MAX_SEARCH_WORKERS = 5


def web_search(query: str, max_results: int = 3) -> str:
    """Run a DuckDuckGo text search and return formatted snippets."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        parts = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            parts.append(f"{title}\n{body}\n{href}")
        return "\n\n".join(parts)
    except Exception as e:
        return f"Search failed: {e}"


def detect_code_columns(
    columns: list[str],
    sample_data: list[dict],
    llm: Any,
) -> list[dict]:
    """Use a cheap LLM to identify which columns contain coded identifiers.

    Returns a list like [{"column": "ndc", "code_type": "NDC"}].
    """
    sample_rows = sample_data[:3]
    sample_str = json.dumps(sample_rows, indent=2, default=str)
    if len(sample_str) > 2000:
        sample_str = sample_str[:2000] + "\n..."

    prompt = (
        "You are a data analyst. Given these column names and sample rows from a "
        "SQL query result, identify which columns contain **coded identifiers** that "
        "would benefit from a human-readable description lookup.\n\n"
        "Examples of coded identifiers: NDC (drug codes), ICD-10/ICD-9 (diagnosis), "
        "CPT/HCPCS (procedures), NAICS/SIC (industry), FIPS (geography), "
        "ticker symbols (stocks), currency codes, zip codes with names, etc.\n\n"
        "Do NOT flag columns that are already human-readable (names, descriptions, "
        "dates, counts, amounts) or generic auto-increment IDs.\n\n"
        f"Columns: {columns}\n\n"
        f"Sample rows:\n{sample_str}\n\n"
        "Return ONLY a JSON array. Each element: "
        '{{"column": "<column_name>", "code_type": "<type>"}}. '
        "If no columns are coded identifiers, return [].\n"
        "Output ONLY the JSON array, nothing else."
    )

    try:
        response = llm.invoke(prompt)
        text = response.content.strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return []
    except Exception as e:
        print(f"⚠ detect_code_columns failed: {e}")
        return []


def _sanitize_for_markdown_table(text: str) -> str:
    """Escape characters that break markdown table cells."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\n", " ").replace("\r", " ")
    text = text.replace("|", "\\|")
    return text.strip()


def _lookup_code(code_type: str, value: str) -> tuple[str, str]:
    """Search for a single code value and return (value, description)."""
    query = f"{code_type} {value} description"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=2))
        if results:
            snippet = results[0].get("body", "")
            if len(snippet) > 150:
                snippet = snippet[:147] + "..."
            return (value, _sanitize_for_markdown_table(snippet))
    except Exception:
        pass
    return (value, "—")


def enrich_codes(
    columns: list[str],
    data: list[dict],
    llm: Any,
    writer: Optional[Any] = None,
) -> Optional[str]:
    """Detect code columns, web-search descriptions, and build an enriched markdown table.

    Returns the enriched markdown table string, or None if nothing to enrich.
    """
    if not columns or not data:
        return None

    code_cols = detect_code_columns(columns, data, llm)
    if not code_cols:
        print("ℹ No coded columns detected — skipping enrichment")
        return None

    col_names = [c["column"] for c in code_cols if c["column"] in columns]
    if not col_names:
        return None

    code_type_map = {c["column"]: c["code_type"] for c in code_cols}
    print(f"🔍 Detected coded columns: {col_names}")
    if writer:
        writer({
            "type": "code_enrichment_progress",
            "content": f"Detected coded columns: {', '.join(col_names)}",
        })

    lookups: dict[str, dict[str, str]] = {}
    for col in col_names:
        unique_vals = list(dict.fromkeys(
            str(row.get(col, "")) for row in data if row.get(col) is not None
        ))[:_MAX_CODES_TO_LOOKUP]

        code_type = code_type_map.get(col, "code")
        if writer:
            writer({
                "type": "code_enrichment_progress",
                "content": f"Looking up {len(unique_vals)} {code_type} descriptions...",
            })

        col_lookups: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=_MAX_SEARCH_WORKERS) as pool:
            futures = {
                pool.submit(_lookup_code, code_type, val): val
                for val in unique_vals
            }
            for future in as_completed(futures, timeout=_ENRICHMENT_TIMEOUT):
                try:
                    val, desc = future.result(timeout=_SEARCH_TIMEOUT)
                    col_lookups[val] = desc
                except Exception:
                    col_lookups[futures[future]] = "—"

        lookups[col] = col_lookups

    enriched_columns = []
    for col in columns:
        enriched_columns.append(col)
        if col in lookups:
            enriched_columns.append(f"{col}_description")

    header = "| " + " | ".join(enriched_columns) + " |"
    separator = "| " + " | ".join("---" for _ in enriched_columns) + " |"

    rows_md = []
    for row in data:
        cells = []
        for col in columns:
            val = _sanitize_for_markdown_table(str(row.get(col, "")))
            cells.append(val)
            if col in lookups:
                desc = lookups[col].get(val.replace("\\|", "|"), "—")
                cells.append(desc)
        rows_md.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header, separator] + rows_md)
    print(f"✓ Enriched table built ({len(enriched_columns)} cols, {len(rows_md)} rows)")
    return table
