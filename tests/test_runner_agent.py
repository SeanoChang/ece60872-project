"""Tests for core/runner_agent.py — written first (TDD).

Two scenarios:
1. Verifies that run_runner_agent constructs the expected docker run command.
2. Verifies that a non-zero exit code is propagated correctly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.runner_agent import RunnerAgentConfig, run_runner_agent


# ---------------------------------------------------------------------------
# 1. test_run_runner_agent_builds_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_runner_agent_builds_command(tmp_path: Path) -> None:
    """run_runner_agent should invoke docker run with the expected arguments."""
    config = RunnerAgentConfig(
        image="bft-agent:latest",
        workspace_host_dir=str(tmp_path / "ws"),
        task_prompt="Set up the project",
        proxy_url="http://host.docker.internal:8081",
        orchestrator_url="http://host.docker.internal:8080",
    )

    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"ok", b""))
    proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        rc, stdout, stderr = await run_runner_agent(config)

    assert rc == 0

    call_args = mock_exec.call_args.args
    assert "docker" in call_args
    assert "run" in call_args
    assert "--rm" in call_args
    assert "bft-agent:latest" in call_args


# ---------------------------------------------------------------------------
# 2. test_run_runner_agent_reports_nonzero_exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_runner_agent_reports_nonzero_exit(tmp_path: Path) -> None:
    """run_runner_agent should propagate a non-zero return code and stderr."""
    config = RunnerAgentConfig(
        image="bft-agent:latest",
        workspace_host_dir=str(tmp_path / "ws"),
        task_prompt="Set up the project",
        proxy_url="http://host.docker.internal:8081",
        orchestrator_url="http://host.docker.internal:8080",
    )

    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b"error"))
    proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        rc, stdout, stderr = await run_runner_agent(config)

    assert rc == 1
    assert b"error" in stderr


# ---------------------------------------------------------------------------
# 3. test_run_runner_agent_includes_correlation_env_vars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_runner_agent_includes_correlation_env_vars(tmp_path: Path) -> None:
    """run_runner_agent injects SCENARIO_RUN_ID and BFT_RUN_ID via docker -e flags."""
    config = RunnerAgentConfig(
        image="bft-agent:latest",
        workspace_host_dir=str(tmp_path / "ws"),
        task_prompt="Set up the project",
        proxy_url="http://host.docker.internal:8081",
        orchestrator_url="http://host.docker.internal:8080",
        scenario_run_id="sr-xyz",
        run_id="run-abc",
    )

    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_runner_agent(config)

    argv = list(mock_exec.call_args.args)

    def _assert_env_pair(value: str) -> None:
        for i, token in enumerate(argv):
            if token == "-e" and i + 1 < len(argv) and argv[i + 1] == value:
                return
        raise AssertionError(f"Expected '-e {value}' in argv, got: {argv}")

    _assert_env_pair("SCENARIO_RUN_ID=sr-xyz")
    _assert_env_pair("BFT_RUN_ID=run-abc")
