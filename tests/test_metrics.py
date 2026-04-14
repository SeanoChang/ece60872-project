"""Tests for analysis.metrics — TDD: write first, implement second."""

import pytest
from analysis.metrics import (
    compute_detection_rate,
    compute_fpr,
    condorcet_predicted,
    compute_condorcet_gap,
    compute_quorum_survival,
)


# ---------------------------------------------------------------------------
# compute_detection_rate
# ---------------------------------------------------------------------------

def test_detection_rate():
    """2 out of 3 malicious results correctly rejected → 2/3."""
    results = [
        {"ground_truth": "malicious", "decision": "reject"},
        {"ground_truth": "malicious", "decision": "reject"},
        {"ground_truth": "malicious", "decision": "allow"},
        # benign entries should be ignored
        {"ground_truth": "benign", "decision": "reject"},
        {"ground_truth": "benign", "decision": "allow"},
    ]
    assert compute_detection_rate(results) == pytest.approx(2 / 3)


def test_detection_rate_no_malicious():
    """No malicious results → 0.0."""
    results = [
        {"ground_truth": "benign", "decision": "allow"},
        {"ground_truth": "benign", "decision": "reject"},
    ]
    assert compute_detection_rate(results) == 0.0


# ---------------------------------------------------------------------------
# compute_fpr
# ---------------------------------------------------------------------------

def test_fpr():
    """1 out of 3 benign results incorrectly rejected → 1/3."""
    results = [
        {"ground_truth": "benign", "decision": "reject"},
        {"ground_truth": "benign", "decision": "allow"},
        {"ground_truth": "benign", "decision": "allow"},
        # malicious entries should be ignored
        {"ground_truth": "malicious", "decision": "reject"},
        {"ground_truth": "malicious", "decision": "allow"},
    ]
    assert compute_fpr(results) == pytest.approx(1 / 3)


def test_fpr_no_benign():
    """No benign results → 0.0."""
    results = [
        {"ground_truth": "malicious", "decision": "reject"},
        {"ground_truth": "malicious", "decision": "allow"},
    ]
    assert compute_fpr(results) == 0.0


# ---------------------------------------------------------------------------
# condorcet_predicted
# ---------------------------------------------------------------------------

def test_condorcet_predicted_p08_n3():
    """p=0.8, n=3 → 0.896."""
    result = condorcet_predicted(p=0.8, n=3)
    assert result == pytest.approx(0.896, rel=1e-6)


def test_condorcet_predicted_p05_n3():
    """p=0.5, n=3 → 0.5 (majority vote on a coin flip stays 0.5)."""
    result = condorcet_predicted(p=0.5, n=3)
    assert result == pytest.approx(0.5, rel=1e-6)


# ---------------------------------------------------------------------------
# compute_condorcet_gap
# ---------------------------------------------------------------------------

def test_condorcet_gap_negative():
    """observed < predicted → negative gap (correlated / common-mode errors)."""
    # p=0.8, n=3 → predicted ≈ 0.896; observed below that
    gap = compute_condorcet_gap(p=0.8, observed=0.8, n=3)
    assert gap < 0


def test_condorcet_gap_zero():
    """observed == predicted → zero gap (perfectly independent judges)."""
    predicted = condorcet_predicted(p=0.8, n=3)
    gap = compute_condorcet_gap(p=0.8, observed=predicted, n=3)
    assert gap == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# compute_quorum_survival
# ---------------------------------------------------------------------------

def test_quorum_survival_full():
    """Same detection rate for byzantine and honest → ratio 1.0."""
    assert compute_quorum_survival(detection_byzantine=0.9, detection_honest=0.9) == pytest.approx(1.0)


def test_quorum_survival_collapse():
    """Byzantine detection 0 → ratio 0.0 (quorum collapse)."""
    assert compute_quorum_survival(detection_byzantine=0.0, detection_honest=0.9) == pytest.approx(0.0)
