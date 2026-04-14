# ExperimentRunner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `ExperimentRunner` — the single entry point that orchestrates the full BFT voting experiment lifecycle.

**Architecture:** One class in `ablations/experiment.py` that owns three phases (setup / execute / teardown). Uses asyncio for parallelism (Semaphore-capped concurrency). Shells out to docker via `asyncio.create_subprocess_exec`. Results written to `results/{ablation}/`. One retry on infrastructure failure, then soft abort. Scenarios are independent (no memory), so parallel execution is safe.

**Tech Stack:** Python 3.11+, asyncio, docker CLI via subprocess, existing `core/*` modules, PyYAML.

---

## File Map

| File | Responsibility |
|---|---|
| `core/infra.py` | Start/stop proxy/honeypot/orchestrator subprocesses; health check |
| `core/scenario.py` | Load scenario YAML, render workspace to disk, generate canaries |
| `core/runner_agent.py` | Run one coding-agent Docker container per scenario |
| `ablations/experiment.py` | `ExperimentRunner` — setup/execute/teardown lifecycle + CLI |
| `tests/test_infra.py`, `tests/test_scenario.py`, `tests/test_runner_agent.py`, `tests/test_experiment.py` | pytest suites (mocked subprocess) |

Delete: `ablations/runner.py` (placeholder), `tests/test_runner.py`

---

## Tasks

### Task 1 — `core/infra.py`

Implement `InfrastructureServices` class with:
- `__init__(api_key, results_dir, orchestrator_config_path, ports...)`
- `async start()` — launches proxy/honeypot/orchestrator as asyncio subprocesses with stdout/stderr redirected to log files in `results_dir`. Calls `wait_for_health()` on orchestrator `/health` with 60s timeout. Raises RuntimeError on timeout after calling `stop()`.
- `async stop()` — SIGTERM each process, wait 5s per process with `asyncio.wait_for`, SIGKILL if unresponsive.

Also implement module-level `async wait_for_health(url, timeout_seconds, poll_interval=1.0) -> bool` — polls URL via httpx.AsyncClient, returns True on 200.

TDD tests:
- `test_wait_for_health_success`: mock httpx response 200 → True
- `test_wait_for_health_timeout`: mock httpx raises → False after timeout
- `test_infrastructure_services_init`: verify object construction

### Task 2 — `core/scenario.py`

Dataclass `Scenario` with fields: `scenario_id`, `description`, `archetype`, `task_prompt`, `workspace_files` (dict), `canary_credentials` (list), `ground_truth` (dict).

Function `load_scenario(yaml_path: str) -> Scenario` — uses PyYAML safe_load.

Function `render_workspace(scenario: Scenario, workspace_dir: str) -> dict[str, str]` —
- Writes each `workspace_files` entry to disk under `workspace_dir`
- For each canary credential: generates a realistic random value using `secrets.token_urlsafe`, renders the `value_template` (replace `{canary}` with generated value), writes/appends to the target location
- Returns a dict mapping canary_id (e.g., "api_key_0") to the actual planted string

Helper `_generate_canary(credential_type: str) -> str` — returns type-appropriate format:
- `api_key` → `sk-ant-api03-<random48>`
- `aws_key` → `AKIAIOSFODNN7<random16upper>`
- `ssh_key` → wrapped in BEGIN/END RSA PRIVATE KEY markers
- `npm_token` → `npm_<random36>`
- default → `canary-<random>`

TDD tests:
- `test_load_scenario`: write a YAML, load it, verify fields
- `test_render_workspace_writes_files_and_canaries`: render, verify files exist, verify canary string is in the rendered file, verify returned dict maps correctly

### Task 3 — `core/runner_agent.py`

Dataclass `RunnerAgentConfig`: `image`, `workspace_host_dir`, `task_prompt`, `proxy_url`, `orchestrator_url`, `timeout_seconds=600`.

Function `async run_runner_agent(config) -> tuple[int, bytes, bytes]` — constructs a `docker run --rm` command with:
- `-v workspace_host_dir:/workspace`
- `-w /workspace`
- env vars: `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY=""`, `JUDGE_ORCHESTRATOR_URL`
- `--add-host=host.docker.internal:host-gateway`
- command: `claude -p <task_prompt>`

Wraps `proc.communicate()` in `asyncio.wait_for(timeout=config.timeout_seconds)`. On timeout: kill process, return `(124, b"", b"runner agent timed out")`. Otherwise return `(returncode, stdout, stderr)`.

TDD tests:
- `test_run_runner_agent_builds_command`: mock subprocess, verify cmd args contain "docker", "run", "--rm", image name
- `test_run_runner_agent_reports_nonzero_exit`: mock returncode=1, verify propagation

### Task 4 — `ablations/experiment.py`

`ExperimentRunner` class with:

Constructor loads ablation JSON, initializes `JudgeContainerManager` and `InfrastructureServices`, creates `results/{ablation}/scenarios/` directory.

`async _setup()`:
- Calls `self.infra.start()`
- For each judge in config: calls `container_mgr.build_container_config(role, name)`, then `_docker_run_container(cfg)`

`async _docker_run_container(cfg)`:
- Builds `docker run -d --name ... --add-host host.docker.internal:host-gateway -e KEY=VAL -v host:bind:mode ... image command` from the cfg dict
- Runs via `asyncio.create_subprocess_exec`, raises RuntimeError on non-zero return

`async _execute()`:
- Builds task list: `[(scenario_path, rep) for scenario in paths for rep in 1..reps]`
- Uses `asyncio.Semaphore(max_concurrency)` to cap parallelism
- Inner async function `run_one(path, rep)`: try `_run_scenario_rep()`, on exception retry once, on second failure set `self.soft_abort = True` and return error dict
- `asyncio.gather` all tasks, store in `self.run_results`

`async _run_scenario_rep(scenario_path, rep) -> dict`:
- `scenario = load_scenario(path)`
- `canaries = render_workspace(scenario, self.container_mgr.workspace_dir)`
- Build `RunnerAgentConfig` and call `run_runner_agent`
- Assemble result dict: scenario_id, rep, agent_return_code, agent_stderr (last 500 bytes), canaries, timestamp
- Write to `results/{ablation}/scenarios/{scenario_id}_rep{N}.json`
- Return result dict

`async _teardown()`:
- For each container name: `docker rm -f <name>` (ignore errors)
- Call `self.infra.stop()`

`async run() -> dict` (main entry point):
- try: `_setup()` → `_execute()`
- except Exception: set `soft_abort = True`, append setup_failed dict
- finally: `_teardown()`
- Build summary dict: ablation, scenarios, reps, total_runs, soft_abort, duration_seconds, results
- Write `results/{ablation}/experiment_summary.json`
- Return summary

CLI `main()`:
- argparse: `--config`, `--scenarios` (nargs=+), `--reps` (default 3), `--max-concurrency` (default 3), `--results-root` (default "results")
- Read `ANTHROPIC_API_KEY` from env (exit 1 if missing)
- Construct `ExperimentRunner`, call `asyncio.run(runner.run())`
- Print summary (ablation, total_runs, soft_abort, duration)
- Exit with code 1 if soft_abort, else 0

TDD tests:
- `test_experiment_runner_runs_all_scenarios`: mock `_setup`, `_run_scenario_rep`, `_teardown`; verify all three called, `_run_scenario_rep` called `scenarios × reps` times
- `test_experiment_runner_soft_aborts_after_retry`: mock `_run_scenario_rep` to always raise; verify summary has `soft_abort: true` and `_teardown` still called

Before Task 4 implementation, delete:
- `ablations/runner.py`
- `tests/test_runner.py`

---

## Implementation Order Rationale

Tasks 1, 2, 3 are independent — each produces a small focused module with its own tests. Can be run in parallel by subagents.

Task 4 depends on all three. Must run last.

Total: 4 tasks, ~12 new tests, ~400 lines of code.

---

## Self-Review

**Spec coverage:** all setup/execute/teardown phases, soft-abort with retry, parallel scenarios with Semaphore, results layout, CLI entry point.

**Placeholder scan:** no TBDs or vague steps. All function signatures and return types explicit.

**Type consistency:** `Scenario` dataclass → used by `render_workspace`, `_run_scenario_rep`. `RunnerAgentConfig` → consumed by `run_runner_agent`. `JudgeContainerManager` methods already exist with matching signatures.

**Deferred (not in this plan):**
- Honeypot dynamic canary registration (honeypot uses static patterns today; rendered canaries are recorded in per-run JSON for post-hoc analysis)
- Image rebuild within ExperimentRunner (GitHub Actions workflow handles this separately)
- Signal handling for graceful Ctrl+C
