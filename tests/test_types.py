"""Tests for core/types.py — TDD suite for Task 1: Core Types."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from core.types import JudgeConfig, JudgeVote, ToolCall, VoteResult


# ---------------------------------------------------------------------------
# ToolCall tests
# ---------------------------------------------------------------------------


def test_tool_call_from_hook_stdin() -> None:
    """Create a ToolCall from a raw PreToolUse hook payload and verify fields."""
    payload = {
        "toolName": "Bash",
        "toolUseId": "toolu_abc123",
        "sessionId": "sess_xyz789",
        "cwd": "/home/user/project",
        "tool_input": {"command": "ls -la"},
    }
    tc = ToolCall.from_hook_payload(payload)

    assert tc.tool_name == "Bash"
    assert tc.tool_use_id == "toolu_abc123"
    assert tc.session_id == "sess_xyz789"
    assert tc.cwd == "/home/user/project"
    assert tc.tool_input == {"command": "ls -la"}
    assert tc.command == "ls -la"


def test_tool_call_file_path() -> None:
    """command property returns file_path when 'command' key is absent (Edit tool)."""
    payload = {
        "toolName": "Edit",
        "toolUseId": "toolu_edit42",
        "sessionId": "sess_xyz789",
        "cwd": "/home/user/project",
        "tool_input": {"file_path": "/etc/passwd", "old_string": "foo", "new_string": "bar"},
    }
    tc = ToolCall.from_hook_payload(payload)

    assert tc.tool_name == "Edit"
    assert tc.command == "/etc/passwd"


# ---------------------------------------------------------------------------
# JudgeConfig tests
# ---------------------------------------------------------------------------


def test_judge_config_creation() -> None:
    """Create a JudgeConfig and verify all fields including defaults."""
    cfg = JudgeConfig(
        name="honest-judge",
        model="claude-3-5-haiku-20241022",
        system_prompt_path="/prompts/honest/general.md",
    )

    assert cfg.name == "honest-judge"
    assert cfg.model == "claude-3-5-haiku-20241022"
    assert cfg.system_prompt_path == "/prompts/honest/general.md"
    assert cfg.temperature == 0.0
    assert cfg.role == "general"
    assert cfg.is_byzantine is False
    assert cfg.compromise_variant == ""
    assert cfg.timeout_seconds == 15


def test_judge_config_prompt_hash(tmp_path: Path) -> None:
    """prompt_hash is a 64-char hex sha256 of the system_prompt_path file, deterministic."""
    prompt_file = tmp_path / "judge_prompt.md"
    content = "You are an honest judge. Approve safe tool calls only."
    prompt_file.write_text(content, encoding="utf-8")

    cfg = JudgeConfig(
        name="test-judge",
        model="claude-3-5-haiku-20241022",
        system_prompt_path=str(prompt_file),
    )

    digest = cfg.prompt_hash
    assert len(digest) == 64
    # All hex chars
    assert all(c in "0123456789abcdef" for c in digest)
    # Deterministic — calling again yields the same value
    assert cfg.prompt_hash == digest
    # Matches independent sha256 computation
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert digest == expected


# ---------------------------------------------------------------------------
# JudgeVote tests
# ---------------------------------------------------------------------------


def test_judge_vote_defaults() -> None:
    """Create a JudgeVote with minimal required fields and verify all defaults."""
    vote = JudgeVote(
        judge_name="honest-judge",
        model_id="claude-3-5-haiku-20241022",
        decision="approve",
        confidence=0.95,
        reason="Command is benign.",
    )

    assert vote.judge_name == "honest-judge"
    assert vote.model_id == "claude-3-5-haiku-20241022"
    assert vote.decision == "approve"
    assert vote.confidence == 0.95
    assert vote.reason == "Command is benign."
    # Defaults
    assert vote.investigation_steps == []
    assert vote.tools_used == []
    assert vote.latency_ms == 0.0
    assert vote.input_tokens == 0
    assert vote.output_tokens == 0
    assert vote.cost_usd == 0.0
    assert vote.is_byzantine is False


def test_judge_vote_is_mutable() -> None:
    """JudgeVote is NOT frozen — fields can be mutated after creation."""
    vote = JudgeVote(
        judge_name="honest-judge",
        model_id="claude-3-5-haiku-20241022",
        decision="approve",
        confidence=0.9,
        reason="Safe.",
    )
    vote.latency_ms = 123.4
    vote.input_tokens = 512
    assert vote.latency_ms == 123.4
    assert vote.input_tokens == 512


# ---------------------------------------------------------------------------
# VoteResult tests
# ---------------------------------------------------------------------------


def test_vote_result() -> None:
    """Create a VoteResult with a list of votes and verify all fields."""
    vote1 = JudgeVote(
        judge_name="judge-a",
        model_id="claude-3-5-haiku-20241022",
        decision="approve",
        confidence=0.9,
        reason="Safe.",
    )
    vote2 = JudgeVote(
        judge_name="judge-b",
        model_id="claude-3-5-haiku-20241022",
        decision="approve",
        confidence=0.85,
        reason="Also safe.",
    )
    result = VoteResult(
        decision="approve",
        votes=[vote1, vote2],
        quorum_rule="majority",
        total_latency_ms=450.0,
        total_cost_usd=0.0012,
    )

    assert result.decision == "approve"
    assert len(result.votes) == 2
    assert result.votes[0].judge_name == "judge-a"
    assert result.quorum_rule == "majority"
    assert result.total_latency_ms == 450.0
    assert result.total_cost_usd == 0.0012


def test_vote_result_is_mutable() -> None:
    """VoteResult is NOT frozen — fields can be mutated after creation."""
    result = VoteResult(
        decision="approve",
        votes=[],
        quorum_rule="unanimous",
        total_latency_ms=0.0,
        total_cost_usd=0.0,
    )
    result.decision = "reject"
    assert result.decision == "reject"
