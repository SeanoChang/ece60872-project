"""Tests for core.api_proxy.ApiProxy — written TDD-first.

These are UNIT tests only; no real HTTP forwarding is tested.
"""

from __future__ import annotations

import pytest

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
    """_track_spend uses Haiku pricing when model is claude-haiku-4-5."""
    response_body = {
        "model": "claude-haiku-4-5-20251001",
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    # Haiku: input=$0.80/M, output=$4/M
    expected_cost = (1000 * 0.80 + 200 * 4.0) / 1_000_000

    cost = proxy._track_spend("judge-a", response_body)
    assert cost == pytest.approx(expected_cost)


def test_track_spend_opus(proxy: ApiProxy):
    """_track_spend uses Opus pricing when model is claude-opus-4-6."""
    response_body = {
        "model": "claude-opus-4-6-20260101",
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    # Opus: input=$15/M, output=$75/M
    expected_cost = (1000 * 15.0 + 200 * 75.0) / 1_000_000

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
