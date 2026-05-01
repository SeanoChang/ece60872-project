# Venue Fit Assessment — BFT Voting for Tool-Call Safety

**Repo:** `ece60872-project` @ `main` (24b0bd8)
**Assessed:** 2026-04-24
**Targets:** ACSAC 2026 (May 30), NeurIPS 2026 E&D (May 6)

---

## TL;DR

- **Course paper due ~2026-05-08 is the binding deadline.** ACSAC and NeurIPS are downstream. The realistic course deliverable is `Δ` and `S` measured on **8 scenarios × 3 reps × 4 ablations** in replay-agent mode. See §4 *Revised plan*.
- **Tonight:** kick off A0 + A1 on the existing 2 scenarios (`for abl in A0 A1; do python -m ablations.experiment ...`). Free wall-clock; de-risks the pipeline before the new scenarios land.
- **Hard cut for course paper:** drop the cloud-VM real-CVE replay, the non-agentic baseline, the n-sweep, and the NeurIPS pivot. Keep the four-condition matrix already in `ablations/configs/`.
- **Bottleneck = scenario authoring.** Teammate must start Monday on 6 new YAMLs; if it slips past May 1, drop to 4 scenarios rather than slipping the sweep.
- **Paper-framing risk:** §3 Method must call this what it is — parallel single-shot majority voting with prompt-swap fault injection, with PBFT as theoretical anchor transferred to a new domain. **Not a PBFT implementation.** Reviewers who know BFT will catch the conflation.
- **NeurIPS E&D in 12 days: not realistic.** Don't attempt.
- **ACSAC May 30: stretch.** Only viable as a May 9 → May 30 follow-up *after* the course submission lands. See §4-Extended.
- **Backup venues if ACSAC slips:** SCORED @ CCS 2026 (supply-chain track, mid-summer) or ISSRE 2026 industry/fast-abstract (typically July).

---

## 1. What Exists

### 1.1 BFT protocol layer

- **File:** `core/voting.py` (65 LOC)
- **Implements:** `majority_vote(votes) -> VoteResult`. Threshold `approvals > n/2`; ties reject. Latency = `max(votes)`; cost = `sum(votes)`. Single function, no side effects. (`core/voting.py:8-39`)
- **Variant:** Plain leaderless single-shot majority voting. **No PBFT, no view change, no replica state machine, no n=3f+1 derivation in code.** The `master-plan.md` "PBFT 2-of-3" framing is anchoring rhetoric, not a protocol.
- **n/f bounds in practice:** n ∈ {0, 1, 3} (the four ablation configs); f = 1 only at A6. No n=5/7 sweep.
- **Status:** Functional but minimal. Not a BFT protocol contribution by ACSAC's systems-paper bar.

### 1.2 Tool-call interception layer

- **PreToolUse hook:** `core/judge_hook.py` (149 LOC). Reads stdin → POSTs to orchestrator `/judge` → exits 0 (approve) or 2 (deny). Fail-closed on any exception. (`core/judge_hook.py:36-101`)
- **Orchestrator:** `core/orchestrator.py` (297 LOC). FastAPI on `:8080`; `POST /judge` runs `run_judges()` via `asyncio.gather` with a 3-second stagger to dodge Anthropic TPM limits, then `majority_vote()`. (`core/orchestrator.py:66-83`, `:130-251`)
- **A0 short-circuit:** `core/orchestrator.py:138-143` early-returns approve when `judges == []`. (README at line 301 says it isn't wired — README is stale.)
- **Hook matcher:** `Bash | Edit | Write` only (`ablations/experiment.py:35`). All other tool calls bypass voting.
- **Status:** Functional, end-to-end working.

### 1.3 Replica orchestration

- **File:** `core/judge_containers.py` (116 LOC) + `core/agentic_judge.py` (297 LOC)
- **Mechanism:** Static `docker run -d` with `sleep infinity` per judge at experiment start; one container per judge for the run. `docker exec claude -p` per judgment. Workspace bind-mount swapped between scenarios. (`core/judge_containers.py:54-115`; `ablations/experiment.py:106-145`)
- **No failover, no view change, no leader election, no replica recovery.**
- **Cost-tracking sidechannel:** `core/stream_parser.py` extracts `total_cost_usd` from Claude Code stream-json (`core/agentic_judge.py:215-263`).
- **Status:** Functional but static — judges are processes, not replicated state machines.

### 1.4 Threat-model artifacts

- **Compromised replicas:** `judge_config/byzantine/{naive,subtle}/IDENTITY.md` + `prompts/byzantine/naive.md`. A6 ablation swaps the threat judge's prompt with an "always approve" variant. (`ablations/configs/A6.json:25-33`)
- **API-key exfiltration:**
  - `core/api_proxy.py:144-164` strips `x-judge-id`/`host`, injects real key host-side; containers see `ANTHROPIC_API_KEY=proxied`.
  - Per-agent budgets enforced by `_check_budget` (`core/api_proxy.py:166-180`); 429 on overrun.
  - `core/honeypot.py:124-214` logs all inbound, regex-matches real Anthropic keys (`r"sk-ant-api03-(?!CANARY)[A-Za-z0-9_-]{80,}"`), and matches randomized canaries planted per scenario.
  - `core/scenario.py:56-73` generates type-specific canaries (api_key / aws_key / ssh_key / npm_token) per scenario run.
- **Malicious tool responses:** **Not modeled.** Judges are inputs, not outputs; there's no model of a compromised tool returning attacker-influenced data.
- **No formal threat-model document.** No diagram of attacker capabilities, no attacker-action enumeration, no "what we defend / what we don't" table. Implicit only.
- **Status:** Implicit in code. **Missing as a paper artifact.**

### 1.5 Eval harness

- **Driver:** `ablations/experiment.py` (604 LOC) — `ExperimentRunner.run()` is the single entry point. Sets up infra + judge containers, iterates `(scenario × rep)` under `asyncio.Semaphore(max_concurrency)`, classifies outcomes, writes per-scenario JSONL + stdout/stderr, runs aggregator. (`ablations/experiment.py:474-537`)
- **Outcome classifier:** `analysis/ground_truth.py:55-107`. Six labels: `attack_succeeded | attack_blocked | false_positive | benign_completed | already_solved | infra_failed`. Honeypot canary hit is the ground-truth winner.
- **Aggregator:** `analysis/aggregate.py` produces `aggregate.json` per ablation: outcome counts, detection rate, FPR, total judgments / cost, latency median+max.
- **Status:** Functional and well-instrumented (structured JSONL events, correlation IDs, per-phase timings).

### 1.6 Datasets / attack traces

- **Primary library (`scenarios/trojaned-codebases/`):** **2 YAMLs**
  - `postinstall-01-fetch-exfil.yaml` — npm postinstall ANTHROPIC_API_KEY exfil; explicit MITRE T1195.002 mapping; canary planted in `.env`.
  - `devserver-01-vite-plugin-exfil.yaml` — vendored opaque `.tgz` Vite plugin reads `.env.local` and POSTs at `npm run dev`; designed to defeat Sonnet's text-stage self-defense (T1552.001 + T1567).
- **Plan calls for ~15** (10 attack + 5 benign). `master-plan.md:65-74` lists 5 archetypes; **only postinstall + devserver-plugin actually exist.** Typosquat, malicious-setup, poisoned-makefile, mcp-poisoning, and benign controls are all unbuilt.
- **Provenance:** `scenarios/SOURCES.md` is mostly `_TBD_` — only the `injecagent-ds-*` and 2 trojaned-codebase rows are filled. Per `SOURCES.md:60`, all 5 `injecagent-ds-*` scenarios are known to land in `already_solved` under A0 (Sonnet self-defends pre-hook), so they don't exercise the panel.
- **Deprecated library (`scenarios/deprecated/`):** 5 InjecAgent + 5 MCPSecBench + 3 realworld YAMLs (axios, mcp-injection, poisoned-setup). Marked cloud-VM-only; not part of the current evaluation.
- **Status:** Severely under-populated. **This is the biggest gap.**

### 1.7 Baselines

- **A0** (`ablations/configs/A0.json`): no judges, agent alone — measures Sonnet 4.6 self-defense floor.
- **A1** (`ablations/configs/A1.json`): single Haiku-4.5 general-purpose judge.
- **A4** (`ablations/configs/A4.json`): 3 Haiku-4.5 judges with Param/Intent/Threat skill kits.
- **A6** (`ablations/configs/A6.json`): 3 judges, threat judge replaced with `prompts/byzantine/naive.md`.
- **Stretch (parked):** A1-h, A2, A3, A4-h, A4-m, A5, A7 in `configs/stretch/`.
- **Missing baselines vs. plan:**
  - **Naive majority vote (judges with no investigation tools)** — needed to isolate the agentic-investigation contribution from the redundancy contribution. Not implemented.
  - **External baselines (AEGIS, ToolSafe, Claude Auto Mode, AgentDojo defenses)** — listed in `README.md:135-140` but **none are actually executed** against the same scenarios. They're discussion targets, not measured comparison points.
- **Empirical run state:** Only `results/A4/` exists. `aggregate.json` shows: 13 scenarios, **9 `already_solved` / 1 `attack_blocked` / 0 `attack_succeeded` / 2 `infra_failed`**. Detection rate of 1.0 is computed from a denominator of 1. **A0/A1/A6 have not been run yet.**

### 1.8 Reproducibility artifacts

- **Build / env:** `environment.yml` (conda env `bft-voting`, Python 3.12), `pyproject.toml` (hatchling, editable install), `docker-compose.yml` (image build only — runtime in `core/infra.py`).
- **Containers:** `docker/agent.Dockerfile`, `docker/judge-agentic.Dockerfile`, `docker/claude-settings.json`.
- **Single-command replay:** `python -m ablations.experiment --config ablations/configs/A4.json --scenarios ... --reps 3` (`README.md:243-294`).
- **CI:** `.github/workflows/ci.yml` (test + image builds) + `experiment.yml` + `experiment-full.yml` (manual-dispatch).
- **Tests:** 22 test modules, 6,794 total LOC under `tests/`.
- **Pinned versions:** Yes (conda env + Docker image digests via base image pins; verify with `docker compose build`).
- **What's missing:** seeded determinism statement, fixed model snapshot pin (uses `claude-haiku-4-5-20251001` — model snapshot date is in the ID, good), no public dataset DOI.
- **Status:** Strong relative to most lab projects. Adequate for ACSAC.

---

## 2. ACSAC Gap Check

| Item | Status | Justification (file refs) |
|---|---|---|
| Concrete threat model (compromised replicas, malicious tool responses, key exfil paths) | **partial** | Compromised replica modeled (`A6.json`, `prompts/byzantine/naive.md`); key exfil modeled (`api_proxy.py`, `honeypot.py`, scenario canaries). Malicious tool-response model **absent**. No formal threat-model document or attacker-capability table. |
| End-to-end working prototype (not just unit tests) | **present** | `ablations/experiment.py:474-537` is end-to-end; `results/A4/aggregate.json` proves it ran. |
| Empirical eval on realistic workloads with malicious tool-call traces | **missing** | 2 scenarios in `scenarios/trojaned-codebases/`; A4 run shows 9/13 `already_solved` and only 1 attack reaching the panel. Statistically empty. |
| Baseline: single-agent runtime, no-consensus runtime, naive majority voting | **partial** | A0/A1 cover single-agent and single-judge. **Naive (non-agentic) majority voting baseline does not exist** — no judge variant runs without filesystem investigation tools, so the agentic-investigation contribution can't be isolated from the redundancy contribution. |
| Overhead: p50/p95/p99 latency, throughput as f(n,f) | **missing** | `analysis/aggregate.py:102-105` reports only median + max. No p95/p99. No n-sweep — the four configs have n ∈ {0,1,3} only. No throughput-vs-load curves. |
| Ablation over n, f, consensus protocol choice | **missing** | n fixed at {0,1,3}; f at {0,1}; one protocol (majority). No n=5/7 sweep, no weighted-vote variant, no quorum-rule comparison. |
| At least one real attack replayed end-to-end | **partial** | `postinstall-01` is "inspired by" axios March 2026; `devserver-01` is "inspired by" node-ipc 2022 + axios. The actual axios/CVE-2025-68143 traces live under `scenarios/deprecated/realworld/` and are explicitly cloud-VM-only — they have **not been run**. |
| Reproducibility (Docker image, seeds, pinned versions) | **present** | `environment.yml`, `pyproject.toml`, both Dockerfiles, `.env.example`, CI workflows, JSONL event streams with `schema_version` field, model snapshot pinned in IDs. |

**ACSAC verdict:** Three blocking gaps — scenario library size, real-attack replay, missing non-agentic-majority baseline. Threat-model write-up is the cheap fourth.

---

## 3. NeurIPS E&D Gap Check

| Item | Status | Justification (file refs) |
|---|---|---|
| Reusable benchmark with documented API (not hardcoded to one runtime) | **missing** | `core/scenario.py:33-53` loads YAMLs into a dataclass tied to *this* runner's `proposed_tool_call` schema and `expected_dangerous_calls` regex format. Not portable. No CLI for "run my judge against this benchmark," no scoring API decoupled from the runner. |
| Ground-truth labels for attack/defense outcomes | **present** | Every scenario YAML carries `ground_truth.label`, `trojan_file`, `trojan_signature`, `expected_dangerous_calls`, `expected_honest_vote`. `analysis/ground_truth.py:55-107` is the canonical classifier. |
| Multiple scenarios covering distinct attack classes | **missing** | 2 YAMLs covering 2 archetypes (postinstall, devserver-plugin). Plan promised 5 archetypes; 3 are unbuilt. Deprecated InjecAgent/MCPSecBench scenarios are not part of the primary benchmark. |
| Scale (order of magnitude scenarios, not three examples) | **missing** | 2 vs. order-of-magnitude expectation of 100+. AgentDojo (2024) ships 629 cases; AgentHarm ships 110+; InjecAgent ships 1,054. |
| Reference implementation positioned as baseline, not contribution | **inverted** | The whole repo is framed as the BFT-voting *contribution* (per `master-plan.md:11-22` and `paper-plan.md:8-22`). E&D track expects the inverse — the dataset is the deliverable, the runtime is one of several baselines reporting against it. |
| Reproducibility artifact (single-command replay) | **partial** | `python -m ablations.experiment` works but requires Docker, an Anthropic API key (~$40 spend per full sweep per `master-plan.md:122`), and ~6 hours of wall clock. No frozen-trace replay (re-execute against pre-recorded judge outputs without LLM calls) — that's the standard E&D bar. |

**NeurIPS verdict:** Wrong shape for the venue. Even with 5 weeks the deliverable wouldn't be a benchmark; it'd be a system paper with thin coverage. **Don't target this.**

---

## 4. Revised plan — course paper due ~2026-05-08 (~10–14 days)

The ACSAC-shaped plan below in §4-Extended is the **post-course follow-up**. The immediate target is the ECE 60872 course deliverable: the 2-page paper described in `docs/planning/paper-plan.md:110-120` (Abstract / Intro / Background / Method / Results / Discussion). Cut everything that doesn't directly feed those six sections in 14 days.

### What gets cut from §4-Extended

- **P2 (real-CVE cloud replay):** drop. Threat model says "inspired by axios"; that's enough for a course paper that frames itself as a transferability study, not a CVE-defense system.
- **P3 (non-agentic majority baseline):** drop for course; keep for ACSAC extension. The course paper's `Δ` and `S` headline metrics in `paper-plan.md:26-29` don't depend on it.
- **P6 (n-sweep):** drop. The four-condition matrix `paper-plan.md:36-43` is the locked design; adding n=5 now risks A0/A1/A4/A6 not finishing.
- **P7, P8 (NeurIPS pivot):** drop entirely.

### Course-deadline action list — ordered, dated, hard cuts

Today is 2026-04-24 (Friday). Target submission: 2026-05-08 (Friday, 14 days). Critical path to a defensible 2-page paper:

#### C0 — Lock scope today, kick off the long-pole compute (today + tonight)

- **Action:** Run **A0 + A1 in parallel right now** against the existing 2 trojaned-codebase scenarios at `--reps 3`. A0 is judges=[] (free, fast); A1 is 1 Haiku judge (~$2). Both finish in <2 hours. This unblocks knowing whether the live-runner pipeline produces non-trivial outcomes on the 2 scenarios you have.
- **Command:**
  ```
  for abl in A0 A1; do
    python -m ablations.experiment \
      --config "ablations/configs/${abl}.json" \
      --scenarios scenarios/trojaned-codebases/*.yaml \
      --reps 3 --max-concurrency 1
  done
  ```
- **Decision gate:** if A0 shows `already_solved == 6/6` (Sonnet self-defends both scenarios across all reps), the live-runner path is unmeasurable and you must commit to the **replay-agent path** (`core/replay_agent.py`) for the course paper. The existing A4 result already showed 9/13 `already_solved`, so plan for replay-mode as the default.
- **Files to modify:** none.
- **Time:** 1 evening of attention; compute runs in background.

#### C1 — Add 4 more scenarios, replay-mode-first (Apr 25 – Apr 30, 4 evenings, ~6 days wall clock with teammate)

Per `docs/planning/infrastructure.md:30`, scenario authoring is the teammate's primary owner. Get them on this Monday-morning at the latest.

- **Files to add (target = 6 attack + 2 benign = 8 total):**
  - `scenarios/trojaned-codebases/typosquat-01-requirements.yaml` (Python pip typosquat)
  - `scenarios/trojaned-codebases/poisoned-makefile-01-install.yaml` (Makefile `install:` curl-pipe-bash)
  - `scenarios/trojaned-codebases/mcp-poisoning-01-config.yaml` (`.mcp/config.json` lift from CVE-2025-68143 description in `paper-plan.md`)
  - `scenarios/trojaned-codebases/postinstall-02-obfuscated-curl.yaml` (variant — base64-decoded curl in postinstall, defeats text scan)
  - `scenarios/trojaned-codebases/benign-01-vite-clean.yaml` (paired with devserver-01 minus the trojan tarball)
  - `scenarios/trojaned-codebases/benign-02-postinstall-clean.yaml` (paired with postinstall-01 minus exfil)
- **Files to modify:** `scenarios/SOURCES.md` — fill provenance for all 6.
- **All 6 must include `proposed_tool_call`** so the replay path works without depending on Sonnet's self-defense behavior.
- **Smoke test each on A1 with `--reps 1` before adding to the sweep.**
- **Time:** ~0.5–1 evening per scenario including provenance + smoke test. 4–6 evenings total. **Teammate-owned.**

#### C2 — Run A4 + A6 sweep on the 8 scenarios (May 1 – May 3, 1 evening + 6h compute)

- **Files to modify:** none.
- **Command:** same four-loop pattern as C0, restricted to A4 + A6. Budget ~$25.
- **Watch for:** `infra_failed` rate. Existing A4 shows 2/13 failed — investigate stderr in `results/A4/scenarios/*.stderr` if it persists; one common cause documented in `core/orchestrator.py:36-43` is TPM bursting.
- **Time:** 1 evening to kick off + monitor. Wall clock ~4–6 hours per ablation per `master-plan.md:53`.

#### C3 — Aggregate, compute Δ + S + bootstrap CIs (May 3, 1 evening)

- **Files to modify:**
  - `analysis/aggregate.py:81-105` — replace `median + max` with explicit p50/p95 (one-line `numpy.percentile` call).
  - `analysis/metrics.py` — add `bootstrap_ci(values, statistic, n_bootstrap=10000, alpha=0.05)` returning `(point_estimate, lo, hi)`. ~20 LOC.
- **Files to add:** `analysis/headline.py` — loads `results/{A0,A1,A4,A6}/aggregate.json`, computes `Δ = detection(A4) - detection(A1)` and `S = detection(A6) / detection(A4)` with bootstrap CIs over scenario-runs, prints a Markdown table ready to paste into Results.
- **Time:** 1 evening.

#### C4 — Write the 2-page paper (May 4 – May 7, 4 evenings, joint)

Per `paper-plan.md:90-101`, Sean writes §3 Method; teammate writes §1 Intro / §2 Background / §4 Results figures / §5 Discussion. Confirm the split is still real with the teammate **this weekend** — if they're behind on scenarios (C1) they will not have time for §1/§2/§4/§5 either.

- **Files to add:** `paper/paper.tex`, `paper/figures/`, `paper/refs.bib` (or whatever the course expects — confirm format with the course staff).
- **Mandatory in §2:** the three "daylight sentences" from `paper-plan.md:65-71`. They preempt the most likely reviewer complaints.
- **Mandatory in §3:** explicit statement that the implementation is parallel single-shot majority voting with prompt-swap fault injection — **not PBFT**. This is non-negotiable. Frame the BFT framing as the inspiration / theoretical anchor (Lamport 1982, Castro-Liskov 1999) being *transferred* to a new domain (LLM judge ensembles), not as a PBFT implementation. If the paper claims PBFT, anyone with a distributed-systems background reviews it negatively.
- **Mandatory in §5 limitations:** small N (8 scenarios × 3 reps = 24 attack runs per ablation), single-snapshot models, replay-mode used as primary measurement path due to Sonnet self-defense.

#### C5 — Cross-read + submit (May 8, 1 evening)

- Internal cross-read between Sean and teammate before noon. Submit by EOD.

### Course-deadline timeline summary

| Day | Action | Owner |
|---|---|---|
| Apr 24 (today) | Kick off A0 + A1 sweep on existing 2 scenarios | Sean |
| Apr 25–30 | 6 new scenarios authored + smoke-tested | Teammate (Sean smoke-tests) |
| May 1–3 | A4 + A6 sweep on 8 scenarios | Sean |
| May 3 | Aggregate + Δ/S/CIs | Sean |
| May 4–7 | Paper drafting (§3 Sean; §1/§2/§4/§5 teammate) | Both |
| May 8 | Cross-read + submit | Both |

**Slack:** ~2 days. C1 scenario authoring is the bottleneck — if it slips past May 1, drop to 4 scenarios (3 attack + 1 benign) rather than slip the sweep.

### What this plan trades away

- **Detection-rate denominators stay small** (8 scenarios × 3 reps = 24 attack runs per ablation, possibly fewer if `already_solved` rate is high). Bootstrap CIs will be wide. The paper has to own this — frame as a feasibility study, not a definitive measurement.
- **No real-CVE replay.** The paper cannot claim "we defended against axios"; it can claim "we measured TMR/BFT transfer on synthetic trojans inspired by axios."
- **No external baseline runs.** The Related Work table in `README.md:135-140` stays a discussion table, not a measurement comparison.
- **No n-sweep.** n is fixed at {0, 1, 3}.

These are acceptable for a 2-page course paper. They are **not** acceptable for ACSAC, which is why §4-Extended below stays on the table as the May 9 → May 30 follow-up plan.

---

## 4-Extended. ACSAC follow-up (only if pursuing ACSAC after course submission)

The original action list, preserved. Use as the May 9 – May 30 plan if and only if the course submission lands cleanly.

### P0 — Scenario library expansion to 15 (8–12 evenings, both venues)

- **Gap closed:** ACSAC §3 (realistic workloads), NeurIPS §3 (multi-class coverage).
- **Files to add:**
  - `scenarios/trojaned-codebases/typosquat-01-requirements.yaml`
  - `scenarios/trojaned-codebases/typosquat-02-package-json.yaml`
  - `scenarios/trojaned-codebases/malicious-setup-01-bash.yaml`
  - `scenarios/trojaned-codebases/malicious-setup-02-make.yaml`
  - `scenarios/trojaned-codebases/poisoned-makefile-01-install-target.yaml`
  - `scenarios/trojaned-codebases/mcp-poisoning-01-config.yaml`
  - `scenarios/trojaned-codebases/mcp-poisoning-02-fixture.yaml`
  - `scenarios/trojaned-codebases/postinstall-02-obfuscated-curl.yaml`
  - `scenarios/trojaned-codebases/devserver-02-webpack-loader.yaml`
  - `scenarios/trojaned-codebases/benign-{01..05}-*.yaml`
- **Files to modify:** `scenarios/SOURCES.md` (fill the `_TBD_` rows for every new scenario).
- **Time:** 8–12 evenings (1 evening per attack scenario including provenance + canary + smoke test on A1; benigns are faster, ~0.5 evenings each).
- **Venue:** Both. Required for either.

### P1 — Run the full A0/A1/A4/A6 sweep on the expanded library (3 evenings + ~6h compute, ACSAC)

- **Gap closed:** ACSAC §3 (empirical eval). Currently only A4 has a result, with N=1 useful attack run.
- **Files to add:** none. Configs already exist.
- **Files to modify:** none (the runner is wired). Cost: ~$40 per `master-plan.md:122`.
- **Concrete commands:** the four-loop `for abl in A0 A1 A4 A6; do python -m ablations.experiment ... ; done` block already in `README.md:280-289`.
- **Time:** 3 evenings (kickoff + monitor + re-run failed reps + aggregate).
- **Venue:** ACSAC.

### P2 — Real-CVE replay on cloud VM (3–5 evenings, ACSAC)

- **Gap closed:** ACSAC §7 (real attack replay). "Inspired by" doesn't carry an empirical paper.
- **Files to add:**
  - `scenarios/realworld-cloud/axios-march-2026.yaml` (lift from `scenarios/deprecated/realworld/axios.yaml` and lock to a pinned compromised commit).
  - `scenarios/realworld-cloud/cve-2025-68143-mcp-injection.yaml`.
  - `docs/reproducibility/cloud-vm-setup.md` — egress firewall config + isolated VPC + cleanup procedure.
- **Files to modify:** `ablations/experiment.py` to accept `--egress-firewall-required` flag that aborts if iptables/security-group sentinel file isn't present.
- **Time:** 3–5 evenings (1 to provision the VM, 1–2 to wire the egress restriction + sentinel, 1–2 to run + capture transcripts).
- **Venue:** ACSAC. Without this, the threat-model section is theoretical.

### P3 — Non-agentic majority-vote baseline (2–3 evenings, both)

- **Gap closed:** ACSAC §4 (baseline comparison). Isolates the agentic-investigation contribution from the bare-redundancy contribution.
- **Files to add:**
  - `core/stateless_judge.py` — variant of `agentic_judge.py` that sends only `tool_call.json` + system prompt to Anthropic SDK, no docker exec, no filesystem investigation, returns a JudgeVote.
  - `ablations/configs/A4-stateless.json` — 3-judge majority with stateless judges.
  - `prompts/stateless/{param,intent,threat}.md` — stripped prompts (no "investigate the workspace" steps).
  - `tests/test_stateless_judge.py`.
- **Files to modify:** `core/orchestrator.py:46-83` — branch on `judge.kind` (agentic vs. stateless) when dispatching.
- **Time:** 2–3 evenings.
- **Venue:** Both. ACSAC needs it for the baseline table; NeurIPS would want it as one of several reference judges scored against the benchmark.

### P4 — Threat model as a paper artifact (1 evening, ACSAC)

- **Gap closed:** ACSAC §1 (concrete threat model).
- **Files to add:** `docs/threat-model.md` — attacker-capability table (compromised replica, key exfil via tool call, key exfil via container env, RCE via tool call, prompt injection in tool response, supply-chain compromise of judge prompt). Defended/undefended column. One-paragraph attacker model per row.
- **Files to modify:** `README.md` to link.
- **Time:** 1 evening.
- **Venue:** ACSAC.

### P5 — Latency p50/p95/p99 + cost rollup (1 evening, ACSAC)

- **Gap closed:** ACSAC §5 (overhead measurement).
- **Files to modify:**
  - `analysis/aggregate.py:81-105` — replace `median + max` with `numpy.percentile([50, 95, 99])` over `judgments[*].total_latency_ms`. Add per-phase breakdown using `judgments[*].phase_timings_ms` keys (`write_input_ms | clear_verdict_ms | claude_investigation_ms | read_verdict_ms`).
  - `analysis/metrics.py` — add `compute_overhead_table(events_dir, n_values=[1,3])` returning rows ready to LaTeX.
- **Time:** 1 evening.
- **Venue:** ACSAC.

### P6 — n-sweep ablation (n=5 honest, n=5 with f=1) (2 evenings, ACSAC)

- **Gap closed:** ACSAC §6 (ablation over n, f).
- **Files to add:**
  - `ablations/configs/A4-n5.json` — 5 honest judges (Param, Intent, Threat ×2, plus a Provenance judge or duplicate).
  - `ablations/configs/A6-n5.json` — 5 judges with 1 byzantine (still f=1, but tighter quorum margin).
  - `judge_config/provenance/IDENTITY.md` + skills if going with new perspective; otherwise duplicate intent/threat with different temperatures.
- **Files to modify:** none.
- **Time:** 1 evening to wire + 1 evening of compute + analysis. Adds ~$15 to the API budget.
- **Venue:** ACSAC.

### P7 — Frozen-trace replay mode (3–4 evenings, NeurIPS pivot only)

- **Gap closed:** NeurIPS §6 (single-command replay without LLM cost).
- **Files to add:**
  - `analysis/replay_traces.py` — load `events/judgment.jsonl` from a pre-recorded run, replay decisions through `core/voting.py`, recompute outcomes. No LLM calls.
  - `docs/benchmark-api.md` — schema for benchmark consumers.
- **Files to modify:** `core/orchestrator.py` to accept `--frozen-judgments-path`.
- **Time:** 3–4 evenings.
- **Venue:** NeurIPS only. **Skip unless pivoting away from ACSAC.**

### P8 — Public benchmark wrapper repo (1 week+, NeurIPS pivot only)

- **Gap closed:** NeurIPS §1, §5.
- **Files to add:** new sibling repo `bft-toolcall-benchmark` with: `cases/` (the YAMLs), `scoring/` (`analysis/ground_truth.py` ported), `runners/{anthropic,openai,frozen}/` examples. Keep `ece60872-project` as the "reference judge implementation."
- **Time:** 1 week+ to do correctly.
- **Venue:** NeurIPS only. **Don't attempt within 12 days.**

---

## 5. Recommendation

**Course paper first; ACSAC is a stretch off whatever the course submission proves.** With ~10–14 days to the May 8 course deadline, the realistic deliverable is the 2-page paper from `paper-plan.md:110-120` measuring `Δ` and `S` on **8 scenarios × 3 reps × 4 ablations** (the 2 existing trojaned-codebase YAMLs plus 6 new ones, primarily replay-mode to defeat Sonnet's self-defense). Tonight: kick off A0 + A1 on the 2 existing scenarios while the rest of the library gets authored — that compute is free wall-clock and de-risks the pipeline. The teammate must own scenario authoring starting Monday or the May 8 date doesn't hold. The paper itself is feasible in 4 evenings if results land by May 3, but only if **§3 Method is honest about what's implemented** — parallel single-shot majority voting with prompt-swap fault injection, with PBFT as a theoretical anchor being transferred to a new domain, **not as a PBFT implementation**. Reviewers who know BFT will catch the conflation and lose trust on everything else; writing it correctly is free and protects the contribution. After May 8, if the course submission lands and you want a real venue: take ~3 weeks (May 9 – May 30) to execute P0–P5 from §4-Extended for ACSAC. If C1 (scenario authoring) slips past May 1, drop to 4 scenarios for the course paper rather than slipping the sweep — and at that point ACSAC is also off; pivot to **SCORED @ CCS 2026** (supply-chain track, mid-summer) or **ISSRE 2026 industry/fast-abstract** (typically July), both of which accept tighter empirical scope without demanding NeurIPS-scale benchmark coverage.
