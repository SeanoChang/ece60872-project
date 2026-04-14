"""Tests for ExperimentRunner — mocked phases, no real infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def ablation_config_file(tmp_path: Path) -> Path:
    cfg = {
        "ablation": "test-ablation",
        "judges": [
            {
                "name": "param",
                "model": "claude-sonnet-4-6-20260101",
                "system_prompt_path": "prompts/honest/param.md",
                "role": "param",
            },
        ],
        "log_path": str(tmp_path / "results/test/orchestrator.jsonl"),
    }
    path = tmp_path / "ablation.json"
    path.write_text(json.dumps(cfg))
    return path


@pytest.fixture
def scenario_file(tmp_path: Path) -> Path:
    yaml_content = """
scenario_id: test-scenario
description: test
archetype: test
task_prompt: "Do the test"
workspace:
  files:
    README.md: "hi"
canary_credentials: []
ground_truth:
  expected_dangerous_calls: []
  expected_benign_calls: []
"""
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml_content)
    return path


@pytest.mark.asyncio
async def test_experiment_runner_runs_all_scenarios(
    tmp_path: Path,
    ablation_config_file: Path,
    scenario_file: Path,
):
    from ablations.experiment import ExperimentRunner

    runner = ExperimentRunner(
        ablation_config_path=str(ablation_config_file),
        scenario_paths=[str(scenario_file)],
        reps=2,
        max_concurrency=2,
        api_key="sk-ant-TEST",
        results_root=str(tmp_path / "results"),
    )

    with (
        patch.object(runner, "_setup", new_callable=AsyncMock) as mock_setup,
        patch.object(runner, "_run_scenario_rep", new_callable=AsyncMock, return_value={"status": "ok"}) as mock_run,
        patch.object(runner, "_teardown", new_callable=AsyncMock) as mock_teardown,
    ):
        summary = await runner.run()

    assert mock_setup.await_count == 1
    assert mock_run.await_count == 2
    assert mock_teardown.await_count == 1
    assert summary["ablation"] == "test-ablation"
    assert summary["total_runs"] == 2


@pytest.mark.asyncio
async def test_experiment_runner_soft_aborts_after_retry(
    tmp_path: Path,
    ablation_config_file: Path,
    scenario_file: Path,
):
    from ablations.experiment import ExperimentRunner

    runner = ExperimentRunner(
        ablation_config_path=str(ablation_config_file),
        scenario_paths=[str(scenario_file)],
        reps=1,
        max_concurrency=1,
        api_key="sk-ant-TEST",
        results_root=str(tmp_path / "results"),
    )

    with (
        patch.object(runner, "_setup", new_callable=AsyncMock),
        patch.object(runner, "_run_scenario_rep", new_callable=AsyncMock, side_effect=RuntimeError("infra fail")),
        patch.object(runner, "_teardown", new_callable=AsyncMock) as mock_teardown,
    ):
        summary = await runner.run()

    assert mock_teardown.await_count == 1
    assert summary["soft_abort"] is True
