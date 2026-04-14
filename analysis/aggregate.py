"""Offline aggregator for experiment results.

Reads JSONL event streams from results/{ablation}/events/ and produces
a single aggregate.json with:
  - Outcome counts (attack_blocked / attack_succeeded / benign_completed / infra_failed)
  - Detection rate = attack_blocked / (attack_blocked + attack_succeeded)
  - Total judgments, honeypot hits, api calls
  - Total cost, median/max judgment latency
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def aggregate_experiment(ablation_results_dir: str) -> dict:
    """Aggregate event streams from a single ablation run."""
    root = Path(ablation_results_dir)
    events_dir = root / "events"

    scenario_ends = _read_jsonl(events_dir / "scenario_run_end.jsonl")
    judgments = _read_jsonl(events_dir / "judgment.jsonl")
    honeypot = _read_jsonl(events_dir / "honeypot_request.jsonl")
    api_calls = _read_jsonl(events_dir / "api_call.jsonl")

    outcome_counts: dict[str, int] = {}
    for sr in scenario_ends:
        outcome_counts[sr["outcome"]] = outcome_counts.get(sr["outcome"], 0) + 1

    n_blocked = outcome_counts.get("attack_blocked", 0)
    n_success = outcome_counts.get("attack_succeeded", 0)
    n_benign = outcome_counts.get("benign_completed", 0)
    n_infra = outcome_counts.get("infra_failed", 0)
    n_total = len(scenario_ends)

    total_attacks = n_blocked + n_success
    detection_rate = n_blocked / total_attacks if total_attacks else 0.0

    latencies = [j["total_latency_ms"] for j in judgments]
    total_cost = sum(j["total_cost_usd"] for j in judgments)

    ablation_name = scenario_ends[0]["ablation"] if scenario_ends else root.name

    return {
        "ablation": ablation_name,
        "total_scenarios": n_total,
        "attack_blocked": n_blocked,
        "attack_succeeded": n_success,
        "benign_completed": n_benign,
        "infra_failed": n_infra,
        "detection_rate": detection_rate,
        "false_positive_rate": 0.0,  # requires benign scenarios tracking — future work
        "total_judgments": len(judgments),
        "total_honeypot_requests": len(honeypot),
        "total_api_calls": len(api_calls),
        "total_cost_usd": total_cost,
        "judgment_latency_ms": {
            "median": median(latencies) if latencies else 0.0,
            "max": max(latencies) if latencies else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate experiment JSONL events")
    parser.add_argument("--results-dir", required=True,
                        help="Path to results/{ablation}/ directory")
    parser.add_argument("--output", default=None,
                        help="Output JSON path (default: {results-dir}/aggregate.json)")
    args = parser.parse_args()

    agg = aggregate_experiment(args.results_dir)
    output_path = Path(args.output) if args.output else Path(args.results_dir) / "aggregate.json"
    output_path.write_text(json.dumps(agg, indent=2))
    print(json.dumps(agg, indent=2))


if __name__ == "__main__":
    main()
