"""JudgeContainerManager — manages persistent judge Docker containers.

Responsibilities
----------------
- Derive container names from an ablation config (agentic judges only).
- Build a container config dict (for docker-py or equivalent).
- Swap the shared workspace directory between scenarios so all mounted
  containers see the new files without restart.
- Append entries to each judge's in-container MEMORY.md file.
- Truncate MEMORY.md when it grows beyond a configurable size limit.
"""

from __future__ import annotations

import os
import shutil
import subprocess


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
        """Return container names for judges with mode=='agentic' only.

        Stateless judges do not need persistent containers and are skipped.

        Parameters
        ----------
        ablation_config:
            Dict with a "judges" list, each entry having at least "name" and
            "mode" keys.

        Returns
        -------
        List of strings in the form ``"judge-{name}"`` for each agentic judge.
        """
        names: list[str] = []
        for judge in ablation_config.get("judges", []):
            if judge.get("mode") == "agentic":
                names.append(f"judge-{judge['name']}")
        return names

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
        memory_md_path = os.path.abspath(os.path.join(self.judge_configs_dir, "MEMORY.md"))

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
                memory_md_path: {
                    "bind": "/judge/MEMORY.md",
                    "mode": "rw",
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

    # -----------------------------------------------------------------------
    # append_memory_entry
    # -----------------------------------------------------------------------

    def append_memory_entry(self, container_name: str, entry: str) -> None:
        """Append an entry string to /judge/MEMORY.md inside the container.

        Uses ``docker exec -i`` with stdin so no shell quoting issues arise.

        Parameters
        ----------
        container_name:
            Name of the running judge container.
        entry:
            The markdown text to append (newline-terminated recommended).
        """
        subprocess.run(
            [
                "docker", "exec", "-i", container_name,
                "sh", "-c", "cat >> /judge/MEMORY.md",
            ],
            input=entry.encode(),
            check=True,
        )

    # -----------------------------------------------------------------------
    # truncate_memory_if_needed
    # -----------------------------------------------------------------------

    def truncate_memory_if_needed(
        self, container_name: str, max_size_kb: int = 50
    ) -> None:
        """Truncate /judge/MEMORY.md if it exceeds max_size_kb kilobytes.

        If the file is under the limit, returns immediately.

        If over the limit: reads the content, splits on "## Findings", keeps
        the last 50 verdict entries (``### Judgment`` blocks) from the history
        section plus the entire Findings section, then writes the trimmed
        content back.

        Parameters
        ----------
        container_name:
            Name of the running judge container.
        max_size_kb:
            Maximum file size in kilobytes before truncation occurs.
        """
        max_bytes = max_size_kb * 1024

        # Check current file size via wc -c
        result = subprocess.run(
            ["docker", "exec", container_name, "wc", "-c", "/judge/MEMORY.md"],
            capture_output=True,
            text=True,
            check=False,
        )
        # wc -c output: "  <N> /judge/MEMORY.md"
        try:
            size_bytes = int(result.stdout.strip().split()[0])
        except (ValueError, IndexError):
            return  # File missing or unreadable — nothing to do

        if size_bytes < max_bytes:
            return

        # Read the full content
        read_result = subprocess.run(
            ["docker", "exec", container_name, "cat", "/judge/MEMORY.md"],
            capture_output=True,
            text=True,
            check=False,
        )
        content = read_result.stdout

        # Split into history and findings sections
        if "## Findings" in content:
            history_part, findings_part = content.split("## Findings", 1)
            findings_section = "## Findings" + findings_part
        else:
            history_part = content
            findings_section = ""

        # Keep last 50 verdict blocks (split on "### Judgment" headings)
        blocks = history_part.split("### Judgment")
        # blocks[0] is the preamble before any judgment; rest are judgment entries
        preamble = blocks[0]
        judgment_blocks = blocks[1:]
        kept_blocks = judgment_blocks[-50:]

        if kept_blocks:
            trimmed_history = preamble + "### Judgment" + "### Judgment".join(kept_blocks)
        else:
            trimmed_history = preamble

        trimmed_content = trimmed_history + findings_section

        # Write back via docker exec -i
        subprocess.run(
            [
                "docker", "exec", "-i", container_name,
                "sh", "-c", "cat > /judge/MEMORY.md",
            ],
            input=trimmed_content.encode(),
            check=True,
        )
