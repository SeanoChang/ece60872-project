# BFT Voting Judge Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-judge voting system that replaces human approval in Claude Code, with an API proxy for credential isolation, agentic judge containers, and a honeypot for ground truth measurement.

**Architecture:** A PreToolUse hook in Claude Code POSTs tool calls to an orchestrator, which spins up 1-3 isolated judge agent containers. Each judge investigates the tool call in its own sandbox and votes approve/reject. An API proxy on the host injects the Anthropic API key into all requests so no container holds the key. A honeypot detects credential exfiltration as ground truth.

**Tech Stack:** Python 3.11+, FastAPI, Anthropic SDK, Docker, httpx, pytest, jsonlines

**Spec:** `docs/superpowers/specs/2026-04-13-bft-voting-judge-cluster-design.md`

---

## File Map

| File | Responsibility | Created in |
|---|---|---|
| `core/types.py` | Dataclasses: JudgeConfig, JudgeVote, VoteResult, ToolCall | Task 1 |
| `core/voting.py` | Majority vote, classify() | Task 2 |
| `core/logger.py` | Append-only JSONL writer | Task 3 |
| `core/honeypot.py` | HTTP server :9999, canary/real-key detection | Task 4 |
| `core/api_proxy.py` | Reverse proxy :8081, key injection, per-agent budgets | Task 5 |
| `core/judge_hook.py` | PreToolUse hook thin client | Task 6 |
| `core/judge_agent.py` | Judge agent logic (stateless mode) | Task 7 |
| `core/orchestrator.py` | FastAPI :8080, dispatches judges, collects votes | Task 8 |
| `docker/agent.Dockerfile` | Coding agent container | Task 9 |
| `docker/judge.Dockerfile` | Judge agent container with sandbox | Task 9 |
| `docker/docker-compose.yml` | Service orchestration | Task 9 |
| `prompts/*.md` | All judge system prompts | Task 10 |
| `ablations/configs/*.json` | Per-ablation configuration | Task 11 |
| `ablations/runner.py` | Experiment matrix runner | Task 12 |
| `scenarios/realworld/*.yaml` | Scenario definitions | Task 13 |
| `analysis/metrics.py` | Detection rate, FPR, Condorcet gap | Task 14 |
| `.github/workflows/experiment.yml` | CI workflow | Task 15 |
| `tests/` | All test files | Tasks 1-8, 12, 14 |

---

## Task Summary

15 tasks, ordered by dependency:

1. **Core Types** — ToolCall, JudgeConfig, JudgeVote, VoteResult dataclasses
2. **Voting Logic** — majority_vote(), classify()
3. **JSONL Logger** — append-only writer with file locking
4. **Honeypot Server** — HTTP :9999, canary detection, tripwire
5. **API Proxy** — reverse proxy :8081, key injection, per-agent budgets
6. **Judge Hook** — PreToolUse thin client, stdin → POST → exit code
7. **Judge Agent** — StatelessJudge (single API call, ablation-a mode)
8. **Orchestrator** — FastAPI :8080, dispatches judges, collects votes
9. **Docker Containers** — agent.Dockerfile, judge.Dockerfile, docker-compose
10. **Judge Prompts** — general, param, intent, threat, byzantine naive/subtle
11. **Ablation Configs** — JSON configs for A0-A7, A1-h, A4-h, A4-m
12. **Experiment Runner** — matrix builder, run orchestration
13. **Scenario Definitions** — axios attack, MCP injection, YAML format
14. **Analysis Scripts** — detection rate, FPR, Condorcet gap, quorum survival
15. **GitHub Actions** — CI workflow for Tier 1 automated runs

Each task follows TDD: write failing test → verify failure → implement → verify pass → commit.

**Future tasks (after core is working):**
- AgenticJudge class (Docker-based judge for ablation-b mode)
- Full Docker orchestration in runner.py (container lifecycle management)
- InjecAgent + MCPSecBench scenario adapters
- analysis/plots.py (requires actual result data)

See the full task details with complete code below.
