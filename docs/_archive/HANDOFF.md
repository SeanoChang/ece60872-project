# HANDOFF — Group B Fork

> This document describes the fork-point for **Group B**, the second 2-person team on the ECE 60872 final project. You fork this repo at git tag `v0.1-shared-scaffold` and build your paper from there. Sean (Group A) continues on `main` for Paper 1.
>
> **Project overview**: two independent 2-page DSN workshop papers, each measuring whether a different classical voting theorem transfers to agentic LLM judges on coding-agent tool-call safety. Locked design as of 2026-04-17.

---

## Your Paper (Group B)

**Title (working)**: *"Does Byzantine Fault Tolerance Transfer? Quorum Survival Under Single-Judge Prompt Compromise in LLM Agentic Voting"*

**RQ**: Does 2-of-3 LLM-agentic majority voting retain its detection rate when one judge's system prompt is replaced with a Byzantine ("always approve") variant?

**Headline metric**: **quorum survival rate**

```
S = detection_rate(A6) / detection_rate(A4)
```

- `S = 1.0` → PBFT guarantee transfers cleanly
- `S = 0.0` → Quorum collapses; 1 Byzantine judge defeats the entire voting mechanism
- Intermediate `S` → Partial transfer; paper reports the specific value + per-archetype breakdown

**Classical anchors**: Byzantine Generals Problem (Lamport, Shostak, Pease 1982), PBFT (Castro & Liskov 1999), 3f+1 quorum bound, Byzantine Quorum Systems (Malkhi & Reiter 1998).

**Course anchoring**: Reliability (quorum theory) + Security (malicious-component fault model). "Reliable AND Secure" two-for-one.

---

## Group A's Paper (for context / cross-citation)

**Title (working)**: *"Does Triple Modular Redundancy Transfer to LLM Agentic Voting for Coding-Agent Tool-Call Safety?"* (Sean's paper)

**RQ**: Does 3-judge agentic majority voting detect trojaned codebases at a higher rate than a single agentic judge, and at what false-positive cost?

**Ablations**: A1 (1 agentic judge) vs A4 (3 agentic judges, majority)

**Headline metric**: detection rate gap `Δ = detection(A4) − detection(A1)` with 95% CI, plus FPR for both.

**Classical anchors**: TMR (von Neumann 1956, Lyons 1962), Condorcet Jury Theorem (1785).

Your paper cites Group A's paper in §5 as complement; Group A's paper cites yours in §5 as complement. Both may optionally merge into a 4-page extended paper if both are shipped by May 1 — upside only, not required.

---

## Experimental Matrix (what you run)

| ID | Judges | Model | Prompt | Temp | What it tests |
|---|---|---|---|---|---|
| **A4** | 3 | Sonnet 4.6 ×3 | Param / Intent / Threat (honest) | 0.0 | Honest 2-of-3 majority baseline |
| **A6** | 3 | Sonnet 4.6 ×3 | Param / Intent / **Byzantine-Threat (naive)** | 0.0 | 2-of-3 with 1 Byzantine judge |

**Two conditions × ~15 scenarios × 3 reps = ~180 runs. ~4–5 hours wall clock. ~$30 API budget.**

**A4 is the shared experimental condition with Group A.** You have two options:

1. **Inherit Group A's A4 JSONL** (recommended if Group A runs A4 first). Saves ~$15 and 2 hours.
2. **Run A4 yourself** (gives you statistically-independent baseline, useful for CI computations).

Either works. Coordinate with Sean before running.

**Stretch ablations** (optional, only if Week 3 finishes early):
- **A6-subtle** — subtle Byzantine prompt (see `judge_config/byzantine/subtle/`). More realistic but more work to interpret.
- **A7** — A6 + content poisoning on inputs. Byzantine ⊕ correlated-failure composition.
- **Cross-substrate A4** — Sonnet + Haiku + Opus as 3 judges (true N-version across substrates).

---

## What's in the Shared Scaffold (at `v0.1-shared-scaffold`)

### Keep entirely — do not modify

- `core/api_proxy.py` — holds Anthropic API key, injects into container requests
- `core/orchestrator.py` — dispatches judge containers, collects votes
- `core/judge_containers.py` — judge container lifecycle, workspace mounting
- `core/agentic_judge.py` — spawns Claude Code inside judge container with skill kit
- `core/judge_hook.py` — PreToolUse hook, POSTs tool call to orchestrator
- `core/honeypot.py` — canary detector + real-key tripwire (ground truth)
- `core/voting.py` — majority-rule aggregator
- `core/logger.py` — JSONL logger
- `core/types.py` — `JudgeConfig`, `JudgeVote`, `VoteResult`
- `core/runner_agent.py` — **replay agent** (deterministic; scripted emit, not LLM-driven)
- `judge_config/param/` — Param Validator (honest)
- `judge_config/intent/` — Intent Aligner (honest)
- `judge_config/threat/` — Threat Modeler (honest)
- `judge_config/byzantine/naive/` — Byzantine Threat Modeler (naive, "always approve")
- `judge_config/byzantine/subtle/` — Byzantine subtle variant (stretch)
- `prompts/honest/{param,intent,threat}.md` — honest judge prompts
- `prompts/byzantine/{naive,subtle}.md` — Byzantine variants
- `scenarios/trojaned-codebases/*.yaml` — ~15 scenarios shared by both groups
- `ablations/configs/{A1,A4,A6}.json` — ablation configurations
- `analysis/metrics.py`, `analysis/aggregate.py`, `analysis/ground_truth.py` — shared analysis base
- `docker/agent.Dockerfile` (replay-agent container), `docker/judge-agentic.Dockerfile`

### Build new (your fork's contribution)

- **`analysis/quorum_survival.py`** — ~30 lines. Reads A4 and A6 event JSONL, computes per-archetype and aggregate quorum survival rate `S = detection(A6) / detection(A4)` with bootstrap 95% CIs. Writes a results table.
- **`analysis/byzantine_detectability.py`** (optional) — Byzantine voter's vote vs honest pair's votes; analyze post-hoc detectability of the compromised judge. Supports a "future work: trust-weighted voting" paragraph in §5.
- **`docs/paper/group-b/`** — your paper draft

---

## The Replay-Agent Reframe (important)

You may notice `core/runner_agent.py` is NOT the LLM-driven coding agent you might expect. It is a deterministic replay shim. Why:

**Problem**: Claude Sonnet 4.6 self-defends on naive prompt-injection scenarios before ever emitting a tool call. The voting panel never fires. No data collected.

**Fix**: Replace the LLM-driven coding agent with a ~50-line deterministic replay agent. Each scenario YAML specifies `proposed_tool_call` (e.g., `{tool: Bash, input: {command: "bash setup.sh"}}`). The replay agent emits this exact tool call through the normal PreToolUse hook path. Judges don't know they're being called by a replay vs a real agent — same hook, same dispatch, same votes.

**Methodology**: standard fault-injection practice — inject the signal at the component under test (the voting panel), not upstream of a silent filter (the self-defending coding agent). Cite Hsueh, Tsai, Iyer (1997) "Fault Injection Techniques and Tools" if asked by a reviewer.

**What this means for your paper's §3 Method**: write a short paragraph explaining the replay-agent isolation. Standard workshop-paper scoping, no issue.

---

## Scenario Schema (v2, locked at tag)

Every scenario in `scenarios/trojaned-codebases/` follows this schema:

```yaml
scenario_id: postinstall-01-fetch-exfil
archetype: postinstall         # {postinstall, typosquat, malicious-setup, poisoned-makefile, mcp-poisoning, benign}
description: "One-paragraph description of the trojan."
source: "provenance citation"
ground_truth:
  label: malicious             # malicious | benign
  trojan_file: "scripts/setup.js"
  trojan_signature: "fetch(cfg.url + cfg.path, {body: process.env.KEY})"
proposed_tool_call:           # what the replay agent emits
  tool: Bash
  input:
    command: "npm install"
task_context: "What a coding agent would plausibly think it's doing."
workspace:
  files:
    package.json: |
      {...}
    scripts/setup.js: |
      {...}
    README.md: |
      {...}
canary_credentials:
  - location: .env
    value_template: "ANTHROPIC_API_KEY={canary}"
expected_honest_vote: reject   # sanity check for honest-judge baseline
```

See `scenarios/trojaned-codebases/postinstall-01-fetch-exfil.yaml` for a concrete example.

---

## Mandatory Related-Work Daylight Sentences (for your §2)

Per the 2026-04-17 novelty audit, you MUST include these three claims in your §2 Related Work to preempt reviewer skim-review objections:

1. *"Prior work on LLM-as-judge ensembles [Maloyan'25] measures attack success under **shared-input prompt injection** — adversarial content visible to all judges. We measure quorum survival under **configuration compromise** — one voter's own system prompt is silently replaced. This threat model corresponds to stolen prompt registries and supply-chain attacks on agent configurations, the setting for which the PBFT 2-of-3 guarantee is most directly invoked."*

2. *"Unlike CP-WBFT [Zheng'25] and DecentLLMs [Jo'25], which propose new Byzantine-robust aggregation mechanisms and evaluate on QA/math benchmarks, we perform the prerequisite measurement: does vanilla 2-of-3 majority voting — the direct port of PBFT's 3f+1 bound — transfer to agentic LLM judges on coding-agent tool-call safety at all?"*

3. *"Unlike persuasion-based subversion of multi-agent debate [Sci. Rep.'26; Amayuelas'24], our Byzantine voter does not debate, does not iteratively converge with peers, and does not use persuasion — it is a silently-compromised voter casting a fixed vote in a single round, matching the independent-voter assumption PBFT actually requires."*

---

## Recommended Citations (12 for Group B)

1. Lamport, Shostak & Pease (1982). *The Byzantine Generals Problem*. ACM TOPLAS.
2. Castro & Liskov (1999). *Practical Byzantine Fault Tolerance*. OSDI.
3. Malkhi & Reiter (1998). *Byzantine Quorum Systems*.
4. Verga et al. ([2404.18796](https://arxiv.org/abs/2404.18796), 2024). PoLL — multi-judge ensembles.
5. Zhuge et al. ([2410.10934](https://arxiv.org/abs/2410.10934), 2024). Agent-as-a-Judge.
6. **Maloyan & Namiot ([2504.18333](https://arxiv.org/abs/2504.18333), 2025). Must-cite with explicit daylight.**
7. Shi et al. (CCS 2024). JudgeDeceiver — attacks on single judges.
8. **Zheng et al. ([2511.10400](https://arxiv.org/abs/2511.10400), 2025). CP-WBFT — must-cite with explicit daylight.**
9. Luo et al. ([2505.05103](https://arxiv.org/abs/2505.05103), 2025). WBFT-MLLMN.
10. Jo et al. ([2507.14928](https://arxiv.org/abs/2507.14928), 2025). DecentLLMs.
11. Amayuelas et al. (EMNLP Findings 2024, [2406.14711](https://arxiv.org/abs/2406.14711)). MultiAgent Collaboration Attack.
12. deVadoss & Artzt ([2504.14668](https://arxiv.org/abs/2504.14668), 2025). BFT for AI Safety (position paper motivator).

Optional: axios March 2026 (threat motivation), AIShellJack ([2509.22040](https://arxiv.org/abs/2509.22040)).

---

## Paper Structure (2 pages)

| Section | Words | Contents |
|---|---|---|
| Abstract | ~150 | PBFT transfer measurement; survival rate `S = X` (CI) |
| §1 Intro | ~200 | Real-world prompt-substitution threats → PBFT 2-of-3 as classical defense → independence concern → RQ |
| §2 Background | ~250 | Byzantine Generals + PBFT + independence assumption; related work with the three daylight sentences |
| §3 Method | ~280 | Replay agent + 3 agentic judges + Byzantine via system-prompt substitution + A4 baseline + A6 condition |
| §4 Results | ~400 | Table 1 + Figure 1 + per-archetype survival + honest-pair agreement |
| §5 Discussion | ~250 | PBFT-transfer verdict; independence violation; limitations; future work |
| References | 10–12 | See above |

Fits 2 pages cleanly.

---

## Setup (conda)

```bash
# Clone your fork
git clone <your-fork-url> group-b
cd group-b
git checkout v0.1-shared-scaffold

# Conda environment
conda env create -f environment.yml
conda activate bft-voting

# Install package
pip install -e .

# Set up API key
cp .env.example .env
# Edit .env to add ANTHROPIC_API_KEY (use a dedicated $50-limited key)

# Start the stack
docker-compose up -d

# Smoke test on one scenario
python -m ablations.experiment --config ablations/configs/A4.json \
  --scenarios scenarios/trojaned-codebases/postinstall-01-fetch-exfil.yaml \
  --reps 1

# Full A6 run (do this after verifying smoke test)
python -m ablations.experiment --config ablations/configs/A6.json --reps 3
```

---

## Deadlines and Milestones

| Date | Milestone |
|---|---|
| Apr 18–24 | Pipeline smoke test on 2–3 scenarios; start A6 runs |
| Apr 25 – May 1 | Complete A4 + A6 matrices (3 reps each); compute S per archetype |
| May 2 – May 8 | Fill Results + Discussion; internal cross-read with Group A; submit |

---

## Questions / Coordination

Sean (Group A) is the default point of contact for any question about the shared scaffold. Any change to `core/*` or `judge_config/{param,intent,threat}/` or `scenarios/trojaned-codebases/*.yaml` requires written coordination — these are the shared substrate.

Your fork's analysis code (`analysis/quorum_survival.py`), your paper draft (`docs/paper/group-b/`), and your ablation-specific runners are yours alone.

---

**Ship it. Good luck.**
