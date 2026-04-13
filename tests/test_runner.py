"""Tests for ablations/runner.py — written first (TDD)."""

import json
import os
import tempfile

import pytest

from ablations.runner import build_run_matrix, load_ablation_config, run_single


# ---------------------------------------------------------------------------
# 1. test_load_config
# ---------------------------------------------------------------------------

def test_load_config():
    """Create a temp JSON file, load it, verify contents round-trip."""
    payload = {"baseline": True, "timeout": 30, "nodes": [1, 2, 3]}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as fh:
        json.dump(payload, fh)
        tmp_path = fh.name

    try:
        result = load_ablation_config(tmp_path)
        assert result == payload
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 2. test_build_run_matrix — 2 × 2 × 2 = 8 runs
# ---------------------------------------------------------------------------

def test_build_run_matrix():
    scenarios = ["configs/scenario_a.json", "configs/scenario_b.json"]
    ablations = ["baseline", "no_commit"]
    repetitions = 2

    matrix = build_run_matrix(scenarios, ablations, repetitions)

    assert len(matrix) == 8

    required_keys = {"scenario", "ablation", "config_path", "repetition", "run_id"}
    for entry in matrix:
        assert required_keys.issubset(entry.keys()), f"Missing keys in {entry}"


# ---------------------------------------------------------------------------
# 3. test_build_run_matrix_single — 1 × 1 × 1 = 1 run
# ---------------------------------------------------------------------------

def test_build_run_matrix_single():
    scenarios = ["configs/only.json"]
    ablations = ["only_ablation"]
    repetitions = 1

    matrix = build_run_matrix(scenarios, ablations, repetitions)

    assert len(matrix) == 1
    entry = matrix[0]
    assert entry["scenario"] == "configs/only.json"
    assert entry["ablation"] == "only_ablation"
    assert entry["config_path"] == "configs/only.json"
    assert entry["repetition"] == 0


# ---------------------------------------------------------------------------
# 4. test_run_id_format — run_id contains ablation name and scenario stem
# ---------------------------------------------------------------------------

def test_run_id_format():
    scenarios = ["configs/my_scenario.json"]
    ablations = ["my_ablation"]
    repetitions = 1

    matrix = build_run_matrix(scenarios, ablations, repetitions)
    run_id = matrix[0]["run_id"]

    assert "my_ablation" in run_id, f"ablation name missing from run_id: {run_id}"
    assert "my_scenario" in run_id, f"scenario stem missing from run_id: {run_id}"
