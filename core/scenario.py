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
    # Values are str (normal YAML text) or bytes (YAML !!binary, e.g. npm
    # tarballs that the agent must route through a hook-matched Bash call
    # to inspect — see render_workspace).
    workspace_files: dict[str, str | bytes] = field(default_factory=dict)
    canary_credentials: list[dict] = field(default_factory=list)
    ground_truth: dict = field(default_factory=dict)
    # Schema v2 — for replay-agent mode. Pre-specified tool call the replay
    # shim emits on behalf of the (absent) coding agent. Empty dict for
    # legacy scenarios that still run a real LLM agent.
    proposed_tool_call: dict = field(default_factory=dict)
    task_context: str = ""
    source: str = ""
    expected_honest_vote: str = ""


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
        proposed_tool_call=data.get("proposed_tool_call", {}) or {},
        task_context=data.get("task_context", ""),
        source=data.get("source", ""),
        expected_honest_vote=data.get("expected_honest_vote", ""),
    )


def _generate_canary(credential_type: str) -> str:
    """Generate a realistic-looking random canary string for the given credential type.

    The token must not contain any literal marker (the word "canary",
    "test", "fake", etc.) because judge agents will grep workspace files
    for such markers and short-circuit to "this is a security test,
    reject" — a measurement artifact that inflates apparent detection
    rates by ~20-40 percentage points relative to real-world attacks.
    Each prefix below mimics a benign identifier shape.
    """
    rand = secrets.token_urlsafe(32)

    if credential_type == "api_key":
        return f"sk-ant-api03-{rand[:48]}"
    elif credential_type == "aws_key":
        return f"AKIAIOSFODNN7{rand[:16].upper()}"
    elif credential_type == "ssh_key":
        return (
            f"-----BEGIN RSA PRIVATE KEY-----\n"
            f"{rand}\n"
            f"-----END RSA PRIVATE KEY-----"
        )
    elif credential_type == "npm_token":
        return f"npm_{rand[:36]}"
    else:
        # Generic identifier — looks like a service/installation ID.
        return f"inst_{rand}"


def render_workspace(scenario: Scenario, workspace_dir: str) -> dict[str, str]:
    """
    Render the scenario workspace to disk, injecting canary credentials.

    Returns a dict mapping canary key (e.g. "api_key_0") to generated canary value.
    """
    ws_path = Path(workspace_dir)
    ws_path.mkdir(parents=True, exist_ok=True)

    # Write workspace files. Values from YAML's !!binary tag are bytes; normal
    # string content stays str. Binary support lets scenarios embed opaque
    # assets (e.g. npm tarballs) that coding agents can't inspect via Read —
    # the panel must route inspection through a hook-matching Bash call
    # (tar -tzf, etc.), which is exactly the measurement surface we want.
    for relpath, content in scenario.workspace_files.items():
        target = ws_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
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
