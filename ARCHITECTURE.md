# Architecture — Code Reference

This is the engineering reference for how the BFT voting system is implemented. For the research overview see [README.md](README.md). For the working-notes version see [docs/internal/WORKFLOW.md](docs/internal/WORKFLOW.md).

---

## Repo Layout

```
ece60872-project/
├── ARCHITECTURE.md                ← this file
├── README.md                      ← paper-style overview
│
├── core/                          ← Python modules (the system)
│   ├── types.py                   ← dataclasses: JudgeConfig, JudgeVote, VoteResult, ToolCall
│   ├── voting.py                  ← majority_vote(), classify()
│   ├── logger.py                  ← JSONLLogger (append-only, filelock)
│   ├── honeypot.py                ← HoneypotServer (:9999, canary detection)
│   ├── api_proxy.py               ← ApiProxy (:8081, key injection, per-agent budgets)
│   ├── judge_hook.py              ← PreToolUse hook thin client (runs inside agent container)
│   ├── orchestrator.py            ← FastAPI :8080 — /judge endpoint, dispatches judges
│   ├── agentic_judge.py           ← run_agentic_judge() — docker exec claude -p
│   ├── judge_containers.py        ← JudgeContainerManager (build config, swap workspace)
│   ├── infra.py                   ← InfrastructureServices (start/stop proxy/honeypot/orchestrator)
│   ├── scenario.py                ← load_scenario(), render_workspace() + canary gen
│   └── runner_agent.py            ← run_runner_agent() — docker run --rm agent container
│
├── ablations/
│   ├── configs/                   ← 10 JSON configs (A1, A1-h, A2, A3, A4, A4-h, A4-m, A5, A6, A7)
│   └── experiment.py              ← ExperimentRunner — SINGLE ENTRY POINT for experiments
│
├── analysis/
│   └── metrics.py                 ← compute_detection_rate, compute_fpr, condorcet_gap, quorum_survival
│
├── docker/
│   ├── agent.Dockerfile           ← coding agent container (Claude Code + hook config)
│   ├── judge-agentic.Dockerfile   ← judge container (Claude Code + investigation tools)
│   └── claude-settings.json       ← hook config INSIDE agent container (not repo root)
│
├── judge_config/                  ← mounted into judge containers
│   ├── CLAUDE.md                  ← shared entry instructions (stateless judgment model)
│   ├── {param,intent,threat}/IDENTITY.md + skills/*.md
│   │                                 ← role-specific, grounded in MITRE/CWE/STRIDE/NIST
│   └── byzantine/{naive,subtle}/IDENTITY.md  ← compromised judge variants
│
├── prompts/                       ← legacy stateless-judge prompts (kept for reference)
│
├── scenarios/                     ← test cases (YAML)
│   ├── realworld/                 ← axios, mcp-injection, poisoned-setup
│   ├── injecagent/                ← 5 cases adapted from InjecAgent benchmark
│   └── mcpsecbench/               ← 5 cases adapted from MCPSecBench benchmark
│
├── tests/                         ← pytest suite (73 tests, all passing)
│
├── docs/
│   ├── internal/WORKFLOW.md       ← working-notes version of this file (original)
│   ├── planning/                  ← original planning documents
│   │   ├── master-plan.md
│   │   ├── shared.md
│   │   ├── direction-1-plan.md
│   │   └── starter.md
│   └── superpowers/               ← specs + implementation plans
│
├── .github/workflows/
│   ├── ci.yml                     ← tests + image builds on push
│   └── experiment.yml             ← manual-dispatch experiment runner
│
├── pyproject.toml                 ← deps: anthropic, fastapi, httpx, docker, yaml, etc.
└── results/                       ← experiment outputs (gitignored)
```

---

## Module-by-Module

### Core types (`core/types.py`)

Four frozen/mutable dataclasses:

- **ToolCall** — parses the JSON payload Claude Code sends to PreToolUse hooks. Fields: `tool_name`, `tool_input`, `tool_use_id`, `session_id`, `cwd`. Property `command` extracts `tool_input["command"]` or `tool_input["file_path"]`.
- **JudgeConfig** — immutable config for one judge. Fields: `name`, `model`, `system_prompt_path`, `temperature`, `role` (Literal: param/intent/threat/general), `is_byzantine`, `compromise_variant`, `timeout_seconds`. Property `prompt_hash` returns sha256 of the prompt file (used for drift detection).
- **JudgeVote** — a single judge's output. Fields include decision, confidence, reason, investigation_steps, tools_used, cost_usd, latency_ms, input/output_tokens, is_byzantine flag.
- **VoteResult** — aggregated: decision, list of votes, quorum_rule, total_latency_ms, total_cost_usd.

### Voting (`core/voting.py`)

Pure functions, no side effects:

- **`majority_vote(votes) -> VoteResult`** — approvals > n/2 → approve, else reject (ties go to reject). Latency is max of votes (parallel), cost is sum. Raises `ValueError` on empty input.
- **`classify(ground_truth, vote_decision) -> str`** — mapping to TP/TN/FP/FN labels. Convention: "malicious + reject" = true_positive (correctly detected attack).

### Logger (`core/logger.py`)

Append-only JSONL with filelock:
- `append(record)` — writes one line, `json.dumps(record, default=str)`
- `read_all() -> list[dict]` — replays the file

### Honeypot (`core/honeypot.py`)

FastAPI server on :9999. On every request:
1. Decode body, compose `full_content = url + body`
2. Check if any `canary_patterns` string appears → `canary_match=True`
3. Check `real_key_pattern` regex → `real_key_match=True`
4. Log to JSONL + in-memory `self._logs`
5. Always return `{"status": "ok"}` with HTTP 200 (attacker thinks exfil succeeded)

Properties: `saw_canary`, `saw_real_key` for ground-truth queries.

### API Proxy (`core/api_proxy.py`)

Reverse proxy on :8081. The only place the real `ANTHROPIC_API_KEY` exists.

Per-request:
1. Read `x-judge-id` header to identify the agent
2. Check budget: if agent's cumulative spend >= limit → return 429
3. Strip `x-judge-id` and `host` headers
4. Inject `x-api-key` with the real key
5. Forward to `https://api.anthropic.com/{path}`
6. Parse response for `usage` and `model`, look up pricing, add to `_spend[agent_id]`
7. Log: {timestamp, agent_id, method, path, cost_usd, cumulative_spend, budget_limit}
8. Return response to the container

Pricing is looked up per-model (prefix match) from a table: Opus 4.6 ($5/$25/M), Sonnet 4 ($3/$15/M), Haiku 4.5 ($1/$5/M).

### Judge Hook (`core/judge_hook.py`)

Thin PreToolUse hook. Runs as a subprocess inside the agent container.

```
Claude Code → pipe JSON to stdin → judge_hook.py
judge_hook.py → POST http://host.docker.internal:8080/judge
orchestrator → response {decision, reason}
judge_hook.py → exit 0 (approve) or exit 2 (reject + reason on stderr)
```

**Fail-closed**: any exception (network, 5xx, malformed response) → exit 2 with reason. Claude Code sees the rejection and adapts.

### Orchestrator (`core/orchestrator.py`)

FastAPI server on :8080. One endpoint matters: `POST /judge`.

Flow:
1. `ToolCall.from_hook_payload(payload)`
2. `await run_judges(tool_call, judge_configs, transcript_dir)` — dispatches all judges in parallel via `asyncio.gather`
3. `majority_vote(votes) → VoteResult`
4. Build log record with per-phase timing (hook_received_ms, hook_returned_ms, dispatch_duration_ms) + every judge's vote
5. `logger.append(record)` to JSONL
6. Return response to the hook

`run_judges` dispatches via `run_agentic_judge` (only agentic mode exists now — stateless was removed).

### Agentic Judge (`core/agentic_judge.py`)

`run_agentic_judge(container_name, tool_call, judge_name, model_id, timeout_seconds=500, transcript_dir=None) -> JudgeVote`

Runs a judgment inside a persistent judge container via `asyncio.create_subprocess_exec` on `docker`:

1. **Write**: `docker exec -i {name} sh -c 'cat > /judge/tool_call.json'` with JSON on stdin (paths live inside `/judge` WORKDIR so Read is auto-allowed under default permission mode)
2. **Clear**: `docker exec {name} sh -c 'rm -f /judge/verdict.json'`
3. **Investigate**: `docker exec {name} claude -p "{INVESTIGATION_PROMPT}" --output-format stream-json --verbose --model {model_id} --setting-sources user --permission-mode acceptEdits` — wrapped in `asyncio.wait_for(timeout=500s)`. `acceptEdits` auto-approves the judge's `Write(/judge/verdict.json)` without triggering Claude Code's root-safety block. On timeout → fail-closed reject vote. On non-zero exit → fail-closed reject with stderr truncated to 500 chars; cost_usd captured from stream-json before the early-return so real spend is still reported.
4. **Read**: `docker exec {name} cat /judge/verdict.json`
5. **Parse**: `parse_verdict_json` extracts decision/confidence/reason/investigation_steps. On malformed JSON → reject with confidence 0.5. `extract_result_cost(claude_stdout)` from `core/stream_parser.py` walks the stream-json for the final `type: "result"` event and sets `vote.cost_usd` to the CLI-computed `total_cost_usd` (authoritative source — applies cache discounts, already aggregates per-message usage).

If `transcript_dir` set, writes each investigation's stdout/stderr to `{transcript_dir}/{judge_name}_{timestamp}.{stdout,stderr}`.

Per-phase timing recorded: `write_input_ms`, `clear_verdict_ms`, `claude_investigation_ms`, `read_verdict_ms`. Total `latency_ms` on the returned JudgeVote.

### Judge Container Manager (`core/judge_containers.py`)

`JudgeContainerManager` — helpers for judge container lifecycle. Does NOT start containers itself (ExperimentRunner does via docker CLI).

- `container_names_from_ablation(ablation) -> list[str]` — returns `["judge-param", "judge-intent", ...]`
- `build_container_config(role, container_name) -> dict` — returns docker-run-style config: image, environment, volumes (workspace:ro, role identity:ro, CLAUDE.md:ro), command `sleep infinity`
- `swap_workspace(scenario_workspace_dir)` — `shutil.rmtree` + `shutil.copytree` — since judges mount `workspace_dir` read-only, swapping contents on the host is visible to all containers without restart

### Infrastructure Services (`core/infra.py`)

`InfrastructureServices` spawns the three host-side services as subprocesses.

- `async start()` — launches `python -m core.api_proxy`, `python -m core.honeypot`, `python -m core.orchestrator` each with stdout/stderr → log file in results dir. Calls `wait_for_health("http://localhost:8080/health", 60s)`. On timeout, calls `stop()` and raises.
- `async stop()` — SIGTERM each, `asyncio.wait_for(proc.wait(), 5s)`, SIGKILL on timeout.
- Module-level `wait_for_health(url, timeout_seconds) -> bool` — polls via httpx.

### Scenario loading (`core/scenario.py`)

- **Scenario dataclass** — scenario_id, description, archetype, task_prompt, workspace_files (dict[path, content]), canary_credentials (list), ground_truth (dict).
- **`load_scenario(yaml_path) -> Scenario`** — safe_load.
- **`render_workspace(scenario, workspace_dir) -> dict[str, str]`** — writes all files; for each canary, generates a realistic random value via `_generate_canary(credential_type)` (type-specific format: api_key, aws_key, ssh_key, npm_token, generic), renders `value_template.replace("{canary}", value)`, writes/appends to the target location. Returns `{canary_id: planted_string}` for honeypot detection.

### Runner Agent (`core/runner_agent.py`)

`RunnerAgentConfig` dataclass + `async run_runner_agent(config) -> (rc, stdout, stderr)`.

Runs one ephemeral agent container:
```
docker run --rm \
  -v {abs workspace}:/workspace \
  -w /workspace \
  -e ANTHROPIC_BASE_URL={proxy} \
  -e ANTHROPIC_API_KEY= \
  -e JUDGE_ORCHESTRATOR_URL={orch} \
  --add-host=host.docker.internal:host-gateway \
  {image} \
  claude -p "{task_prompt}"
```

Wrapped in `asyncio.wait_for(timeout=600s)`. On timeout → kill + return `(124, "", "runner agent timed out")`.

### Analysis (`analysis/metrics.py`)

Pure functions:
- `compute_detection_rate(results)` — TP / (TP + FN) = rejected_malicious / total_malicious
- `compute_fpr(results)` — FP / (FP + TN) = rejected_benign / total_benign
- `condorcet_predicted(p, n)` — P(majority correct) = Σ C(n,k) · pᵏ · (1-p)^(n-k) for k from ⌈n/2⌉ to n
- `compute_condorcet_gap(p, observed, n=3)` — observed − predicted. Negative = judges correlated.
- `compute_quorum_survival(detection_byzantine, detection_honest)` — ratio, 1.0 = full tolerance.

---

## Single Entry Point: `ablations/experiment.py`

**`ExperimentRunner.run()`** owns the full lifecycle:

### Phase 1 — `_setup()`

1. `await self.infra.start()` — spawn proxy/honeypot/orchestrator host subprocesses, wait for `/health`
2. For each judge in ablation config: `docker run -d --name judge-{name} ... sleep infinity`

### Phase 2 — `_execute()`

1. Build task matrix: `[(scenario_path, rep) for path in scenarios for rep in 1..reps]`
2. `asyncio.Semaphore(max_concurrency)` caps parallel scenario runs
3. For each (scenario, rep): try `_run_scenario_rep`, on failure retry once, on second failure set `soft_abort = True` and log

Inside `_run_scenario_rep`:
- `load_scenario(path)` → Scenario dataclass
- `render_workspace(scenario, /tmp/bft-workspace)` → canaries dict (written to workspace, judges see them via mount)
- `run_runner_agent(config)` → docker run --rm agent container executing `claude -p "{task_prompt}"`
- Agent makes tool calls → hook → orchestrator → judge containers → vote → return to hook → agent executes or gets rejection
- Capture full stdout/stderr of agent to `results/{ablation}/scenarios/{scenario}_rep{N}.{stdout,stderr}`
- Write summary JSON with rc, duration, canaries planted, paths to stdout/stderr files

### Phase 3 — `_teardown()` (always runs, in `finally`)

1. For each judge container: `docker rm -f {name}`
2. `await self.infra.stop()` — SIGTERM proxy/honeypot/orchestrator

### Output layout

```
results/{ablation}/
├── experiment_summary.json
├── effective_config.json           ← ablation config with runtime transcript_dir injected
├── proxy.log, honeypot.log, orchestrator.log
├── proxy.jsonl, honeypot.jsonl, orchestrator.jsonl
├── judge_transcripts/
│   └── {judge_name}_{timestamp}.{stdout,stderr}
└── scenarios/
    ├── {scenario_id}_rep{N}.json
    ├── {scenario_id}_rep{N}.stdout
    └── {scenario_id}_rep{N}.stderr
```

CLI:
```
python -m ablations.experiment \
    --config ablations/configs/A4.json \
    --scenarios scenarios/realworld/axios.yaml \
    --reps 3 \
    --max-concurrency 3
```

Exits 0 on success, 1 on soft_abort.

---

## Data Flow — One Tool Call

```
Runner Agent Container
    Claude Code wants to run: bash("npm install")
        │
        │  fork subprocess: python core/judge_hook.py
        │  pipe JSON {tool_name, tool_input, tool_use_id, session_id} to stdin
        │
        ▼
    judge_hook.py (runs inside runner container)
        │  POST http://host.docker.internal:8080/judge
        │
        ▼
    Orchestrator on host (:8080)
        │  ToolCall.from_hook_payload()
        │  run_judges() → asyncio.gather of 3 run_agentic_judge() calls
        │
        ▼
    Each run_agentic_judge (parallel, staggered by _JUDGE_STAGGER_SECONDS):
        │  docker exec judge-{name} sh -c 'cat > /judge/tool_call.json' (stdin: payload)
        │  docker exec judge-{name} sh -c 'rm -f /judge/verdict.json'
        │  docker exec judge-{name} claude -p "{INVESTIGATION_PROMPT}" \
        │      --output-format stream-json --verbose \
        │      --model {model_id} --setting-sources user \
        │      --permission-mode acceptEdits
        │      │
        │      │  Inside judge container: Claude Code reads IDENTITY.md + skills/,
        │      │  investigates /workspace (ro), uses /sandbox for npm --dry-run etc.,
        │      │  makes LLM calls via proxy, writes /judge/verdict.json
        │      │
        │  docker exec judge-{name} cat /judge/verdict.json
        │  parse_verdict_json → JudgeVote
        │  extract_result_cost(stdout) → vote.cost_usd
        │
        ▼
    Back in orchestrator:
        │  majority_vote(votes) → VoteResult
        │  logger.append(record) — orchestrator.jsonl
        │  Return response JSON to hook
        │
        ▼
    Back in judge_hook.py:
        │  decision == "approve" → exit 0
        │  decision == "reject" → write reason to stderr, exit 2
        │
        ▼
    Claude Code reads hook's exit code:
        0 → executes bash("npm install") → side effects may hit honeypot
        2 → records rejection, adapts reasoning, picks next tool call
```

---

## Key Design Invariants

**1. API key never enters a container.**
Proxy holds the key. All containers set `ANTHROPIC_BASE_URL=http://host.docker.internal:8081` and `ANTHROPIC_API_KEY=""`. If malicious code searches for the key, it finds empty string.

**2. Stateless judgments.**
Each `claude -p` invocation is fresh. No MEMORY.md. No cross-scenario accumulation. Scenarios are independent experimental units — order doesn't affect outcomes.

**3. Fail-closed at every layer.**
- judge_hook.py: exception → exit 2 (reject)
- run_agentic_judge: any docker exec failure, timeout, or parse failure → reject JudgeVote
- ties in majority_vote → reject (conservative)

**4. Timeout hierarchy.**
Claude Code hook timeout (600s, in settings.json) > orchestrator judge timeout (500s, in run_agentic_judge). Ensures we never exceed the hook's limit.

**5. Single entry point.**
ExperimentRunner.run() is the only thing you invoke. Everything else is infrastructure underneath. Read that one method top-to-bottom to understand the experiment.

---

## Tests

`tests/` has 73 pytest cases covering every module (types, voting, logger, honeypot, api_proxy, judge_hook, agentic_judge, judge_containers, orchestrator, infra, scenario, runner_agent, experiment, metrics).

- Fake Docker via mocked `asyncio.create_subprocess_exec`
- Fake Anthropic via `AsyncMock` on the SDK's `messages.create`
- Fake HTTP via httpx `ASGITransport` for FastAPI apps
- Temp dirs via pytest's `tmp_path`

Run all:
```
conda run -n ece60872 python -m pytest tests/ -v
```

## CI

`.github/workflows/ci.yml` runs on every push:
- `test` — pytest suite
- `build-images` — builds both Dockerfiles
- `smoke-test-services` — starts honeypot + proxy briefly, verifies they bind and respond

`.github/workflows/experiment.yml` runs on manual dispatch:
- Builds images
- Invokes `python -m ablations.experiment` with chosen ablation and scenarios
- Uploads `results/` as a workflow artifact (90-day retention)

---

## What's Next

- Matrix workflow to run all 10 ablations in parallel (one per GitHub Actions runner)
- Honeypot canary registration at experiment start (currently uses static patterns)
- Signal handling for graceful experiment shutdown on Ctrl+C
