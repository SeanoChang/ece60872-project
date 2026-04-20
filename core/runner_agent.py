"""runner_agent.py — PRIMARY: LLM-driven coding-agent runner.

This module is the primary execution path for the experiment: a real Claude
Code instance runs inside a Docker container, receives a benign-looking task
prompt ("set up this project by running npm install"), and proposes tool
calls against a trojaned codebase. The PreToolUse hook forwards each
proposed call to the orchestrator, which convenes the voting panel.

The companion ``core.replay_agent`` module is kept as a **fallback** for
scenarios where the live agent's own refusal behavior would prevent the
voting panel from observing the decision (scenario authors can pre-specify
``proposed_tool_call`` in the YAML and route through the replay path
instead). For the A0/A1/A4/A6 matrix defined in the locked design, the
primary runner is the default.

Responsibilities
----------------
- Accept a RunnerAgentConfig describing the image, workspace, prompts, URLs.
- Build and execute a docker run command via asyncio subprocess.
- Enforce a configurable timeout, returning a sentinel exit code on timeout.
"""

from __future__ import annotations

import asyncio
import os
from asyncio.subprocess import PIPE
from dataclasses import dataclass


@dataclass
class RunnerAgentConfig:
    """Configuration for a single runner agent invocation."""

    image: str
    workspace_host_dir: str
    task_prompt: str
    proxy_url: str
    orchestrator_url: str
    timeout_seconds: int = 600
    scenario_run_id: str = ""
    run_id: str = ""


async def run_runner_agent(
    config: RunnerAgentConfig,
) -> tuple[int, bytes, bytes]:
    """Spawn the coding agent Docker container and wait for it to finish.

    Parameters
    ----------
    config:
        A RunnerAgentConfig instance describing the run.

    Returns
    -------
    A 3-tuple of (return_code, stdout_bytes, stderr_bytes).
    On timeout the return code is 124 (matching GNU timeout convention)
    and stderr contains b"runner agent timed out".
    """
    abs_workspace = os.path.abspath(config.workspace_host_dir)

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{abs_workspace}:/workspace",
        "-w",
        "/workspace",
        "-e",
        f"ANTHROPIC_BASE_URL={config.proxy_url}",
        "-e",
        "ANTHROPIC_API_KEY=proxied",
        "-e",
        f"JUDGE_ORCHESTRATOR_URL={config.orchestrator_url}",
        "-e",
        f"SCENARIO_RUN_ID={config.scenario_run_id}",
        "-e",
        f"BFT_RUN_ID={config.run_id}",
        "--add-host=host.docker.internal:host-gateway",
        config.image,
        "claude",
        "-p",
        config.task_prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        # Claude Code 2.1+ requires an explicit setting source to load
        # ~/.claude/settings.json; without this the PreToolUse hook config
        # is ignored and the judge layer never runs.
        "--setting-sources",
        "user",
    ]

    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=config.timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return (124, b"", b"runner agent timed out")

    return (proc.returncode or 0, stdout, stderr)
