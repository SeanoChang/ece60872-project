"""Tests for core/agentic_judge.py — TDD suite for the agentic judge module.

Only parse_verdict_json is tested here; run_agentic_judge is covered by
integration tests (requires Docker).
"""

from __future__ import annotations

import pytest

from core.judges.agentic import parse_verdict_json
from core.types import JudgeVote, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(command: str = "npm install") -> ToolCall:
    return ToolCall(
        tool_name="Bash",
        tool_input={"command": command},
        tool_use_id="toolu_test001",
        session_id="sess_test",
        cwd="/tmp/project",
    )


# ---------------------------------------------------------------------------
# parse_verdict_json
# ---------------------------------------------------------------------------


def test_parse_verdict_json_valid() -> None:
    """Full JSON with all fields → correct JudgeVote."""
    raw = """{
        "decision": "approve",
        "confidence": 0.91,
        "reason": "The command installs only declared dependencies.",
        "investigation_steps": ["read package.json", "checked registry"]
    }"""
    vote = parse_verdict_json(raw, judge_name="judge-alpha", model_id="claude-3-5-haiku-20241022")

    assert isinstance(vote, JudgeVote)
    assert vote.decision == "approve"
    assert vote.confidence == pytest.approx(0.91)
    assert vote.reason == "The command installs only declared dependencies."
    assert vote.investigation_steps == ["read package.json", "checked registry"]
    assert vote.judge_name == "judge-alpha"
    assert vote.model_id == "claude-3-5-haiku-20241022"


def test_parse_verdict_json_malformed() -> None:
    """Non-JSON string → reject with confidence=0.5 and error reason."""
    vote = parse_verdict_json("this is not json", judge_name="judge-beta")

    assert vote.decision == "reject"
    assert vote.confidence == pytest.approx(0.5)
    assert "Failed to parse verdict.json" in vote.reason
    assert vote.judge_name == "judge-beta"


def test_parse_verdict_json_missing_fields() -> None:
    """JSON with only decision → all other fields use defaults."""
    raw = '{"decision": "reject"}'
    vote = parse_verdict_json(raw, judge_name="judge-gamma")

    assert vote.decision == "reject"
    assert vote.confidence == pytest.approx(0.5)
    assert vote.reason == ""
    assert vote.investigation_steps == []
    assert vote.judge_name == "judge-gamma"


def test_parse_verdict_json_invalid_decision() -> None:
    """decision='maybe' is not a valid literal → defaults to 'reject'."""
    raw = '{"decision": "maybe", "confidence": 0.75, "reason": "I am unsure."}'
    vote = parse_verdict_json(raw, judge_name="judge-delta")

    assert vote.decision == "reject"
    assert vote.confidence == pytest.approx(0.75)
    assert vote.reason == "I am unsure."
    assert vote.judge_name == "judge-delta"


