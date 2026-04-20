# Master Plan (Codebase Mirror)

> Canonical planning document lives in the Obsidian vault at
> `Learning/Spring 2026/Reliable and Secure Computer Systems/Final Project/三個臭皮匠勝過一個諸葛亮 — BFT Voting for Coding Agent Tool Calls.md`.
> This file is the condensed code-side mirror, kept in sync with the vault.
> Status: **Locked 2026-04-17** — one paper, four ablation conditions, live-agent runner primary, replay-agent fallback.

---

## Project

**Course**: ECE 60872 — Reliable and Secure Computer Systems, Prof. Saurabh Bagchi, Purdue Spring 2026.

**Deliverable**: One 2-page DSN workshop paper measuring whether two classical voting theorems (TMR and BFT) transfer to agentic LLM judges on coding-agent tool-call safety.

> **Scope note (2026-04-17)**: An earlier version of this plan described two papers produced by two groups from one shared repo with a fork at `v0.1-shared-scaffold`. That framing is obsolete. This repo produces ONE paper, from Sean's group only. The "other group" on the course team is building a separate pre-filter classifier (a different component of the defense pipeline) and does NOT fork this repo.

## The Paper

**Working title**: *"Does Triple Modular Redundancy Transfer to LLM Agentic Voting for Coding-Agent Tool-Call Safety? Plus a Byzantine-Tolerance Ablation."*

Two research questions measured in one paper, both on the same scenario library and same honest-judge stack.

### RQ1 — TMR transfer

Does 3-judge agentic majority voting detect trojaned codebases at a higher rate than a single agentic judge, and at what false-positive cost?

- **Ablations**: A1 vs A4
- **Headline metric**: `Δ = detection(A4) − detection(A1)` with 95% bootstrap CI; FPR on benign controls reported alongside
- **Classical anchors**: TMR (von Neumann 1956; Lyons & Vanderkulk 1962), Condorcet Jury Theorem (Condorcet 1785), N-version programming (Avizienis & Chen 1977)

### RQ2 — BFT transfer

Does 2-of-3 agentic majority voting retain its detection rate when one judge's system prompt is silently replaced with a Byzantine ("always approve") variant?

- **Ablations**: A4 vs A6
- **Headline metric**: `S = detection(A6) / detection(A4)` (quorum survival rate) with 95% bootstrap CI
- **Classical anchors**: PBFT 3f+1 (Castro-Liskov 1999), Byzantine Generals Problem (Lamport, Shostak, Pease 1982), Byzantine Quorum Systems (Malkhi & Reiter 1998)

### A0 — Sonnet 4.6 self-defense floor

Both Δ and S are reported *on top of* an A0 baseline: the trojaned-codebase detection rate of the live Claude Sonnet 4.6 coding agent with **no voting guard at all**. Voting's contribution is framed as incremental on top of whatever safety the frontier model already provides unaided. A0 is not a measurement condition of the guard — it is the measurement condition of the agent.

## Ablation Matrix (final, four conditions)

| ID | Judges | Model | Prompt strategy | Temp | What it tests |
|---|---|---|---|---|---|
| **A0** | 0 | — (agent alone, no guard) | — | — | Agent self-defense baseline |
| **A1** | 1 | Sonnet 4.6 | General security reviewer | 0.0 | Single-judge baseline |
| **A4** | 3 | Sonnet 4.6 ×3 | Param / Intent / Threat | 0.0 | Honest 2-of-3 majority voting |
| **A6** | 3 | Sonnet 4.6 ×3 | Param / Intent / Byzantine-Threat (naive) | 0.0 | 2-of-3 with 1 Byzantine judge |

Four conditions × ~15 trojaned-codebase scenarios × 3 reps ≈ 180 runs. Expected wall clock: 4–6 hours. Budget: ~$40 of the dedicated $50 Anthropic key.

**Stretch** (optional, only if Week 3 finishes early): A2, A3, A5, A1-h, A4-h, A4-m, A6-subtle, A7. These configs are not in `ablations/configs/` in the main plan; restore them under `ablations/configs/stretch/` if we decide to run them.

## Execution Path — Live Agent Primary, Replay Agent Fallback

The primary execution path is a real Claude Code instance running inside `docker/agent.Dockerfile`, managed by `core/runner_agent.py`. The agent receives a benign-looking task prompt (e.g. *"set up this project by running `npm install`"*) and proposes tool calls against a trojaned codebase. The PreToolUse hook forwards each proposed call to the orchestrator, which convenes the voting panel (A1: 1 judge, A4/A6: 3 judges, A0: bypasses).

`core/replay_agent.py` is a **fallback**, not the primary path. It exists for scenarios where the live agent's own refusal would prevent the voting panel from observing the decision under test — the scenario YAML pre-specifies `proposed_tool_call` and the shim POSTs it on the hook path. For the A0/A1/A4/A6 matrix on the current trojaned-codebase library the live runner is the default; replay is used only when a specific scenario proves empirically unobservable under the live runner.

## Scenario Library

~15 scenarios in `scenarios/trojaned-codebases/` (10 malicious + 5 benign controls):

| Archetype | Trojan location | Provenance |
|---|---|---|
| postinstall | `package.json` → `scripts/setup.js` | axios March 2026 supply-chain compromise |
| typosquat | `requirements.txt` | AIShellJack ([2509.22040](https://arxiv.org/abs/2509.22040)) |
| malicious-setup | `setup.sh` | InjecAgent `dh-*` adapted ([2403.02691](https://arxiv.org/abs/2403.02691)) |
| poisoned-makefile | `Makefile` `install:` target | CVE-2025-68143 class |
| mcp-poisoning | `.mcp/config.json` + fixture | Anthropic Git MCP CVEs 2025-68143/4/5 |
| benign controls | — | ×5 for FPR measurement |

Every scenario has an entry in `scenarios/SOURCES.md` with arxiv ID + original case reference + adaptation notes.

## Architecture

```
Host Machine (live-agent mode, primary)
┌──────────────────────────────────────────────────────────────┐
│  API Proxy (:8081) ─ holds ANTHROPIC_API_KEY                 │
│  Orchestrator (:8080) ─ dispatches judges, collects votes    │
│  Honeypot (:9999) ─ canary detector, ground truth            │
│                                                              │
│  Runner Agent (docker/agent.Dockerfile — PRIMARY)            │
│   └─ Claude Code proposes tool calls against trojaned repo   │
│                                                              │
│  Judge A/B/C (docker/judge-agentic.Dockerfile, per-container)│
│   ├─ Claude Code in own container with skill kit             │
│   ├─ workspace mounted READ-ONLY                             │
│   └─ investigates → votes approve/reject                     │
└──────────────────────────────────────────────────────────────┘

Replay-agent fallback (core/replay_agent.py) bypasses the runner container
and emits scenario.proposed_tool_call directly via the hook payload path.
Used only for scenarios where the live agent's own self-defense would
short-circuit the voting panel.
```

## Mandatory Daylight Sentences (§2 Related Work)

The following claims must appear in §2 to preempt reviewer skim-review objections, per the 2026-04-17 novelty audit. They cover both RQ1 and RQ2 threats in one consolidated block since this is one paper.

1. *"No prior work measures the A1→A4 (single-judge vs 2-of-3 TMR majority) detection gap for **agentic** LLM judges — judges with filesystem access and investigation tools — applied to coding-agent tool-call admission against trojaned codebases. Prior multi-agent LLM safety work is either (i) non-agentic panels on text tasks [Verga'24, Zheng'25], (ii) single agentic judges [Xiang'24, ShieldAgent'25, Zhuge'24], or (iii) divided-labor pipelines for package-level classification [CHASE'26, LAMPS'26]."*

2. *"Unlike BFT/consensus work on multi-agent LLMs [Zheng'25], we anchor on classical TMR (von Neumann 1956; Lyons 1962) and PBFT (Castro-Liskov 1999) with 2-of-3 majority to isolate the redundancy gain attributable to voter independence in the Condorcet sense [Condorcet 1785] — not to a new consensus protocol."*

3. *"Prior work on LLM-as-judge ensembles under attack [Maloyan'25] measures success under **shared-input prompt injection** — adversarial content visible to all judges. We measure quorum survival under **configuration compromise** — one voter's own system prompt is silently replaced — which corresponds to stolen prompt registries and supply-chain attacks on agent configurations, the setting for which PBFT's 2-of-3 bound is most directly invoked."*

## Schedule

| Week | Dates | Milestones |
|---|---|---|
| **Week 2 remainder** | Apr 18–24 | Smoke test live runner on 2–3 scenarios; complete ~15-scenario library; run A0 (baseline) and A1 |
| **Week 3** | Apr 25 – May 1 | Run A4 and A6; compute Δ, S, A0 self-defense rate; per-archetype breakdown; figures; paper skeleton |
| **Week 4** | May 2 – May 8 | Paper iteration; internal cross-read; verify citations; submit |

## Budget

Dedicated Anthropic API key with $50 hard spend limit in the console. A0/A1 are cheap (~$5 combined across 90 runs); A4/A6 are the main spend (~$15–20 each, 3 reps × 15 scenarios × 3 judges).

## Companion documents

- `docs/planning/paper-plan.md` — detailed code-side paper plan (this doc's operational companion)
- `docs/planning/infrastructure.md` — shared infrastructure contract (formerly `shared.md`)
- `scenarios/SOURCES.md` — scenario provenance manifest
- `docs/planning/_archive/` — obsolete two-group-fork docs retained for history
- `docs/_archive/HANDOFF.md` — obsolete Group B fork handoff retained for history
