"""Tests for core.api_proxy.ApiProxy — written TDD-first.

These are UNIT tests only; no real HTTP forwarding is tested.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.api_proxy import ApiProxy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def proxy(tmp_path):
    """Return an ApiProxy instance with known budgets — not started."""
    log_file = tmp_path / "proxy.jsonl"
    return ApiProxy(
        host="127.0.0.1",
        port=8081,
        api_key="sk-ant-api03-TESTKEY",
        budgets={"agent-main": 5.0, "judge-a": 0.50},
        log_path=str(log_file),
    )


# ---------------------------------------------------------------------------
# Test 1 — _inject_headers: x-api-key added, x-judge-id stripped, host stripped
# ---------------------------------------------------------------------------


def test_inject_headers(proxy: ApiProxy):
    """_inject_headers adds x-api-key, removes x-judge-id and host."""
    original = {
        "content-type": "application/json",
        "x-judge-id": "judge-a",
        "host": "127.0.0.1:8081",
        "anthropic-version": "2023-06-01",
    }
    result = proxy._inject_headers(original)

    assert result["x-api-key"] == "sk-ant-api03-TESTKEY"
    assert "x-judge-id" not in result
    assert "host" not in result
    assert result["content-type"] == "application/json"
    assert result["anthropic-version"] == "2023-06-01"


# ---------------------------------------------------------------------------
# Test 2 — _check_budget_within: spend < limit → True
# ---------------------------------------------------------------------------


def test_check_budget_within(proxy: ApiProxy):
    """Agent with cumulative spend below its limit returns True."""
    # judge-a has a budget of 0.50; no spend yet → within budget
    assert proxy._check_budget("judge-a") is True


# ---------------------------------------------------------------------------
# Test 3 — _check_budget_exceeded: spend >= limit → False
# ---------------------------------------------------------------------------


def test_check_budget_exceeded(proxy: ApiProxy):
    """Agent with cumulative spend at or above its limit returns False."""
    # Artificially set spend to the limit
    proxy._spend["judge-a"] = 0.50

    assert proxy._check_budget("judge-a") is False


# ---------------------------------------------------------------------------
# Test 4 — _check_budget_unknown_agent: agent not in budgets → False
# ---------------------------------------------------------------------------


def test_check_budget_unknown_agent(proxy: ApiProxy):
    """Unknown agent_id (not in budgets dict) returns False."""
    assert proxy._check_budget("intruder-bot") is False


# ---------------------------------------------------------------------------
# Test 5 — _track_spend: valid usage body → correct cost, cumulative updated
# ---------------------------------------------------------------------------


def test_track_spend_sonnet(proxy: ApiProxy):
    """_track_spend uses Sonnet pricing when model is claude-sonnet-4-6."""
    response_body = {
        "model": "claude-sonnet-4-6-20260101",
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    # Sonnet: input=$3/M, output=$15/M
    expected_cost = (1000 * 3.0 + 200 * 15.0) / 1_000_000

    cost = proxy._track_spend("judge-a", response_body)
    assert cost == pytest.approx(expected_cost)
    assert proxy.get_spend("judge-a") == pytest.approx(expected_cost)


def test_track_spend_haiku(proxy: ApiProxy):
    """_track_spend uses Haiku 4.5 pricing when model is claude-haiku-4-5."""
    response_body = {
        "model": "claude-haiku-4-5-20251001",
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    # Haiku 4.5: input=$1/M, output=$5/M
    expected_cost = (1000 * 1.0 + 200 * 5.0) / 1_000_000

    cost = proxy._track_spend("judge-a", response_body)
    assert cost == pytest.approx(expected_cost)


def test_track_spend_opus(proxy: ApiProxy):
    """_track_spend uses Opus 4.6 pricing when model is claude-opus-4-6."""
    response_body = {
        "model": "claude-opus-4-6-20260101",
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    # Opus 4.6: input=$5/M, output=$25/M
    expected_cost = (1000 * 5.0 + 200 * 25.0) / 1_000_000

    cost = proxy._track_spend("agent-main", response_body)
    assert cost == pytest.approx(expected_cost)


# ---------------------------------------------------------------------------
# Test 6 — _track_spend_no_usage: response body without usage → 0.0 cost
# ---------------------------------------------------------------------------


def test_track_spend_no_usage(proxy: ApiProxy):
    """_track_spend with a response body missing 'usage' returns 0.0 and adds nothing."""
    response_body = {
        "type": "error",
        "error": {"type": "authentication_error", "message": "invalid key"},
    }

    cost = proxy._track_spend("agent-main", response_body)

    assert cost == 0.0
    assert proxy.get_spend("agent-main") == 0.0


# ---------------------------------------------------------------------------
# Test 7 — api_call event emission via events_dir (unit-level constructor check)
# ---------------------------------------------------------------------------
# NOTE: End-to-end api_call event emission (writing api_call.jsonl) requires a
# real upstream HTTP round-trip through proxy_request handler and is covered by
# integration testing.  The constructor-level check below verifies that
# ApiProxy correctly stores ablation and events_dir for later use.


def test_api_proxy_stores_ablation_and_events_dir(tmp_path):
    """ApiProxy stores ablation and events_dir passed at construction time."""
    log_file = tmp_path / "proxy.jsonl"
    proxy = ApiProxy(
        host="127.0.0.1",
        port=8082,
        api_key="sk-ant-TESTKEY",
        budgets={"agent-main": 5.0},
        log_path=str(log_file),
        ablation="A4",
        events_dir=str(tmp_path),
    )

    assert proxy._ablation == "A4"
    assert proxy._events_dir == str(tmp_path)


# ---------------------------------------------------------------------------
# Test 8 — end-to-end api_call event emission through FastAPI app
# ---------------------------------------------------------------------------


def test_api_proxy_emits_api_call_event_with_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ApiProxy emits an ApiCall JSONL event after a forwarded request.

    Uses FastAPI TestClient to hit the proxy's ASGI app directly, with the
    upstream httpx client monkeypatched to return a canned Anthropic-style
    response.  Verifies that run_id (from BFT_RUN_ID env var) and all key
    fields are captured in the emitted event.
    """
    monkeypatch.setenv("BFT_RUN_ID", "run-integration-test")
    events_dir = tmp_path / "events"
    proxy = ApiProxy(
        host="127.0.0.1",
        port=0,
        api_key="test-key",
        budgets={"agent-main": 5.0},
        log_path=str(tmp_path / "proxy.jsonl"),
        ablation="test-ablation",
        events_dir=str(events_dir),
    )

    canned_body = {
        "model": "claude-opus-4-5",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "content": [{"type": "text", "text": "ok"}],
    }
    mock_response = MagicMock()
    mock_response.json.return_value = canned_body
    mock_response.content = json.dumps(canned_body).encode()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    proxy._client.request = AsyncMock(return_value=mock_response)

    client = TestClient(proxy._app)
    resp = client.post(
        "/v1/messages",
        headers={"x-judge-id": "agent-main", "content-type": "application/json"},
        json={"model": "claude-opus-4-5", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200

    event_path = events_dir / "api_call.jsonl"
    assert event_path.exists(), f"expected api_call.jsonl at {event_path}"
    lines = event_path.read_text().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])

    assert event["run_id"] == "run-integration-test"
    assert event["ablation"] == "test-ablation"
    assert event["agent_id"] == "agent-main"
    assert event["input_tokens"] == 100
    assert event["output_tokens"] == 50
    assert event["cost_usd"] > 0  # claude-opus pricing (100 in + 50 out)
    assert event["model"] == "claude-opus-4-5"
    assert event["upstream_status"] == 200
    assert event["scenario_run_id"] in ("unknown", "")


# ---------------------------------------------------------------------------
# Test 9 — run_id is captured from BFT_RUN_ID env var at construction time
# ---------------------------------------------------------------------------


def test_api_proxy_run_id_from_env(tmp_path, monkeypatch):
    """ApiProxy reads BFT_RUN_ID from env at init time (ContextVars don't survive subprocess)."""
    monkeypatch.setenv("BFT_RUN_ID", "run-xyz")

    log_file = tmp_path / "proxy.jsonl"
    proxy = ApiProxy(
        host="127.0.0.1",
        port=8083,
        api_key="sk-ant-TESTKEY",
        budgets={"agent-main": 5.0},
        log_path=str(log_file),
    )

    assert proxy._run_id == "run-xyz"
