"""Tests for core/orchestrator.py — TDD suite for Task 8: Orchestrator."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core.types import JudgeVote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_judge_vote(
    decision: str,
    judge_name: str = "judge-a",
    confidence: float = 0.9,
) -> JudgeVote:
    """Build a minimal JudgeVote for testing."""
    return JudgeVote(
        judge_name=judge_name,
        model_id="claude-sonnet-4-6-20260101",
        decision=decision,
        confidence=confidence,
        reason=f"test reason ({decision})",
        latency_ms=100.0,
        cost_usd=0.001,
        is_byzantine=False,
    )


def _make_config(log_path: str, num_judges: int = 3) -> dict:
    """Build a minimal ablation config dict for testing."""
    judges = [
        {
            "name": f"judge-{i}",
            "model": "claude-sonnet-4-6-20260101",
            "system_prompt_path": "/fake/path/prompt.md",
            "temperature": 0.0,
            "role": "general",
            "is_byzantine": False,
        }
        for i in range(num_judges)
    ]
    return {
        "ablation": "test-ablation",
        "judges": judges,
        "memory_window": 5,
        "log_path": log_path,
    }


def _make_hook_payload() -> dict:
    """Build a minimal Claude Code PreToolUse hook payload."""
    return {
        "toolName": "Bash",
        "toolUseId": "toolu_test999",
        "sessionId": "sess_xyz",
        "cwd": "/tmp",
        "tool_input": {"command": "ls -la /tmp"},
    }


# ---------------------------------------------------------------------------
# Test: POST /judge — 2 approve + 1 reject → decision="approve"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_approve(tmp_path: Path) -> None:
    """2 approve + 1 reject votes → response decision='approve'."""
    from core.orchestrator import create_app

    log_file = str(tmp_path / "test.jsonl")
    config = _make_config(log_file, num_judges=3)

    votes = [
        _make_judge_vote("approve", "judge-0"),
        _make_judge_vote("approve", "judge-1"),
        _make_judge_vote("reject", "judge-2"),
    ]

    app = create_app(config)

    with patch("core.orchestrator.run_judges", new=AsyncMock(return_value=votes)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/judge", json=_make_hook_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "approve"
    assert "votes" in body
    assert len(body["votes"]) == 3


# ---------------------------------------------------------------------------
# Test: POST /judge — 2 reject + 1 approve → decision="reject"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_reject(tmp_path: Path) -> None:
    """2 reject + 1 approve votes → response decision='reject'."""
    from core.orchestrator import create_app

    log_file = str(tmp_path / "test.jsonl")
    config = _make_config(log_file, num_judges=3)

    votes = [
        _make_judge_vote("reject", "judge-0"),
        _make_judge_vote("reject", "judge-1"),
        _make_judge_vote("approve", "judge-2"),
    ]

    app = create_app(config)

    with patch("core.orchestrator.run_judges", new=AsyncMock(return_value=votes)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/judge", json=_make_hook_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "reject"
    assert "votes" in body
    assert len(body["votes"]) == 3


# ---------------------------------------------------------------------------
# Test: JSONL log record is written with correct fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_logs_record(tmp_path: Path) -> None:
    """After a /judge request, verify JSONL log contains one record with expected fields."""
    from core.logger import JSONLLogger
    from core.orchestrator import create_app

    log_file = str(tmp_path / "test.jsonl")
    config = _make_config(log_file, num_judges=3)

    votes = [
        _make_judge_vote("approve", "judge-0"),
        _make_judge_vote("approve", "judge-1"),
        _make_judge_vote("reject", "judge-2"),
    ]

    app = create_app(config)

    with patch("core.orchestrator.run_judges", new=AsyncMock(return_value=votes)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/judge", json=_make_hook_payload())

    assert resp.status_code == 200

    logger = JSONLLogger(log_file)
    records = logger.read_all()
    assert len(records) == 1

    record = records[0]
    # Required top-level fields
    assert "timestamp" in record
    assert "session_id" in record
    assert "ablation" in record
    assert "tool_call" in record
    assert "judges" in record
    assert "decision" in record
    assert "quorum_rule" in record
    assert "total_latency_ms" in record
    assert "total_cost_usd" in record

    # Check values
    assert record["session_id"] == "sess_xyz"
    assert record["ablation"] == "test-ablation"
    assert record["decision"] == "approve"
    assert record["tool_call"]["tool_name"] == "Bash"
    assert isinstance(record["judges"], list)
    assert len(record["judges"]) == 3

    # Each judge record should have expected fields
    judge_record = record["judges"][0]
    assert "judge_name" in judge_record
    assert "model" in judge_record
    assert "decision" in judge_record
    assert "confidence" in judge_record
    assert "reason" in judge_record
    assert "is_byzantine" in judge_record
    assert "latency_ms" in judge_record
    assert "cost_usd" in judge_record


# ---------------------------------------------------------------------------
# Test: GET /health returns judges count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_health(tmp_path: Path) -> None:
    """GET /health returns {status: 'ok', judges: N} where N matches config."""
    from core.orchestrator import create_app

    log_file = str(tmp_path / "test.jsonl")
    config = _make_config(log_file, num_judges=3)
    app = create_app(config)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["judges"] == 3


# ---------------------------------------------------------------------------
# Test: Single-judge config → singleton quorum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_single_judge(tmp_path: Path) -> None:
    """Config with 1 judge → quorum_rule='singleton' in log record."""
    from core.logger import JSONLLogger
    from core.orchestrator import create_app

    log_file = str(tmp_path / "test.jsonl")
    config = _make_config(log_file, num_judges=1)

    votes = [_make_judge_vote("approve", "judge-0")]

    app = create_app(config)

    with patch("core.orchestrator.run_judges", new=AsyncMock(return_value=votes)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/judge", json=_make_hook_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "approve"

    logger = JSONLLogger(log_file)
    records = logger.read_all()
    assert len(records) == 1
    assert records[0]["quorum_rule"] == "singleton"


# ---------------------------------------------------------------------------
# Test: agentic mode dispatches via run_agentic_judge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_agentic_mode(tmp_path):
    """When judges have mode=agentic, orchestrator dispatches via run_agentic_judge."""
    prompt_file = tmp_path / "threat.md"
    prompt_file.write_text("You are a threat modeler.")

    config = {
        "ablation": "A4-b",
        "judges": [
            {
                "name": "threat",
                "model": "claude-sonnet-4-6-20260101",
                "system_prompt_path": str(prompt_file),
                "role": "threat",
                "mode": "agentic",
            },
        ],
        "log_path": str(tmp_path / "log.jsonl"),
    }

    mock_vote = JudgeVote(
        judge_name="threat",
        model_id="claude-sonnet-4-6-20260101",
        decision="reject",
        confidence=0.9,
        reason="found typosquat",
    )

    from core.orchestrator import create_app
    app = create_app(config)

    with patch("core.orchestrator.run_agentic_judge", new_callable=AsyncMock, return_value=mock_vote) as mock_fn:
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/judge", json={
                "toolName": "Bash",
                "tool_input": {"command": "npm install"},
                "toolUseId": "toolu_01",
                "sessionId": "sess_01",
            })

    assert resp.status_code == 200
    assert resp.json()["decision"] == "reject"
    mock_fn.assert_awaited_once()
    assert mock_fn.call_args.kwargs["container_name"] == "judge-threat"
