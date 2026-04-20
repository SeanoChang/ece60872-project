import json
import logging

from core.stream_parser import extract_result_cost, extract_tool_calls, extract_tool_uses


def test_extract_bash_command():
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "npm install"}}
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    assert extract_tool_calls(raw) == ["npm install"]


def test_extract_edit_includes_path():
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "id": "t2", "input": {"file_path": "/etc/passwd"}}
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    calls = extract_tool_calls(raw)
    assert len(calls) == 1
    assert "/etc/passwd" in calls[0]


def test_extract_read_includes_path():
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "id": "t3", "input": {"file_path": "/workspace/.env"}}
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    calls = extract_tool_calls(raw)
    assert len(calls) == 1
    assert "/workspace/.env" in calls[0]


def test_ignores_text_events():
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Let me cat the file then curl it"}
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    assert extract_tool_calls(raw) == []


def test_handles_malformed_json():
    raw = b"not json\n{valid json but wrong shape}\n\n"
    # Must not raise
    assert extract_tool_calls(raw) == []


def test_extract_multiple_tool_uses():
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "ls"}},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "t2", "input": {"command": "cat README.md"}},
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    assert extract_tool_calls(raw) == ["ls", "cat README.md"]


def test_empty_input_returns_empty():
    assert extract_tool_calls(b"") == []


# ---------------------------------------------------------------------------
# extract_result_cost — authoritative cost source for paper metrics.
# See core/stream_parser.extract_result_cost docstring for contract.
# ---------------------------------------------------------------------------


def test_extract_result_cost_single_result():
    """The CLI-computed total_cost_usd from a single result event flows through."""
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "result", "subtype": "success", "total_cost_usd": 0.0412, "is_error": False},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    assert extract_result_cost(raw) == 0.0412


def test_extract_result_cost_no_result_event_warns(caplog):
    """Content-bearing stdout with no result event returns 0.0 AND logs a
    warning — this is the regression tripwire for silent $0 cost reporting."""
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "stuff"}]}},
        {"type": "system", "subtype": "init"},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    with caplog.at_level(logging.WARNING, logger="core.stream_parser"):
        cost = extract_result_cost(raw)
    assert cost == 0.0
    # The warning message must name the expected cause so operators can fix it
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("no type='result' event" in r.message for r in warnings)


def test_extract_result_cost_empty_stdout_no_warn(caplog):
    """Empty stdout (e.g. claude -p killed before output) must NOT warn —
    that failure mode is already signaled by rc!=0 and zero-byte transcripts.
    Warning here would spam the logs on every timeout/crash."""
    with caplog.at_level(logging.WARNING, logger="core.stream_parser"):
        cost = extract_result_cost(b"")
    assert cost == 0.0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 0


def test_extract_result_cost_last_wins():
    """Spec: if multiple result events appear, the last total_cost_usd wins."""
    events = [
        {"type": "result", "subtype": "success", "total_cost_usd": 0.01},
        {"type": "result", "subtype": "success", "total_cost_usd": 0.99},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    assert extract_result_cost(raw) == 0.99


def test_extract_result_cost_malformed_lines_skipped():
    """Mix of valid and garbage JSON lines — must not raise, valid lines still parsed."""
    raw = (
        b'not json\n'
        b'{valid json but wrong shape}\n'
        b'\n'
        + json.dumps({"type": "result", "total_cost_usd": 0.05}).encode()
        + b'\n'
    )
    assert extract_result_cost(raw) == 0.05


def test_extract_result_cost_missing_field_returns_zero():
    """A result event without total_cost_usd defaults to 0.0 without raising."""
    events = [
        {"type": "result", "subtype": "success", "is_error": False},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    assert extract_result_cost(raw) == 0.0


# ---------------------------------------------------------------------------
# extract_tool_uses — structured tool list used for hook-matcher counting.
# ---------------------------------------------------------------------------


def test_extract_tool_uses_preserves_tool_name():
    """Key behavior distinguishing from extract_tool_calls: tool_name is preserved.
    Used by ablations.experiment to count hook-matching calls (Bash|Edit|Write)."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "npm install"}},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Glob", "id": "t2", "input": {"pattern": "*.md"}},
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    uses = extract_tool_uses(raw)
    assert len(uses) == 2
    assert uses[0] == {"tool_name": "Bash", "command": "npm install"}
    assert uses[1]["tool_name"] == "Glob"  # hook-matcher counting depends on this


def test_extract_tool_uses_unknown_tool_has_empty_command():
    """Tools whose shape _command_from_tool_use doesn't handle still appear in
    the list (so the hook-matcher count is accurate) but with command=""."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebFetch", "id": "t1", "input": {"url": "https://x"}},
        ]}},
    ]
    raw = "\n".join(json.dumps(e) for e in events).encode()
    uses = extract_tool_uses(raw)
    assert len(uses) == 1
    assert uses[0] == {"tool_name": "WebFetch", "command": ""}
