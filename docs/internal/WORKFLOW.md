# Internal: Codebase Workflow & Architecture

Last updated after: stateless removal + memory system removal.

This is the internal engineering reference for how the code fits together. For the research overview see the top-level `README.md`.

---

## Directory Structure

```
ece60872-project/
├── core/                              ← Python modules
│   ├── types.py                       ← Dataclasses (JudgeConfig, JudgeVote, VoteResult, ToolCall)
│   ├── voting.py                      ← majority_vote(), classify()
│   ├── logger.py                      ← JSONLLogger (append-only)
│   ├── honeypot.py                    ← HoneypotServer (:9999)
│   ├── api_proxy.py                   ← ApiProxy (:8081, key injection, per-agent budgets)
│   ├── judge_hook.py                  ← PreToolUse hook thin client
│   ├── orchestrator.py                ← FastAPI (:8080, dispatches judges)
│   ├── agentic_judge.py               ← run_agentic_judge() via docker exec
│   └── judge_containers.py            ← JudgeContainerManager
│
├── docker/                            ← Container images
│   ├── agent.Dockerfile               ← Runner agent (Claude Code)
│   └── judge-agentic.Dockerfile       ← Judge agent (Claude Code + investigation tools)
│
├── judge_config/                      ← Judge identity/skills (mounted into judge containers)
│   ├── CLAUDE.md                      ← Shared entry instructions
│   ├── param/IDENTITY.md + skills/    ← Parameter Validator (CWE-20, NIST SI-10)
│   ├── intent/IDENTITY.md + skills/   ← Intent Aligner (NIST AC-6 PoLP)
│   ├── threat/IDENTITY.md + skills/   ← Threat Modeler (STRIDE + MITRE ATT&CK)
│   └── byzantine/{naive,subtle}/      ← Byzantine variants with hidden override
│
├── prompts/                           ← Legacy system prompts (was for stateless judges)
│
├── scenarios/realworld/               ← YAML test cases
│   ├── axios.yaml                     ← March 2026 npm supply chain
│   ├── mcp-injection.yaml             ← CVE-2025-68143 class injection
│   └── poisoned-setup.yaml            ← Social engineering via README
│
├── ablations/
│   ├── configs/                       ← 10 ablation configs (A1–A7, plus -h and -m variants)
│   └── runner.py                      ← Placeholder — ExperimentRunner lives here (TODO)
│
├── analysis/
│   └── metrics.py                     ← Detection rate, FPR, Condorcet gap, quorum survival
│
├── tests/                             ← pytest suite (68 tests, all passing)
└── .github/workflows/experiment.yml   ← CI workflow (Tier 1 automated runs)
```

---

## Service Topology

Everything runs on one host (local dev machine, cloud VM, or GitHub Actions runner):

```
Host Machine
├── ApiProxy (:8081)
│   └── Holds ANTHROPIC_API_KEY, injects into all outgoing requests
│       All containers set ANTHROPIC_BASE_URL=http://host.docker.internal:8081
│
├── Honeypot (:9999)
│   └── Logs all HTTP requests, detects canary credential patterns
│       Ground truth for attack success
│
├── Orchestrator (:8080)
│   └── FastAPI. Receives tool calls from hooks, dispatches judges, applies voting
│
├── Docker: judge-param (persistent, `sleep infinity`)
│   ├── /workspace/  (ro mount — shared across all judges, swapped per scenario)
│   ├── /sandbox/    (rw — for investigation: npm install --dry-run, etc.)
│   └── /judge/      (CLAUDE.md, IDENTITY.md, skills/)
│
├── Docker: judge-intent (same structure)
├── Docker: judge-threat (same structure)
│
└── Docker: runner-agent (ephemeral — one per scenario, destroyed after)
    ├── Claude Code running the task
    ├── /workspace/ (scenario files + planted canary credentials)
    └── Network restricted: proxy + honeypot only
```

---

## Per-Tool-Call Flow

This is what happens every time the runner agent proposes a tool call:

```
[Coding Agent Container]
    Claude Code proposes: bash("npm install")
        │
        ▼
[PreToolUse Hook fires inside container]
    core/judge_hook.py
    - Reads tool call JSON from stdin
    - POSTs to orchestrator on host
        │
        ▼
[Orchestrator on host :8080]
    core/orchestrator.py
    - Receives POST /judge
    - Calls run_judges(tool_call, judge_configs)
        │
        │  Dispatches N judges in parallel via asyncio.gather
        ▼
    ┌────────────┬────────────┬────────────┐
    │            │            │            │
    ▼            ▼            ▼            ▼
 Judge A      Judge B      Judge C      (or however many in the ablation config)
 (Param)      (Intent)     (Threat)

 Each dispatch runs core/agentic_judge.py::run_agentic_judge():
   1. docker exec -i judge-X sh -c 'cat > /tool_call.json'
   2. docker exec judge-X sh -c 'rm -f /verdict.json'
   3. docker exec judge-X claude -p "Investigate the tool call..."
   4. docker exec judge-X cat /verdict.json
   5. Parse JSON → JudgeVote

 Inside each judge container, Claude Code:
   - Reads /judge/CLAUDE.md → IDENTITY.md → skills/*.md
   - Investigates: read /workspace, run bash in /sandbox, inspect packages
   - Writes verdict to /verdict.json
   - All API calls go through the host's ApiProxy (proxy injects the key)
        │
        ▼
[majority_vote() in core/voting.py]
    Aggregates the 1–3 JudgeVote objects into a single VoteResult
        │
        │  Writes JSONL log record via JSONLLogger
        │  Returns response JSON to the hook
        ▼
[Hook exits]
    exit 0 → Claude Code executes the tool call
    exit 2 → Claude Code receives rejection + reason

[If tool executed and it's malicious]
    [Honeypot (:9999)]
    - Logs any request containing canary credential strings
    - canary seen = attack succeeded (ground truth)
    - real API key seen = tripwire, halt experiment
```

---

## What Makes Judges "Agentic"

Each judge is **Claude Code running inside its own Docker container**, not a one-shot API call.

| Capability | Source |
|---|---|
| System prompt | `/judge/identity/IDENTITY.md` (grounded in MITRE/CWE/STRIDE) |
| Bootstrap instructions | `/judge/CLAUDE.md` (shared across judges) |
| Investigation procedures | `/judge/identity/skills/*.md` (per-role, grounded) |
| Workspace read access | `/workspace/` mount (read-only — same workspace as the agent) |
| Investigation sandbox | `/sandbox/` mount (read-write — where the judge runs commands) |
| Available tools | bash, file read, grep, python, git, curl, npm, pip (all inside container) |
| API access | via ApiProxy (no key in container) |

**Each judgment is independent** — no memory carries across tool calls or scenarios. This preserves research validity (no test-set contamination).

---

## Ablation Configs (`ablations/configs/`)

Each config is a JSON file defining:
- `ablation`: identifier (e.g., "A4")
- `judges`: list of JudgeConfig entries (name, model, system_prompt_path, role, temperature, is_byzantine, etc.)
- `log_path`: where to write JSONL results

The orchestrator reads a config at startup. The ExperimentRunner (TODO) will iterate over scenarios × reps for a given config.

| Config | Judges | What it tests |
|---|---|---|
| A1 | 1 Sonnet (general) | Single-judge baseline |
| A2 | 1 Sonnet (best specialized) | Prompt engineering ceiling |
| A3 | 3 Sonnet (same prompt, T=0.7) | Pure Condorcet redundancy |
| A4 | 3 Sonnet (param/intent/threat) | N-version perspective diversity |
| A5 | 1 Opus | Cost-quality anchor |
| A1-h | 1 Haiku | Cheap single-judge |
| A4-h | 3 Haiku (diverse) | Cheap multi-judge |
| A4-m | 2 Haiku + 1 Sonnet | Mixed-model N-version |
| A6 | 3 Sonnet (1 Byzantine naive) | Byzantine quorum survival |
| A7 | 3 Sonnet (1 Byzantine + poison) | Byzantine ⊕ correlated failure |

---

## What Is Built vs What Is Missing

### ✅ Built

- All modules in `core/`
- Both Dockerfiles (`agent.Dockerfile`, `judge-agentic.Dockerfile`)
- Judge identities + skills with MITRE/CWE/STRIDE/NIST/OWASP citations
- Byzantine variants (naive + subtle)
- All 10 ablation configs
- 3 real-world scenario YAMLs
- Analysis metrics (detection rate, FPR, Condorcet gap, quorum survival)
- 68 passing tests

### ❌ Missing: The Entry Point

Currently the pieces exist but **nothing orchestrates the full experiment lifecycle**. To run an experiment today, you'd have to manually:

```bash
# Terminal 1
python -m core.api_proxy &
# Terminal 2
python -m core.honeypot &
# Terminal 3
python -m core.orchestrator --config ablations/configs/A4.json &
# Terminal 4 (manually, per judge)
docker run -d --name judge-param -v <abs>/workspace:/workspace:ro \
    -v <abs>/judge_config/param:/judge/identity:ro \
    -v <abs>/judge_config/CLAUDE.md:/judge/CLAUDE.md:ro \
    bft-judge-agentic
docker run -d --name judge-intent ... bft-judge-agentic
docker run -d --name judge-threat ... bft-judge-agentic
# Terminal 5 (manually, per scenario)
# - swap /workspace contents
# - plant canary credentials
# - docker run --rm bft-agent claude -p "$(cat scenarios/realworld/axios.yaml | yq .task_prompt)"
# - wait, collect honeypot log
# - read orchestrator JSONL
# - clean up runner container
# repeat for every scenario × rep
# Then stop/remove all containers and services manually
```

### 🚧 Next: ExperimentRunner

A single class (`ablations/experiment.py::ExperimentRunner`) that owns the full lifecycle:

```python
class ExperimentRunner:
    """Single entry point for an experiment.

    Lifecycle:
      Phase 1 — setup:    build images, start services, start judge containers, health-check
      Phase 2 — execute:  for each (scenario × rep), run in parallel up to max_concurrency
      Phase 3 — teardown: stop containers, save summary
    """
    async def run(self) -> dict: ...
```

CLI:
```bash
python -m ablations.experiment \
    --config ablations/configs/A4.json \
    --scenarios scenarios/realworld/*.yaml \
    --reps 3 \
    --max-concurrency 5
```

Design decisions (already made):
- **Parallel scenarios**, capped via `asyncio.Semaphore(max_concurrency)`
- **One retry on infrastructure failure**, then soft abort (stop experiment, save partial results)
- **Results layout**: `results/{ablation}/scenarios/{scenario}_rep{N}.json` + `experiment_summary.json`
- **Health check**: poll each service every 1s, 60s total timeout
- **No memory between judgments** — scenarios independent, reproducible

---

## Research Validity Notes

### Why no memory persistence

Originally judges had a MEMORY.md that accumulated across scenarios. Removed because:

1. **Test-set contamination** — judges "learned" patterns during the experiment, invalidating later scenarios as independent tests
2. **Ordering bugs** — scenario C's outcome depends on what came before (A→B→C vs C→A→B produced different results)
3. **Broken Condorcet analysis** — per-judge accuracy `p` is supposed to be stable, but memory made it drift
4. **Non-reproducible** — other researchers couldn't replicate results

Now: each judgment is fully independent. Judges read IDENTITY.md + skills/, investigate the workspace, vote, done. No state carries over.

### Why only agentic mode (no stateless)

Stateless was originally the "ablation-a" mode (single API call, no investigation). Removed because:
- Doubled the token cost without providing research value we care about
- The interesting comparison is between different *agentic* configurations (diverse prompts, model tiers, Byzantine vs honest), not agentic-vs-API-only

All judges are now Claude Code inside Docker containers with investigation capabilities.

---

## Key Design Patterns to Know

### API Proxy for credential isolation

The real `ANTHROPIC_API_KEY` lives in exactly one place: the ApiProxy process on the host. All containers set `ANTHROPIC_BASE_URL=http://host.docker.internal:8081` and `ANTHROPIC_API_KEY=""`. The proxy strips incoming headers, injects the real key, and forwards to Anthropic. If malicious code in any container searches for the key, it finds an empty string.

Canary credentials (fake AWS/SSH/npm tokens) are planted as files in the agent's workspace. These ARE the attack target. The judges protect these — the proxy protects the API key.

### Per-agent budgeting

The proxy reads `x-judge-id` from incoming requests to identify which agent is making the call. Each agent has a budget (e.g., `agent-main=$5.00`, `judge-a=$0.50`). Requests that would exceed budget return HTTP 429. Cost is computed per-model using the actual response tokens (Sonnet/Opus/Haiku pricing verified current).

### Framework-grounded prompts

Each role's IDENTITY.md and skills/ files cite specific MITRE ATT&CK techniques, CWE IDs, and relevant NIST/OWASP references. This was a deliberate choice over generic "security analyst" framing — gives reviewers authoritative sources to point to and strengthens the N-version claim (judges applying genuinely different methodologies).

| Role | Framework |
|---|---|
| Param Validator | CWE-20, CWE-22/78/94/95, NIST SI-10 |
| Intent Aligner | NIST AC-6/AC-3 (Principle of Least Privilege), NIST RMF |
| Threat Modeler | STRIDE + MITRE ATT&CK |
