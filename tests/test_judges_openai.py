"""Tests for core/judges/openai.py — host-side ReAct harness.

Mocks both the HTTP client (chat completions endpoint) and the docker exec
subprocess so no real model server or container is required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from core.judges.openai import (
    OpenAIJudgeConfig,
    _extract_verdict_json,
    _looks_like_refusal,
    run_openai_judge,
)
from core.types import ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call(command: str = "npm install") -> ToolCall:
    return ToolCall(
        tool_name="Bash",
        tool_input={"command": command},
        tool_use_id="toolu_test001",
        session_id="sess_test",
        cwd="/workspace",
    )


def _completion(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
) -> dict:
    """Build a fake OpenAI chat-completion response."""
    msg: dict = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient that returns scripted responses in order."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise RuntimeError("FakeClient: no scripted response left")
        return _FakeResponse(self._responses.pop(0))

    async def aclose(self) -> None:
        return


def _fake_subprocess(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Return a callable that mimics asyncio.create_subprocess_exec."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode

    async def _factory(*args, **kwargs):
        return proc

    return _factory


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------


def test_looks_like_refusal_positive_cases() -> None:
    assert _looks_like_refusal("I cannot help with that request.")
    assert _looks_like_refusal("Sorry, I can't do this.")
    assert _looks_like_refusal("I'm not able to investigate.")
    assert _looks_like_refusal("As an AI assistant, I won't proceed.")


def test_looks_like_refusal_negative_cases() -> None:
    assert not _looks_like_refusal("")
    assert not _looks_like_refusal('{"decision": "reject", "reason": "bad."}')
    # Verdict prose that mentions "cannot" mid-sentence must NOT trigger.
    assert not _looks_like_refusal(
        "After investigation, the package cannot be trusted because it "
        "exfiltrates credentials. Decision: reject."
    )


def test_extract_verdict_json_finds_bare_json() -> None:
    text = (
        'Here is my verdict: '
        '{"decision": "approve", "confidence": 0.9, "reason": "ok"}'
    )
    out = _extract_verdict_json(text)
    assert out is not None
    assert json.loads(out)["decision"] == "approve"


def test_extract_verdict_json_handles_trailing_text() -> None:
    text = '{"decision": "reject", "confidence": 0.7, "reason": "bad"}\nDone.'
    out = _extract_verdict_json(text)
    assert out is not None and json.loads(out)["decision"] == "reject"


def test_extract_verdict_json_no_decision_returns_none() -> None:
    text = "Just a regular {key: value} response with no decision field."
    assert _extract_verdict_json(text) is None


def test_extract_verdict_json_empty_returns_none() -> None:
    assert _extract_verdict_json("") is None


# ---------------------------------------------------------------------------
# run_openai_judge — full harness with mocked HTTP + docker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_turn_verdict() -> None:
    """Model emits verdict immediately, no tool calls."""
    client = _FakeClient([
        _completion(
            '{"decision": "approve", "confidence": 0.85, '
            '"reason": "Safe install.", "investigation_steps": ["read README"]}'
        ),
    ])
    vote = await run_openai_judge(
        container_name="judge-test",
        tool_call=_make_tool_call(),
        judge_name="judge-glm",
        model_id="glm-4.5-air",
        http_client=client,  # type: ignore[arg-type]
    )
    assert vote.decision == "approve"
    assert vote.confidence == pytest.approx(0.85)
    assert vote.reason == "Safe install."
    assert vote.phase_timings_ms["turns_used"] == 1.0
    assert vote.input_tokens == 100
    assert vote.output_tokens == 50
    # The HTTP call carried OpenAI tool-use schema and the right model id.
    sent = client.calls[0]["json"]
    assert sent["model"] == "glm-4.5-air"
    assert any(t["function"]["name"] == "bash" for t in sent["tools"])


@pytest.mark.asyncio
async def test_multi_turn_with_tool_call() -> None:
    """Model calls one tool, then emits verdict on the second turn."""
    tool_resp = _completion(
        content=None,
        tool_calls=[{
            "id": "call_1",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "/workspace/package.json"}),
            },
        }],
    )
    final_resp = _completion(
        '{"decision": "reject", "confidence": 0.95, '
        '"reason": "postinstall trojan.", "investigation_steps": []}'
    )
    client = _FakeClient([tool_resp, final_resp])

    with patch(
        "core.judges.openai.asyncio.create_subprocess_exec",
        new=_fake_subprocess(stdout=b'{"name":"hello-api"}'),
    ):
        vote = await run_openai_judge(
            container_name="judge-test",
            tool_call=_make_tool_call(),
            judge_name="judge-glm",
            model_id="glm-4.5-air",
            http_client=client,  # type: ignore[arg-type]
        )

    assert vote.decision == "reject"
    assert vote.reason == "postinstall trojan."
    assert "read_file" in vote.tools_used
    assert vote.phase_timings_ms["turns_used"] == 2.0
    # tool-call appears in investigation_steps prepended by the harness
    assert any("read_file" in step for step in vote.investigation_steps)


@pytest.mark.asyncio
async def test_refusal_classified() -> None:
    """Model declines instead of investigating → judge_refused."""
    client = _FakeClient([
        _completion("I cannot help with security analysis tasks."),
    ])
    vote = await run_openai_judge(
        container_name="judge-test",
        tool_call=_make_tool_call(),
        judge_name="judge-glm",
        model_id="glm-4.5-air",
        http_client=client,  # type: ignore[arg-type]
    )
    assert vote.decision == "reject"
    assert vote.reason.startswith("judge_refused")


@pytest.mark.asyncio
async def test_turn_budget_exhaustion() -> None:
    """Model loops on tools forever; harness aborts at turn budget."""
    tool_resp = _completion(
        content=None,
        tool_calls=[{
            "id": "call_x",
            "function": {
                "name": "bash",
                "arguments": json.dumps({"command": "ls"}),
            },
        }],
    )
    client = _FakeClient([tool_resp] * 10)  # plenty of responses

    with patch(
        "core.judges.openai.asyncio.create_subprocess_exec",
        new=_fake_subprocess(stdout=b"file1\nfile2\n"),
    ):
        vote = await run_openai_judge(
            container_name="judge-test",
            tool_call=_make_tool_call(),
            judge_name="judge-glm",
            model_id="glm-4.5-air",
            config=OpenAIJudgeConfig(turn_budget=3),
            http_client=client,  # type: ignore[arg-type]
        )

    assert vote.decision == "reject"
    assert vote.reason.startswith("judge_timed_out")
    assert vote.phase_timings_ms["turns_used"] == 3.0
    # Should have dispatched 3 bash calls (one per turn)
    assert vote.tools_used == ["bash", "bash", "bash"]


@pytest.mark.asyncio
async def test_malformed_final_text() -> None:
    """Model emits prose without a parseable verdict → judge_failed_malformed."""
    client = _FakeClient([
        _completion("After looking at the code, I believe this is fine."),
    ])
    vote = await run_openai_judge(
        container_name="judge-test",
        tool_call=_make_tool_call(),
        judge_name="judge-glm",
        model_id="glm-4.5-air",
        http_client=client,  # type: ignore[arg-type]
    )
    assert vote.decision == "reject"
    assert vote.reason.startswith("judge_failed_malformed")


@pytest.mark.asyncio
async def test_http_error_classified_as_timeout() -> None:
    """Network error during chat completion → judge_timed_out fail-closed."""
    import httpx

    class _BrokenClient:
        async def post(self, url, json, headers):
            raise httpx.ConnectError("server unreachable")

        async def aclose(self):
            return

    vote = await run_openai_judge(
        container_name="judge-test",
        tool_call=_make_tool_call(),
        judge_name="judge-glm",
        model_id="glm-4.5-air",
        http_client=_BrokenClient(),  # type: ignore[arg-type]
    )
    assert vote.decision == "reject"
    assert vote.reason.startswith("judge_timed_out")
    assert "ConnectError" in vote.reason
