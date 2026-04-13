"""Tests for core/voting.py — written before implementation (TDD)."""

import pytest

from core.types import JudgeVote, VoteResult
from core.voting import classify, majority_vote


def make_vote(decision: str, latency_ms: float = 10.0, cost_usd: float = 0.001) -> JudgeVote:
    """Helper to create a JudgeVote with minimal boilerplate."""
    return JudgeVote(
        judge_name="test-judge",
        model_id="claude-3-5-haiku-20241022",
        decision=decision,
        confidence=0.9,
        reason="test reason",
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# majority_vote tests
# ---------------------------------------------------------------------------


def test_majority_approve_2_of_3():
    """2 approvals out of 3 votes -> approve, quorum_rule='majority-3'."""
    votes = [
        make_vote("approve"),
        make_vote("approve"),
        make_vote("reject"),
    ]
    result = majority_vote(votes)
    assert isinstance(result, VoteResult)
    assert result.decision == "approve"
    assert result.quorum_rule == "majority-3"
    assert result.votes is votes


def test_majority_reject_2_of_3():
    """2 rejections out of 3 votes -> reject."""
    votes = [
        make_vote("reject"),
        make_vote("reject"),
        make_vote("approve"),
    ]
    result = majority_vote(votes)
    assert result.decision == "reject"
    assert result.quorum_rule == "majority-3"


def test_majority_tie_rejects():
    """1 approve, 1 reject -> reject (conservative tie-breaking)."""
    votes = [
        make_vote("approve"),
        make_vote("reject"),
    ]
    result = majority_vote(votes)
    assert result.decision == "reject"
    assert result.quorum_rule == "majority-2"


def test_single_judge():
    """Single vote -> quorum_rule='singleton'."""
    votes = [make_vote("approve")]
    result = majority_vote(votes)
    assert result.decision == "approve"
    assert result.quorum_rule == "singleton"


def test_majority_latency_is_max():
    """Total latency should be the max (parallel execution), not the sum."""
    votes = [
        make_vote("approve", latency_ms=100.0),
        make_vote("approve", latency_ms=250.0),
        make_vote("reject", latency_ms=80.0),
    ]
    result = majority_vote(votes)
    assert result.total_latency_ms == 250.0
    # Confirm it is NOT the sum
    assert result.total_latency_ms != 430.0


def test_majority_cost_is_sum():
    """Total cost should be the sum of all vote costs."""
    votes = [
        make_vote("approve", cost_usd=0.001),
        make_vote("approve", cost_usd=0.002),
        make_vote("reject", cost_usd=0.0005),
    ]
    result = majority_vote(votes)
    assert result.total_cost_usd == pytest.approx(0.0035)


# ---------------------------------------------------------------------------
# classify tests
# ---------------------------------------------------------------------------


def test_classify_all_four():
    """All four valid classification outcomes."""
    assert classify("malicious", "reject") == "true_negative"
    assert classify("malicious", "approve") == "false_negative"
    assert classify("benign", "approve") == "true_positive"
    assert classify("benign", "reject") == "false_positive"


def test_classify_invalid():
    """Invalid ground_truth / vote_decision combination raises ValueError."""
    with pytest.raises(ValueError):
        classify("unknown", "approve")

    with pytest.raises(ValueError):
        classify("malicious", "abstain")

    with pytest.raises(ValueError):
        classify("benign", "abstain")
