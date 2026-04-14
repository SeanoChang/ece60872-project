"""JudgeContainerManager — manages persistent judge Docker containers.

Responsibilities
----------------
- Derive container names from an ablation config.
- Build a container config dict (for docker-py or equivalent).
- Swap the shared workspace directory between scenarios so all mounted
  containers see the new files without restart.
"""

from __future__ import annotations

import os
import shutil


class JudgeContainerManager:
    """Manages lifecycle and workspace for persistent judge Docker containers."""

    def __init__(
        self,
        image: str = "bft-judge-agentic:latest",
        judge_configs_dir: str = "judge_config",
        workspace_dir: str = "/tmp/bft-workspace",
        proxy_url: str = "http://host.docker.internal:8081",
    ) -> None:
        self.image = image
        self.judge_configs_dir = judge_configs_dir
        self.workspace_dir = workspace_dir
        self.proxy_url = proxy_url

    # -----------------------------------------------------------------------
    # container_names_from_ablation
    # -----------------------------------------------------------------------

    def container_names_from_ablation(self, ablation_config: dict) -> list[str]:
        """Return container names for all judges in the ablation config.

        Parameters
        ----------
        ablation_config:
            Dict with a "judges" list, each entry having a "name" key.

        Returns
        -------
        List of strings in the form ``"judge-{name}"``.
        """
        return [f"judge-{j['name']}" for j in ablation_config.get("judges", [])]

    # -----------------------------------------------------------------------
    # build_container_config
    # -----------------------------------------------------------------------

    def build_container_config(self, role: str, container_name: str) -> dict:
        """Return a container configuration dict suitable for docker-py's run().

        Mounts
        ------
        - self.workspace_dir  → /workspace          (read-only)
        - judge_configs_dir/{role}/  → /judge/identity  (read-only)
        - judge_configs_dir/CLAUDE.md → /judge/CLAUDE.md (read-only)

        Parameters
        ----------
        role:
            The judge role identifier (e.g. "param", "intent", "threat").
        container_name:
            The Docker container name (e.g. "judge-param").
        """
        role_identity_dir = os.path.abspath(os.path.join(self.judge_configs_dir, role))
        claude_md_path = os.path.abspath(os.path.join(self.judge_configs_dir, "CLAUDE.md"))

        return {
            "name": container_name,
            "image": self.image,
            "detach": True,
            "command": "sleep infinity",
            "environment": {
                "ANTHROPIC_BASE_URL": self.proxy_url,
                "ANTHROPIC_API_KEY": "proxied",
            },
            "volumes": {
                os.path.abspath(self.workspace_dir): {
                    "bind": "/workspace",
                    "mode": "ro",
                },
                role_identity_dir: {
                    "bind": "/judge/identity",
                    "mode": "ro",
                },
                claude_md_path: {
                    "bind": "/judge/CLAUDE.md",
                    "mode": "ro",
                },
            },
        }

    # -----------------------------------------------------------------------
    # swap_workspace
    # -----------------------------------------------------------------------

    def swap_workspace(self, scenario_workspace_dir: str) -> None:
        """Replace self.workspace_dir with the contents of scenario_workspace_dir.

        Because judges mount self.workspace_dir read-only, the swap is
        immediately visible inside all running containers.

        Parameters
        ----------
        scenario_workspace_dir:
            Path to the scenario's workspace directory to copy in.
        """
        if os.path.exists(self.workspace_dir):
            shutil.rmtree(self.workspace_dir)
        shutil.copytree(scenario_workspace_dir, self.workspace_dir)

