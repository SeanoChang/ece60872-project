# Agentic Judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AgenticJudge (ablation-b mode) — persistent Claude Code instances in Docker containers that investigate tool calls with workspace access, sandbox, skills, and accumulating memory.

**Architecture:** Each judge is a Docker container with Claude Code installed. The orchestrator sends tool calls via `docker exec`, invoking `claude -p` with a prompt that instructs investigation. Judges read IDENTITY.md and MEMORY.md via CLAUDE.md. The orchestrator appends structured verdict records to MEMORY.md; the judge appends freeform findings. Judges persist across scenarios.

**Tech Stack:** Python 3.11+, Docker (via asyncio subprocess), Claude Code CLI, asyncio

**Spec:** `docs/superpowers/specs/2026-04-13-agentic-judge-design.md`

---

## File Map

| File | Responsibility | Created in |
|---|---|---|
| `core/agentic_judge.py` | `run_agentic_judge()`, `parse_verdict_json()`, `format_memory_entry()` | Task 1 |
| `core/judge_containers.py` | `JudgeContainerManager` — start/stop/swap/memory management | Task 2 |
| `docker/judge-agentic.Dockerfile` | Judge container with Claude Code + investigation tools | Task 3 |
| `judge_config/CLAUDE.md` | Shared CLAUDE.md template | Task 4 |
| `judge_config/MEMORY.md` | Empty MEMORY.md template with section headers | Task 4 |
| `judge_config/param/IDENTITY.md` | Param Validator identity | Task 4 |
| `judge_config/param/skills/*.md` | 3 param validator skills | Task 4 |
| `judge_config/intent/IDENTITY.md` | Intent Aligner identity | Task 4 |
| `judge_config/intent/skills/*.md` | 3 intent aligner skills | Task 4 |
| `judge_config/threat/IDENTITY.md` | Threat Modeler identity | Task 4 |
| `judge_config/threat/skills/*.md` | 3 threat modeler skills | Task 4 |
| `judge_config/byzantine/naive/IDENTITY.md` | Byzantine naive identity | Task 5 |
| `judge_config/byzantine/subtle/IDENTITY.md` | Byzantine subtle identity | Task 5 |
| Modify: `core/orchestrator.py` | Branch on config.mode for agentic dispatch | Task 6 |
| Modify: `pyproject.toml` | Add `docker` dependency | Task 1 |

---

## Tasks

6 tasks covering: core agentic judge function, container management, Dockerfile, identity/skills/memory configs, Byzantine configs, and orchestrator integration.

### Task 1: Core Agentic Judge Function
- Create `core/agentic_judge.py` with `run_agentic_judge()`, `parse_verdict_json()`, `format_memory_entry()`
- TDD: test verdict parsing (valid, malformed, missing fields)
- `run_agentic_judge` uses `asyncio.create_subprocess_exec` for docker exec calls
- Add `docker>=7.0.0` to pyproject.toml

### Task 2: Judge Container Manager
- Create `core/judge_containers.py` with `JudgeContainerManager`
- Methods: `build_container_config()`, `container_names_from_ablation()`, `swap_workspace()`, `append_memory_entry()`, `truncate_memory_if_needed()`
- TDD: test config building, name generation, stateless filtering

### Task 3: Agentic Judge Dockerfile
- Create `docker/judge-agentic.Dockerfile`
- Based on node:20-slim with Claude Code, python3, investigation tools (jq, grep, ripgrep)
- `CMD ["sleep", "infinity"]` — stays alive, work via docker exec

### Task 4: Judge Identity, Skills, and Memory Templates
- Create all judge_config files: CLAUDE.md, MEMORY.md, 3 roles x (IDENTITY.md + 3 skills)
- Param Validator: analyze-arguments, check-paths, validate-urls
- Intent Aligner: compare-task-scope, check-dependencies, detect-off-task
- Threat Modeler: check-typosquat, inspect-postinstall, detect-obfuscation
- All identities include priorities: accuracy > time > cost

### Task 5: Byzantine Identity Configs
- Create naive and subtle Byzantine IDENTITY.md variants
- Based on Threat Modeler identity with appended override
- Naive: always approve with plausible justification
- Subtle: only reject on obvious dangerous strings

### Task 6: Orchestrator Integration
- Modify `core/orchestrator.py` to import and dispatch `run_agentic_judge` when config.mode == "agentic"
- Modify `run_judges()` to branch per-judge on mode
- TDD: test agentic mode dispatch with mocked run_agentic_judge
- Existing stateless tests must continue passing
