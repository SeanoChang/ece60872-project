"""PreToolUse hook script for Claude Code — thin client that forwards to the orchestrator.

Claude Code calls this script before every matched tool execution:
  - Reads the tool call JSON from stdin
  - POSTs it to the orchestrator's /judge endpoint
  - Exits with code 0 (approve) or 2 (reject)

Exit codes:
    0  — approve: Claude Code proceeds with the tool call
    2  — reject:  Claude Code cancels the tool call; stderr message is sent back as feedback

Environment:
    JUDGE_ORCHESTRATOR_URL  URL of the orchestrator (default: http://localhost:8080)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_ORCHESTRATOR_URL = "http://localhost:8080"

# ---------------------------------------------------------------------------
# Core async function (testable)
# ---------------------------------------------------------------------------


async def evaluate_tool_call(
    payload: dict[str, Any],
    orchestrator_url: str,
) -> tuple[int, dict]:
    """POST *payload* to the orchestrator and return (exit_code, output_dict).

    Parameters
    ----------
    payload:
        The parsed JSON dict received on stdin from Claude Code.
    orchestrator_url:
        Base URL of the orchestrator, e.g. "http://localhost:8080".

    Returns
    -------
    tuple[int, dict]
        - exit_code: 0 for approve, 2 for reject or error
        - output_dict: empty on approve; structured hookSpecificOutput on reject
    """
    judge_url = f"{orchestrator_url.rstrip('/')}/judge"

    headers: dict[str, str] = {}
    scenario_run_id = os.environ.get("SCENARIO_RUN_ID")
    run_id = os.environ.get("BFT_RUN_ID")
    if scenario_run_id:
        headers["x-scenario-run-id"] = scenario_run_id
    if run_id:
        headers["x-run-id"] = run_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(judge_url, json=payload, headers=headers)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception as exc:
        # Fail-closed: any error (network, 5xx, etc.) → reject with reason
        return (2, {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Judge orchestrator unavailable: {exc}",
            }
        })

    decision = data.get("decision", "reject")
    reason: str = data.get("reason", "")

    if decision == "approve":
        return (0, {})

    # Reject path — build the structured hook output Claude Code expects
    structured_output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    return (2, structured_output)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Read JSON from stdin, evaluate, write outputs, and exit with proper code.

    Claude Code's hook protocol treats exit code 2 as "deny" and *any other
    non-zero* as "no opinion" (the tool call is allowed). That means an
    uncaught exception (ImportError, network glitch, malformed stdin, etc.)
    silently fails open. Wrap the whole body so any failure becomes a
    fail-closed rejection.
    """
    try:
        raw = sys.stdin.read()
        payload: dict[str, Any] = json.loads(raw)

        orchestrator_url = os.environ.get("JUDGE_ORCHESTRATOR_URL", _DEFAULT_ORCHESTRATOR_URL)

        exit_code, output = asyncio.run(evaluate_tool_call(payload, orchestrator_url))

        if output:
            sys.stdout.write(json.dumps(output))
            sys.stdout.flush()

        if exit_code == 2:
            reason = ""
            hook_out = output.get("hookSpecificOutput", {})
            if hook_out:
                reason = hook_out.get("permissionDecisionReason", "")
            if reason:
                sys.stderr.write(reason)
                sys.stderr.flush()

        sys.exit(exit_code)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001  intentional: fail-closed catch-all
        sys.stderr.write(f"judge_hook fail-closed: {type(exc).__name__}: {exc}")
        sys.stderr.flush()
        sys.exit(2)


if __name__ == "__main__":
    main()
