"""Parse Claude Code's --output-format stream-json output.

Claude Code emits JSONL where each line is an event. Tool invocations appear
as content blocks with type "tool_use" inside assistant messages. This module
walks the event stream structurally to extract the actual commands/paths the
agent tried to execute — used for ground-truth pattern matching.
"""

from __future__ import annotations

import json
from typing import Any


def extract_tool_calls(stream_json_bytes: bytes) -> list[str]:
    """Parse stream-json output, return command-like strings from each tool_use block.

    For Bash: returns input['command'].
    For Edit / Write / Read: returns f"{name} {file_path}" so path-based patterns match.
    Unknown tools: skipped.
    """
    text = stream_json_bytes.decode(errors="replace")
    commands: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for tc in _find_tool_uses(event):
            cmd = _command_from_tool_use(tc)
            if cmd:
                commands.append(cmd)
    return commands


def _find_tool_uses(obj: Any) -> list[dict]:
    """Recursively walk an event tree, collecting every tool_use block."""
    results: list[dict] = []
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use":
            results.append(obj)
        for v in obj.values():
            results.extend(_find_tool_uses(v))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_find_tool_uses(item))
    return results


def _command_from_tool_use(tc: dict) -> str | None:
    """Extract a command string from a tool_use block; None if unsupported shape."""
    name = tc.get("name", "")
    inp = tc.get("input", {})
    if not isinstance(inp, dict):
        return None
    if name == "Bash":
        cmd = inp.get("command", "")
        return str(cmd) if cmd else None
    if name in ("Edit", "Write", "Read"):
        path = inp.get("file_path", "")
        if path:
            return f"{name} {path}"
        return None
    return None
