"""Tests for core/judge_agent.py — TDD suite for Task 7: Judge Agent (StatelessJudge)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.types import JudgeConfig, JudgeVote, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    tmp_path: Path,
    *,
    is_byzantine: bool = False,
    model: str = "claude-sonnet-4-6-20260101",
) -> JudgeConfig:
    """Build a JudgeConfig pointing to a real temp prompt file."""
    prompt_file = tmp_path / "judge_prompt.md"
    prompt_file.write_text("You are an honest judge. Evaluate tool calls carefully.")
    return JudgeConfig(
        name="test-judge",
        model=model,
        system_prompt_path=str(prompt_file),
        temperature=0.0,
        is_byzantine=is_byzantine,
        mode="stateless",
    )


def _make_tool_call() -> ToolCall:
    return ToolCall(
        tool_name="Bash",
        tool_input={"command": "ls -la /tmp"},
        tool_use_id="toolu_test123",
        session_id="sess_abc",
    )


def _make_mock_client(response_text: str, model: str = "claude-sonnet-4-6-20260101") -> MagicMock:
    """Build a mock AsyncAnthropic client that returns *response_text* from messages.create."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_message.model = model
    mock_message.usage = MagicMock(input_tokens=100, output_tokens=50)

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stateless_judge_approve(tmp_path: Path) -> None:
    """Mock client returns approve JSON → JudgeVote with decision='approve'."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path)
    client = _make_mock_client('{"decision": "approve", "confidence": 0.9, "reason": "safe"}')
    judge = StatelessJudge(config=config, client=client)

    vote = await judge.evaluate(_make_tool_call())

    assert isinstance(vote, JudgeVote)
    assert vote.decision == "approve"


@pytest.mark.asyncio
async def test_stateless_judge_reject(tmp_path: Path) -> None:
    """Mock client returns reject JSON → JudgeVote with decision='reject'."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path)
    client = _make_mock_client(
        '{"decision": "reject", "confidence": 0.95, "reason": "dangerous command"}'
    )
    judge = StatelessJudge(config=config, client=client)

    vote = await judge.evaluate(_make_tool_call())

    assert isinstance(vote, JudgeVote)
    assert vote.decision == "reject"


@pytest.mark.asyncio
async def test_stateless_judge_populates_fields(tmp_path: Path) -> None:
    """Verify judge_name, model_id, confidence, reason, latency, tokens, cost are all populated."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path)
    client = _make_mock_client('{"decision": "approve", "confidence": 0.88, "reason": "all good"}')
    judge = StatelessJudge(config=config, client=client)

    vote = await judge.evaluate(_make_tool_call())

    assert vote.judge_name == "test-judge"
    assert vote.model_id == "claude-sonnet-4-6-20260101"
    assert vote.confidence == 0.88
    assert vote.reason == "all good"
    assert vote.latency_ms > 0
    assert vote.input_tokens == 100
    assert vote.output_tokens == 50
    assert vote.cost_usd > 0
    assert vote.is_byzantine is False


@pytest.mark.asyncio
async def test_stateless_judge_malformed_response(tmp_path: Path) -> None:
    """Mock client returns non-JSON text → JudgeVote with decision='reject', confidence=0.5."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path)
    client = _make_mock_client("I cannot determine if this is safe or not.")
    judge = StatelessJudge(config=config, client=client)

    vote = await judge.evaluate(_make_tool_call())

    assert vote.decision == "reject"
    assert vote.confidence == 0.5
    assert "failed to parse" in vote.reason.lower()


@pytest.mark.asyncio
async def test_stateless_judge_json_in_markdown(tmp_path: Path) -> None:
    """Mock client returns ```json\\n{...}\\n``` → parses correctly (models often wrap JSON)."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path)
    markdown_response = (
        "```json\n"
        '{"decision": "approve", "confidence": 0.75, "reason": "looks fine"}\n'
        "```"
    )
    client = _make_mock_client(markdown_response)
    judge = StatelessJudge(config=config, client=client)

    vote = await judge.evaluate(_make_tool_call())

    assert vote.decision == "approve"
    assert vote.confidence == 0.75
    assert vote.reason == "looks fine"


@pytest.mark.asyncio
async def test_stateless_judge_passes_byzantine_flag(tmp_path: Path) -> None:
    """Config with is_byzantine=True → vote.is_byzantine=True."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path, is_byzantine=True)
    client = _make_mock_client('{"decision": "approve", "confidence": 0.9, "reason": "safe"}')
    judge = StatelessJudge(config=config, client=client)

    vote = await judge.evaluate(_make_tool_call())

    assert vote.is_byzantine is True


@pytest.mark.asyncio
async def test_stateless_judge_with_context(tmp_path: Path) -> None:
    """Context dict is included in the user message without errors."""
    from core.judge_agent import StatelessJudge

    config = _make_config(tmp_path)
    client = _make_mock_client('{"decision": "approve", "confidence": 0.9, "reason": "safe"}')
    judge = StatelessJudge(config=config, client=client)

    context = {"past_calls": ["ls", "pwd"], "session_id": "sess_abc"}
    vote = await judge.evaluate(_make_tool_call(), context=context)

    assert vote.decision == "approve"
    # Verify that the client was called with a message including context info
    call_args = client.messages.create.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[0] if call_args.args else None
    if messages is None:
        messages = call_args.kwargs["messages"]
    user_content = messages[0]["content"]
    assert "past_calls" in user_content or "session_id" in user_content
