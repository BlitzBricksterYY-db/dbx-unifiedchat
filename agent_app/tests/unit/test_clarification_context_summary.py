from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_server.multi_agent.agents.clarification import (
    _format_clarification_context_summary,
)


def test_format_clarification_context_summary_includes_options():
    summary = _format_clarification_context_summary(
        context_summary=(
            "The user wants an analysis of pediatric members (defined as under 18 by "
            "start_date) to identify whether they have fall/fracture diagnoses."
        ),
        clarification_reason=(
            "The available spaces include diagnosis and procedure tables, but the request "
            "still needs the exact diagnosis/procedure codes."
        ),
        clarification_options=[
            "Provide the diagnosis code set or rule for fall/fracture.",
            "Confirm whether 'reason' should be inferred from diagnosis codes only.",
            "Specify the analysis window and sequencing rule for 'after that'.",
        ],
        user_response=(
            "1. you decide diag and procedure code; 2. 'reason' should be inferred from "
            "diagnosis codes only; 3. any later claim within 60 days"
        ),
    )

    assert "Clarification asked:" in summary
    assert "Clarification Options:" in summary
    assert "1), Provide the diagnosis code set or rule for fall/fracture" in summary
    assert "2), Confirm whether 'reason' should be inferred from diagnosis codes only" in summary
    assert "3), Specify the analysis window and sequencing rule for 'after that'" in summary
    assert "User answered:" in summary


def test_format_clarification_context_summary_handles_empty_prior_context():
    summary = _format_clarification_context_summary(
        context_summary="",
        clarification_reason="Need the treatment timeframe.",
        clarification_options=[],
        user_response="Any later claim within 60 days",
    )

    assert summary == (
        "Clarification asked: Need the treatment timeframe. — "
        "User answered: Any later claim within 60 days"
    )
