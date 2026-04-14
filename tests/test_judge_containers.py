"""Tests for core/judge_containers.py — TDD suite for JudgeContainerManager.

Mocks subprocess and shutil; no real Docker required.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from core.judge_containers import JudgeContainerManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> JudgeContainerManager:
    return JudgeContainerManager(
        image="bft-judge-agentic:latest",
        judge_configs_dir="judge_config",
        workspace_dir="/tmp/bft-workspace",
        proxy_url="http://host.docker.internal:8081",
    )


# ---------------------------------------------------------------------------
# container_names_from_ablation
# ---------------------------------------------------------------------------


def test_container_names_from_ablation(manager: JudgeContainerManager) -> None:
    """3 agentic judges → 3 container names."""
    ablation_config = {
        "judges": [
            {"name": "alpha", "mode": "agentic"},
            {"name": "beta", "mode": "agentic"},
            {"name": "gamma", "mode": "agentic"},
        ]
    }
    names = manager.container_names_from_ablation(ablation_config)
    assert names == ["judge-alpha", "judge-beta", "judge-gamma"]


def test_container_names_skips_stateless(manager: JudgeContainerManager) -> None:
    """Stateless judges → empty list (no containers needed)."""
    ablation_config = {
        "judges": [
            {"name": "alpha", "mode": "stateless"},
            {"name": "beta", "mode": "stateless"},
        ]
    }
    names = manager.container_names_from_ablation(ablation_config)
    assert names == []


def test_container_names_mixed(manager: JudgeContainerManager) -> None:
    """1 stateless + 2 agentic → 2 names (only agentic)."""
    ablation_config = {
        "judges": [
            {"name": "alpha", "mode": "stateless"},
            {"name": "beta", "mode": "agentic"},
            {"name": "gamma", "mode": "agentic"},
        ]
    }
    names = manager.container_names_from_ablation(ablation_config)
    assert names == ["judge-beta", "judge-gamma"]


# ---------------------------------------------------------------------------
# build_container_config
# ---------------------------------------------------------------------------


def test_build_container_config(manager: JudgeContainerManager) -> None:
    """Verify name, image, environment, volumes, command, detach."""
    config = manager.build_container_config(role="param", container_name="judge-param")

    # Basic identity
    assert config["name"] == "judge-param"
    assert config["image"] == "bft-judge-agentic:latest"
    assert config["detach"] is True
    assert config["command"] == "sleep infinity"

    # Environment
    env = config["environment"]
    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:8081"
    assert env["ANTHROPIC_API_KEY"] == "proxied"

    # Volumes — workspace mounted read-only (absolute paths)
    volumes = config["volumes"]
    workspace_key = os.path.abspath("/tmp/bft-workspace")
    assert workspace_key in volumes
    assert volumes[workspace_key]["bind"] == "/workspace"
    assert volumes[workspace_key]["mode"] == "ro"

    # Role identity dir mounted read-only
    role_host_path = os.path.abspath("judge_config/param")
    assert role_host_path in volumes
    assert volumes[role_host_path]["bind"] == "/judge/identity"
    assert volumes[role_host_path]["mode"] == "ro"

    # CLAUDE.md mounted read-only
    claude_md_path = os.path.abspath("judge_config/CLAUDE.md")
    assert claude_md_path in volumes
    assert volumes[claude_md_path]["bind"] == "/judge/CLAUDE.md"
    assert volumes[claude_md_path]["mode"] == "ro"

    # MEMORY.md mounted read-write
    memory_md_path = os.path.abspath("judge_config/MEMORY.md")
    assert memory_md_path in volumes
    assert volumes[memory_md_path]["bind"] == "/judge/MEMORY.md"
    assert volumes[memory_md_path]["mode"] == "rw"


# ---------------------------------------------------------------------------
# swap_workspace
# ---------------------------------------------------------------------------


def test_swap_workspace(manager: JudgeContainerManager) -> None:
    """Create temp dirs, perform swap, verify workspace contents changed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Build a source scenario workspace with a sentinel file
        scenario_dir = os.path.join(tmpdir, "scenario_workspace")
        os.makedirs(scenario_dir)
        sentinel_path = os.path.join(scenario_dir, "README.txt")
        with open(sentinel_path, "w") as f:
            f.write("scenario content")

        # Point manager's workspace_dir to a temp location
        workspace = os.path.join(tmpdir, "bft-workspace")
        manager.workspace_dir = workspace

        # Pre-populate workspace with stale content that should be cleared
        os.makedirs(workspace)
        stale_path = os.path.join(workspace, "stale.txt")
        with open(stale_path, "w") as f:
            f.write("old content")

        manager.swap_workspace(scenario_dir)

        # Stale content gone, sentinel present
        assert not os.path.exists(stale_path)
        assert os.path.exists(os.path.join(workspace, "README.txt"))
        with open(os.path.join(workspace, "README.txt")) as f:
            assert f.read() == "scenario content"
