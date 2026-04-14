import json
from core.stream_parser import extract_tool_calls


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
