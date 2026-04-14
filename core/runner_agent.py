"""runner_agent.py — spawns the coding agent Docker container for one scenario.

Responsibilities
----------------
- Accept a RunnerAgentConfig describing the image, workspace, prompts, and URLs.
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
        "ANTHROPIC_API_KEY=",
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
