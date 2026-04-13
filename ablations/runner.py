"""Experiment runner for ablation studies.

Provides utilities to load configs, build a full run matrix, and execute
individual runs (Docker orchestration is a future concern).
"""

import argparse
import json
import time
from pathlib import Path


def load_ablation_config(path: str) -> dict:
    """Load and return JSON config from *path*."""
    with open(path, "r") as fh:
        return json.load(fh)


def build_run_matrix(scenarios: list, ablations: list, repetitions: int) -> list:
    """Build the full experiment matrix.

    Returns a flat list of dicts, one per (scenario, ablation, repetition)
    combination.  Each entry contains:
        scenario    – original scenario path string
        ablation    – ablation name string
        config_path – same as scenario (aliased for clarity)
        repetition  – zero-based repetition index
        run_id      – unique identifier for this run
    """
    matrix = []
    ts = int(time.time())
    for ablation in ablations:
        for scenario in scenarios:
            stem = Path(scenario).stem
            for rep in range(repetitions):
                run_id = f"{ablation}_{stem}_r{rep}_{ts}"
                matrix.append(
                    {
                        "scenario": scenario,
                        "ablation": ablation,
                        "config_path": scenario,
                        "repetition": rep,
                        "run_id": run_id,
                    }
                )
    return matrix


def run_single(run: dict) -> dict:
    """Placeholder runner — full Docker orchestration will be added later.

    Loads the config for the run, prints run info, and returns a minimal
    result dict indicating that the run is not yet implemented.
    """
    config = load_ablation_config(run["config_path"])
    print(
        f"[runner] run_id={run['run_id']} | ablation={run['ablation']} "
        f"| scenario={run['scenario']} | rep={run['repetition']} "
        f"| config_keys={list(config.keys())}"
    )
    return {"run_id": run["run_id"], "status": "not_implemented"}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ablation study experiment runner")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        required=True,
        help="One or more scenario config file paths",
    )
    parser.add_argument(
        "--ablations",
        nargs="+",
        required=True,
        help="One or more ablation names",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=3,
        help="Number of repetitions per (scenario, ablation) pair (default: 3)",
    )
    args = parser.parse_args()

    matrix = build_run_matrix(args.scenarios, args.ablations, args.reps)
    print(f"Total runs: {len(matrix)}")

    for run in matrix:
        result = run_single(run)
        print(result)
