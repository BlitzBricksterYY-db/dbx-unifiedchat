"""
Standalone /api/rechart endpoint that exposes ChartGenerator for the
"Ask chart" button in the chat UI.

Mounted onto the MLflow AgentServer's FastAPI app in start_server.py.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class RechartRequest(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    prompt: str = Field(..., min_length=1)
    title: str = ""
    description: str = ""
    row_grain_hint: str = ""
    mode: str = "replace"


class RechartResponse(BaseModel):
    success: bool
    chart: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    mode: str = "replace"


def _get_chart_generator():
    """Reuse the same lazy singleton from the summarize module."""
    try:
        from agent_server.multi_agent.agents.summarize import (
            _get_cached_chart_generator,
        )

        return _get_cached_chart_generator()
    except Exception as exc:
        logger.warning("Failed to get ChartGenerator: %s", exc)
        return None


@router.post("/rechart", response_model=RechartResponse)
async def rechart(request: RechartRequest) -> RechartResponse:
    chart_gen = _get_chart_generator()
    if chart_gen is None:
        return RechartResponse(
            success=False,
            error="ChartGenerator is not available. Check LLM endpoint configuration.",
            mode=request.mode,
        )

    try:
        payload = chart_gen.generate_chart(
            columns=request.columns,
            data=request.rows,
            original_query=request.prompt,
            result_context={
                "label": request.title or None,
                "sql_explanation": request.description or None,
                "row_grain_hint": request.row_grain_hint or None,
            },
        )

        if payload is None:
            return RechartResponse(
                success=False,
                error="The data is not plottable for the requested chart configuration.",
                mode=request.mode,
            )

        return RechartResponse(
            success=True,
            chart=payload,
            mode=request.mode,
        )
    except Exception as exc:
        logger.exception("Rechart failed")
        return RechartResponse(
            success=False,
            error=str(exc),
            mode=request.mode,
        )
