"""replay_agent.py — deterministic shim that replaces the LLM coding agent.

Why this module exists
----------------------
Claude Sonnet 4.6 self-defends on naive prompt-injection scenarios before it
ever emits a tool call. When the voting panel (the component under test in
our paper) never sees a decision to judge, its detection behavior is
unobservable. To isolate the voting panel from upstream coding-agent variance,
we replace the LLM-driven agent with a deterministic replay shim: each
scenario YAML specifies the exact tool call the replay agent should emit,
and the shim POSTs it to the orchestrator's /judge endpoint on the same path
a Claude Code PreToolUse hook would.

This is a standard fault-injection methodology (Hsueh, Tsai & Iyer, "Fault
Injection Techniques and Tools", IEEE Computer 1997): inject the signal at
the component under test, not upstream of a stochastic filter.

Usage
-----
    cfg = ReplayAgentConfig(
        orchestrator_url="http://localhost:8080",
        proposed_tool_call={"tool": "Bash", "input": {"command": "npm install"}},
        scenario_run_id="postinstall-01-rep1-abc123",
        run_id="exp-42",
        workspace_host_dir="/tmp/workspace-xyz",
    )
    result = await run_replay_agent(cfg)
    # result.decision is "approve" or "reject"

The replay agent does NOT execute the approved tool call. Execution (and
honeypot ground-truth checking) is the experiment runner's responsibility,
preserved from the previous runner_agent pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


_FAIL_CLOSED_DECISION = "reject"


@dataclass
class ReplayAgentConfig:
    """Configuration for one replay-agent invocation."""

    orchestrator_url: str
    proposed_tool_call: dict[str, Any]
    scenario_run_id: str
    run_id: str
    workspace_host_dir: str = ""
    timeout_seconds: int = 60


@dataclass
class ReplayAgentResult:
    """Outcome of one replay-agent invocation."""

    decision: str
    reason: str
    error: str = ""
    raw_response: dict[str, Any] | None = None


def _build_hook_payload(config: ReplayAgentConfig) -> dict[str, Any]:
    """Synthesize the PreToolUse hook payload a Claude Code agent would have sent.

    The orchestrator's /judge endpoint and downstream judge_hook use the
    snake_case schema `tool_name`, `tool_input`, `tool_use_id`, `session_id`,
    `cwd`. We emit exactly that, so the orchestrator cannot distinguish a
    replay-agent call from a real Claude Code hook call.
    """
    tool_name = config.proposed_tool_call["tool"]
    tool_input = config.proposed_tool_call["input"]
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": f"replay-{config.scenario_run_id}",
        "session_id": f"replay-session-{config.run_id}",
        "cwd": config.workspace_host_dir,
    }


async def run_replay_agent(config: ReplayAgentConfig) -> ReplayAgentResult:
    """POST the scenario's proposed tool call to the orchestrator and return its decision.

    Fails closed: any network/HTTP error returns a `reject` decision with an
    `error` field populated. The experiment runner logs this as `infra_failed`
    rather than treating it as a real judge rejection.
    """
    payload = _build_hook_payload(config)

    headers: dict[str, str] = {
        "x-scenario-run-id": config.scenario_run_id,
        "x-run-id": config.run_id,
    }

    judge_url = f"{config.orchestrator_url.rstrip('/')}/judge"

    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            response = await client.post(judge_url, json=payload, headers=headers)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception as exc:
        return ReplayAgentResult(
            decision=_FAIL_CLOSED_DECISION,
            reason="",
            error=f"{type(exc).__name__}: {exc}",
            raw_response=None,
        )

    return ReplayAgentResult(
        decision=data.get("decision", _FAIL_CLOSED_DECISION),
        reason=data.get("reason", ""),
        error="",
        raw_response=data,
    )
