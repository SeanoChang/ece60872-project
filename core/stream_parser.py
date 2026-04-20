"""Parse Claude Code's --output-format stream-json output.

Claude Code emits JSONL where each line is an event. Tool invocations appear
as content blocks with type "tool_use" inside assistant messages. This module
walks the event stream structurally to extract the actual commands/paths the
agent tried to execute — used for ground-truth pattern matching.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)


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


def extract_result_cost(stream_json_bytes: bytes) -> float:
    """Return the total_cost_usd from the final `type: "result"` event, or 0.0.

    Claude Code's stream-json emits one result event at session end with a
    CLI-computed total_cost_usd. This is the authoritative cost number — it
    already aggregates per-message usage and applies cache discounts. Summing
    intermediate `assistant` events' usage would double-count cached reads.

    If multiple result events appear (shouldn't happen but be robust), the
    last one wins.

    Logs a warning when stdout has content (non-blank lines) but no
    `type: "result"` event was ever seen. This is a tripwire for the
    regression mode where a caller invokes claude without
    `--output-format stream-json`, or the CLI's stream-json schema drifts
    and drops the result event — either way, cost_usd would silently
    fall back to 0.0 without detection. Empty stdout (process killed
    before output) is treated as a different failure and not warned about
    here — the caller already knows about it from rc != 0 or timeouts.
    """
    text = stream_json_bytes.decode(errors="replace")
    total = 0.0
    saw_result = False
    saw_content = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        saw_content = True
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            saw_result = True
            val = event.get("total_cost_usd")
            if val is not None:
                total = float(val)
    if saw_content and not saw_result:
        _logger.warning(
            "extract_result_cost: stdout had content but no type='result' event — "
            "cost will report $0.00. Likely causes: CLI invoked without "
            "--output-format stream-json, or Claude Code schema changed. "
            "Verify core/runner_agent.py and core/agentic_judge.py still pass "
            "--output-format stream-json --verbose."
        )
    return total


def extract_tool_uses(stream_json_bytes: bytes) -> list[dict]:
    """Like extract_tool_calls, but preserves tool_name for every tool_use block.

    Returns one dict per tool_use: {"tool_name": str, "command": str}. `command`
    is the same string `extract_tool_calls` would have returned for this block,
    or "" for tools whose shape `_command_from_tool_use` doesn't handle. Used
    by the experiment runner to build the per-run summary and count calls
    that would match the PreToolUse hook matcher.
    """
    text = stream_json_bytes.decode(errors="replace")
    uses: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for tc in _find_tool_uses(event):
            name = tc.get("name", "") or ""
            cmd = _command_from_tool_use(tc) or ""
            uses.append({"tool_name": name, "command": cmd})
    return uses


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
