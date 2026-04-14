"""Scenario loading and workspace rendering with canary credentials."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Scenario:
    scenario_id: str
    description: str
    archetype: str
    task_prompt: str
    workspace_files: dict[str, str] = field(default_factory=dict)
    canary_credentials: list[dict] = field(default_factory=list)
    ground_truth: dict = field(default_factory=dict)


def load_scenario(yaml_path: str) -> Scenario:
    """Load a scenario from a YAML file and return a Scenario instance."""
    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    workspace = data.get("workspace", {}) or {}
    workspace_files = workspace.get("files", {}) or {}

    return Scenario(
        scenario_id=data.get("scenario_id", ""),
        description=data.get("description", ""),
        archetype=data.get("archetype", ""),
        task_prompt=data.get("task_prompt", ""),
        workspace_files=workspace_files,
        canary_credentials=data.get("canary_credentials", []) or [],
        ground_truth=data.get("ground_truth", {}) or {},
    )


def _generate_canary(credential_type: str) -> str:
    """Generate a realistic-looking random canary string for the given credential type."""
    rand = secrets.token_urlsafe(32)

    if credential_type == "api_key":
        return f"sk-ant-api03-{rand[:48]}"
    elif credential_type == "aws_key":
        return f"AKIAIOSFODNN7{rand[:16].upper()}"
    elif credential_type == "ssh_key":
        return (
            f"-----BEGIN RSA PRIVATE KEY-----\n"
            f"canary-{rand}\n"
            f"-----END RSA PRIVATE KEY-----"
        )
    elif credential_type == "npm_token":
        return f"npm_{rand[:36]}"
    else:
        return f"canary-{rand}"


def render_workspace(scenario: Scenario, workspace_dir: str) -> dict[str, str]:
    """
    Render the scenario workspace to disk, injecting canary credentials.

    Returns a dict mapping canary key (e.g. "api_key_0") to generated canary value.
    """
    ws_path = Path(workspace_dir)
    ws_path.mkdir(parents=True, exist_ok=True)

    # Write workspace files
    for relpath, content in scenario.workspace_files.items():
        target = ws_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    # Inject canary credentials
    canaries: dict[str, str] = {}
    for i, cred in enumerate(scenario.canary_credentials):
        cred_type = cred.get("type", "generic")
        location = cred["location"]
        template = cred.get("value_template", "{canary}")

        value = _generate_canary(cred_type)
        rendered = template.replace("{canary}", value)

        target = ws_path / location
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_text()
            target.write_text(existing + "\n" + rendered)
        else:
            target.write_text(rendered)

        canaries[f"{cred_type}_{i}"] = value

    return canaries
