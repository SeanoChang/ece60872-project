"""Paper-ready metrics analysis.

Reads from `extracted-master/` (produced by `extract_all.py`) and emits
visualization-ready CSVs plus a synthesized findings JSON.

Outputs in `paper-data/`:
- `headline_table.csv` — one row per (scenario, sweep) pair for the paper's
  main result table. Channel-categorized.
- `per_judgment_costs.csv` — per-judgment cost decomposition using
  Haiku-4.5 pricing.
- `cost_decomposition.csv` — by-decision (approve/reject) and by-scenario
  cost summary.
- `channel_summary.csv` — penetration rate aggregated by injection channel.
- `latency_distribution.csv` — judgment-level latency percentiles.
- `summary.json` — top-line numbers for the paper's executive summary.

Pricing (Haiku 4.5, per million tokens):
- input:        $1.00
- 5m cache:     $1.25
- 1h cache:     $2.00
- cache hit:    $0.10
- output:       $5.00
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

# Haiku 4.5 pricing ($/M tokens).
PRICE_INPUT = 1.00
PRICE_CACHE_5M_WRITE = 1.25
PRICE_CACHE_1H_WRITE = 2.00
PRICE_CACHE_HIT = 0.10
PRICE_OUTPUT = 5.00


# ---------------------------------------------------------------------------
# Channel categorization
# ---------------------------------------------------------------------------
# Each scenario gets a (channel, payload_class, composition) tag.

CHANNEL_MAP = {
    # injection channels
    "claudemd-audit-redirect":          ("claude-md",       "supply-chain",  "injection+supply"),
    "agents-md-audit-redirect":         ("agents-md",       "supply-chain",  "injection+supply"),
    "package-json-audit-metadata":      ("pkg-metadata",    "supply-chain",  "injection+supply"),
    "fixture-as-audit-record":          ("json-fixture",    "supply-chain",  "injection+supply"),
    "negative-framing-redirect":        ("claude-md-neg",   "supply-chain",  "injection+supply"),
    "inline-source-audit-comment":      ("inline-comment-directive", "supply-chain", "injection+supply"),
    "inline-source-no-directive":       ("inline-comment",  "supply-chain",  "injection+supply"),
    "readme-broken-optout":             ("broken-defense",  "supply-chain",  "injection+supply"),
    # pure supply-chain (no injection amplifier)
    "probe-02-bearer-auth":             ("baseline",        "supply-chain",  "pure-supply"),
    "probe-03-pixel-track":             ("baseline",        "supply-chain",  "pure-supply"),
    "probe-04-negative-control":        ("baseline",        "benign",        "negative-control"),
    "probe-01-no-env-read":             ("baseline",        "supply-chain",  "pure-supply"),
    "npm-handler-dispatcher":           ("dispatch",        "supply-chain",  "pure-supply"),
    "npm-multi-stage-trigger":          ("multi-stage",     "supply-chain",  "pure-supply"),
    "npm-vendored-utility-surgical-mod":("vendored-dep",    "supply-chain",  "pure-supply"),
    "npm-bin-cli-trigger":              ("deferred-cli",    "supply-chain",  "pure-supply"),
    "pip-conftest-trojan":              ("pytest-deferred", "supply-chain",  "pure-supply"),
    "pip-build-backend-chain":          ("pip-backend",     "supply-chain",  "pure-supply"),
    "pip-pth-injection":                ("pip-pth",         "supply-chain",  "pure-supply"),
    "npm-postinstall-direct":           ("baseline-direct", "supply-chain",  "pure-supply"),
    # benigns
    "benign-01-npm-express":            ("benign-npm",      "benign",        "benign-control"),
    "benign-02-pip-utility":            ("benign-pip",      "benign",        "benign-control"),
}


# Headline sweeps to include in paper table (one row per scenario; pick the
# definitive sweep per scenario).
HEADLINE_SWEEPS = {
    "probe-02-bearer-auth":             "results-final-a1",
    "npm-handler-dispatcher":           "results-variants-a1",
    "npm-multi-stage-trigger":          "results-final-a1",
    "npm-vendored-utility-surgical-mod":"results-final-a1",
    "npm-bin-cli-trigger":              "results-final-a1",
    "pip-conftest-trojan":              "results-variants-a1",
    "claudemd-audit-redirect":          "results-variants-a1",
    "readme-broken-optout":             "results-final-a1",
    "negative-framing-redirect":        "results-variants-a1",
    "inline-source-audit-comment":      "results-variants-a1",
    "fixture-as-audit-record":          "results-variants-a1",
    "agents-md-audit-redirect":         "results-v2-variants-a1",
    "package-json-audit-metadata":      "results-v2-variants-a1",
    "inline-source-no-directive":       "results-v2-variants-a1",
}


# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------

def compute_cost_breakdown(input_tokens: int, output_tokens: int,
                            cache_read_tokens: int, cache_creation_tokens: int) -> dict:
    """Compute Haiku-4.5 cost breakdown given token counts.

    Cache creation tokens are billed at the 5m-write rate (the predominant
    cache type in our setup; 1h-cache is rarer per the streaming
    transcripts).
    """
    cost_input    = input_tokens         / 1_000_000 * PRICE_INPUT
    cost_cache_w  = cache_creation_tokens/ 1_000_000 * PRICE_CACHE_5M_WRITE
    cost_cache_r  = cache_read_tokens    / 1_000_000 * PRICE_CACHE_HIT
    cost_output   = output_tokens        / 1_000_000 * PRICE_OUTPUT
    total = cost_input + cost_cache_w + cost_cache_r + cost_output
    return {
        "cost_input_usd":          round(cost_input, 6),
        "cost_cache_write_usd":    round(cost_cache_w, 6),
        "cost_cache_read_usd":     round(cost_cache_r, 6),
        "cost_output_usd":         round(cost_output, 6),
        "cost_total_usd":          round(total, 6),
        # Percentage breakdown (of total)
        "pct_input":               round(cost_input  / total * 100, 1) if total else 0,
        "pct_cache_write":         round(cost_cache_w/ total * 100, 1) if total else 0,
        "pct_cache_read":          round(cost_cache_r/ total * 100, 1) if total else 0,
        "pct_output":              round(cost_output / total * 100, 1) if total else 0,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _f(v) -> float:
    try: return float(v) if v not in ("", None) else 0.0
    except: return 0.0


def _i(v) -> int:
    try: return int(float(v)) if v not in ("", None) else 0
    except: return 0


def _pct(xs, p):
    xs = sorted(xs)
    if not xs: return 0
    k = max(0, min(len(xs)-1, int(round(p/100*(len(xs)-1)))))
    return xs[k]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    src = Path("extracted-master")
    out = Path("paper-data")
    out.mkdir(exist_ok=True)

    per_scen = _read_csv(src / "per_scenario.csv")
    per_judg = _read_csv(src / "per_judgment.csv")
    per_rep  = _read_csv(src / "per_rep.csv")

    # ---- Headline table -------------------------------------------------
    headline_rows: list[dict] = []
    for r in per_scen:
        sid = r["scenario_id"]
        if sid not in HEADLINE_SWEEPS: continue
        if HEADLINE_SWEEPS[sid] not in r["results_root"]: continue
        chan, payload, comp = CHANNEL_MAP.get(sid, ("?", "?", "?"))

        # Compute cost using actual token counts (per-rep mean × n_reps).
        n_reps = _i(r["n_reps"])
        in_tok = _f(r["judge_input_tokens_per_rep_mean"])
        out_tok = _f(r["judge_output_tokens_per_rep_mean"])
        cr_tok = _f(r["judge_cache_read_tokens_per_rep_mean"])
        cw_tok = _f(r["judge_cache_creation_tokens_per_rep_mean"])
        cost_per_rep = compute_cost_breakdown(int(in_tok), int(out_tok), int(cr_tok), int(cw_tok))

        headline_rows.append({
            "scenario_id": sid,
            "channel": chan,
            "payload_class": payload,
            "composition": comp,
            "n_reps": n_reps,
            "n_succ": _i(r["n_attack_succeeded"]),
            "n_blocked": _i(r["n_attack_blocked"]),
            "n_hung": _i(r["n_agent_hung"]),
            "pen_rate_uncond": _f(r["penetration_rate_unconditional"]),
            "pen_rate_cond": _f(r["penetration_rate_conditional"]),
            "fpr": _f(r["false_positive_rate"]),
            "agent_dur_mean_s": _f(r["agent_duration_seconds_mean"]),
            "agent_dur_median_s": _f(r["agent_duration_seconds_median"]),
            "judgments_per_rep_mean": _f(r["n_judgments_per_rep_mean"]),
            "judge_latency_total_ms_mean": _f(r["judge_total_latency_ms_per_rep_mean"]),
            "judge_latency_total_ms_median": _f(r["judge_total_latency_ms_per_rep_median"]),
            "tokens_input_per_rep": int(in_tok),
            "tokens_output_per_rep": int(out_tok),
            "tokens_cache_read_per_rep": int(cr_tok),
            "tokens_cache_write_per_rep": int(cw_tok),
            **cost_per_rep,
            "results_root": r["results_root"],
        })

    # Sort by composition then pen_rate descending for paper readability
    headline_rows.sort(key=lambda r: (r["composition"], -r["pen_rate_uncond"]))

    fieldnames = list(headline_rows[0].keys()) if headline_rows else []
    with (out / "headline_table.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in headline_rows:
            w.writerow(row)

    # ---- Per-judgment costs --------------------------------------------
    judg_rows: list[dict] = []
    for j in per_judg:
        if j.get("transcript_present") != "True": continue
        in_tok = _i(j.get("transcript_input_tokens"))
        out_tok = _i(j.get("transcript_output_tokens"))
        cr_tok = _i(j.get("transcript_cache_read_tokens"))
        cw_tok = _i(j.get("transcript_cache_creation_tokens"))
        cost = compute_cost_breakdown(in_tok, out_tok, cr_tok, cw_tok)
        judg_rows.append({
            "scenario_run_id": j["scenario_run_id"],
            "ablation": j["ablation"],
            "panel_decision": j["panel_decision"],
            "judge_decision": j["judge_decision"],
            "tool_command": j.get("tool_command",""),
            "latency_ms": _f(j.get("judge_latency_ms")),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_read_tokens": cr_tok,
            "cache_write_tokens": cw_tok,
            "num_turns": _i(j.get("transcript_num_turns")),
            "num_tool_uses": _i(j.get("transcript_tool_use_total")),
            "n_files_inspected": _i(j.get("transcript_n_files_inspected")),
            **cost,
        })
    if judg_rows:
        fieldnames = list(judg_rows[0].keys())
        with (out / "per_judgment_costs.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in judg_rows:
                w.writerow(row)

    # ---- Cost decomposition by decision --------------------------------
    decomp_by_decision = defaultdict(lambda: {
        "n": 0, "input_tok": 0, "output_tok": 0, "cache_read_tok": 0, "cache_write_tok": 0,
        "cost_total": 0.0, "cost_input": 0.0, "cost_cache_read": 0.0,
        "cost_cache_write": 0.0, "cost_output": 0.0,
        "latency_ms_list": [],
    })
    for row in judg_rows:
        d = row["judge_decision"]
        b = decomp_by_decision[d]
        b["n"] += 1
        b["input_tok"]      += row["input_tokens"]
        b["output_tok"]     += row["output_tokens"]
        b["cache_read_tok"] += row["cache_read_tokens"]
        b["cache_write_tok"]+= row["cache_write_tokens"]
        b["cost_total"]     += row["cost_total_usd"]
        b["cost_input"]     += row["cost_input_usd"]
        b["cost_cache_read"]+= row["cost_cache_read_usd"]
        b["cost_cache_write"]+= row["cost_cache_write_usd"]
        b["cost_output"]    += row["cost_output_usd"]
        b["latency_ms_list"].append(row["latency_ms"])

    decomp_rows = []
    for d, b in decomp_by_decision.items():
        n = b["n"]
        if n == 0: continue
        decomp_rows.append({
            "decision": d,
            "n_judgments": n,
            "mean_latency_ms": round(mean(b["latency_ms_list"]), 1) if b["latency_ms_list"] else 0,
            "median_latency_ms": round(median(b["latency_ms_list"]), 1) if b["latency_ms_list"] else 0,
            "mean_input_tok": round(b["input_tok"]/n),
            "mean_output_tok": round(b["output_tok"]/n),
            "mean_cache_read_tok": round(b["cache_read_tok"]/n),
            "mean_cache_write_tok": round(b["cache_write_tok"]/n),
            "mean_cost_total_usd": round(b["cost_total"]/n, 5),
            "mean_cost_input_usd": round(b["cost_input"]/n, 5),
            "mean_cost_cache_read_usd": round(b["cost_cache_read"]/n, 5),
            "mean_cost_cache_write_usd": round(b["cost_cache_write"]/n, 5),
            "mean_cost_output_usd": round(b["cost_output"]/n, 5),
        })
    if decomp_rows:
        fieldnames = list(decomp_rows[0].keys())
        with (out / "cost_decomposition.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in decomp_rows:
                w.writerow(row)

    # ---- Channel summary -----------------------------------------------
    channel_summary = defaultdict(lambda: {"n_scenarios": 0, "n_reps": 0, "n_succ": 0, "n_blocked": 0})
    for r in headline_rows:
        c = r["channel"]
        b = channel_summary[c]
        b["n_scenarios"] += 1
        b["n_reps"] += r["n_reps"]
        b["n_succ"] += r["n_succ"]
        b["n_blocked"] += r["n_blocked"]

    chan_rows = []
    for c, b in channel_summary.items():
        denom = b["n_succ"] + b["n_blocked"]
        chan_rows.append({
            "channel": c,
            "n_scenarios": b["n_scenarios"],
            "n_reps_total": b["n_reps"],
            "n_succ_total": b["n_succ"],
            "n_blocked_total": b["n_blocked"],
            "pen_rate_uncond": round(b["n_succ"]/b["n_reps"], 3) if b["n_reps"] else 0,
            "pen_rate_cond":   round(b["n_succ"]/denom, 3) if denom else 0,
        })
    chan_rows.sort(key=lambda r: -r["pen_rate_uncond"])
    if chan_rows:
        fieldnames = list(chan_rows[0].keys())
        with (out / "channel_summary.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in chan_rows:
                w.writerow(row)

    # ---- Latency distribution ------------------------------------------
    if judg_rows:
        all_lat = sorted([r["latency_ms"] for r in judg_rows if r["latency_ms"] > 0])
        latency_dist = {
            "n": len(all_lat),
            "min_ms": all_lat[0] if all_lat else 0,
            "p25_ms": _pct(all_lat, 25),
            "median_ms": _pct(all_lat, 50),
            "p75_ms": _pct(all_lat, 75),
            "p90_ms": _pct(all_lat, 90),
            "max_ms": all_lat[-1] if all_lat else 0,
            "mean_ms": round(mean(all_lat), 1) if all_lat else 0,
            "stdev_ms": round(stdev(all_lat), 1) if len(all_lat) >= 2 else 0,
        }
        with (out / "latency_distribution.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(latency_dist.keys()))
            w.writeheader()
            w.writerow(latency_dist)

    # ---- Top-line summary JSON -----------------------------------------
    summary = {
        "n_scenarios_in_paper": len(headline_rows),
        "n_judgments_total": len(judg_rows),
        "channel_dichotomy": {
            "metadata_channels_pen_rate": _pct_for_channels(headline_rows, ["claude-md", "agents-md", "pkg-metadata", "json-fixture"]),
            "audit_channels_pen_rate": _pct_for_channels(headline_rows, ["inline-comment", "inline-comment-directive"]),
            "pure_supply_pen_rate": _pct_for_channels(headline_rows, ["baseline", "dispatch", "multi-stage", "vendored-dep", "deferred-cli", "pytest-deferred"]),
        },
        "haiku45_pricing_per_M_tokens": {
            "input": PRICE_INPUT,
            "cache_5m_write": PRICE_CACHE_5M_WRITE,
            "cache_1h_write": PRICE_CACHE_1H_WRITE,
            "cache_hit": PRICE_CACHE_HIT,
            "output": PRICE_OUTPUT,
        },
    }
    with (out / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nWrote outputs to {out}/:")
    for f in sorted(out.iterdir()):
        print(f"  {f.name}")
    print()
    print(f"Headline scenarios: {len(headline_rows)}")
    print(f"Per-judgment rows:  {len(judg_rows)}")


def _pct_for_channels(rows: list[dict], channels: list[str]) -> dict:
    """Aggregate pen rate across rows whose channel matches."""
    matched = [r for r in rows if r["channel"] in channels]
    if not matched: return {"n_reps": 0, "n_succ": 0, "pen": 0.0}
    n_reps = sum(r["n_reps"] for r in matched)
    n_succ = sum(r["n_succ"] for r in matched)
    return {
        "n_scenarios": len(matched),
        "n_reps": n_reps,
        "n_succ": n_succ,
        "pen_uncond": round(n_succ/n_reps, 3) if n_reps else 0,
    }


if __name__ == "__main__":
    main()
