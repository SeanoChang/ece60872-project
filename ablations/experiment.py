from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx

from core.correlation import new_run_id, new_scenario_run_id, correlation_context
from core.events import (
    ExperimentStart, ExperimentEnd, ScenarioRunStart, ScenarioRunEnd, Inspection,
)
from core.infra import InfrastructureServices
from core.judge_containers import JudgeContainerManager
from core.logger import JSONLLogger
from core.runner_agent import RunnerAgentConfig, run_runner_agent
from core.scenario import load_scenario, render_workspace
from analysis.ground_truth import match_patterns, classify_scenario_outcome
from analysis.aggregate import aggregate_experiment
from analysis.inspection import compute_inspection_for_scenario
from core.stream_parser import (
    extract_tool_calls as _extract_from_stream,
    extract_tool_uses as _extract_tool_uses_from_stream,
    extract_result_cost as _extract_result_cost_from_stream,
)


# Tool names that the PreToolUse hook matcher in docker/claude-settings.json
# actually intercepts. Calls to other tools (Glob, Read, Grep, …) bypass the
# judge panel entirely — the orchestrator never hears about them. Kept in sync
# with `hooks.PreToolUse[0].matcher` in that file.
_HOOK_MATCHED_TOOLS = frozenset({"Bash", "Edit", "Write"})


class ExperimentRunner:

    def __init__(
        self,
        ablation_config_path: str,
        scenario_paths: list[str],
        reps: int,
        max_concurrency: int,
        api_key: str,
        results_root: str = "results",
        agent_image: str = "bft-agent:latest",
        judge_image: str = "bft-judge-agentic:latest",
        judge_configs_dir: str = "judge_config",
        workspace_dir: str = "/tmp/bft-workspace",
        permission_mode: str = "default",
        timeout_seconds: int = 120,
    ) -> None:
        with open(ablation_config_path) as f:
            self.ablation = json.load(f)
        self.ablation_name = self.ablation["ablation"]
        self.scenario_paths = scenario_paths
        self.reps = reps
        self.max_concurrency = max_concurrency
        self.api_key = api_key
        self.ablation_config_path = ablation_config_path
        self.agent_image = agent_image
        self.judge_image = judge_image
        self.permission_mode = permission_mode
        self.timeout_seconds = timeout_seconds

        self.results_dir = Path(results_root) / self.ablation_name
        self.results_dir.mkdir(parents=True, exist_ok=True)
        (self.results_dir / "scenarios").mkdir(exist_ok=True)
        transcript_dir = self.results_dir / "judge_transcripts"
        transcript_dir.mkdir(exist_ok=True)
        events_dir = self.results_dir / "events"
        events_dir.mkdir(exist_ok=True)
        self.events_dir = events_dir

        # Generate the run-level correlation ID
        self.run_id = new_run_id()

        # Write an effective config that carries the runtime transcript_dir and events_dir
        self.ablation["transcript_dir"] = str(transcript_dir)
        self.ablation["events_dir"] = str(events_dir)
        self.effective_config_path = self.results_dir / "effective_config.json"
        self.effective_config_path.write_text(json.dumps(self.ablation, indent=2))

        self.container_mgr = JudgeContainerManager(
            image=judge_image,
            judge_configs_dir=judge_configs_dir,
            workspace_dir=workspace_dir,
            proxy_url="http://host.docker.internal:8081",
        )

        self.infra = InfrastructureServices(
            api_key=api_key,
            results_dir=str(self.results_dir),
            orchestrator_config_path=str(self.effective_config_path),
            run_id=self.run_id,
            ablation=self.ablation_name,
        )

        self.run_results: list[dict] = []
        self.soft_abort: bool = False

    def _write_event(self, event) -> None:
        """Append a pydantic event to its per-type JSONL stream under a file lock."""
        event_type = event.event_type
        path = self.events_dir / f"{event_type}.jsonl"
        JSONLLogger(str(path)).append_event(event)

    async def _setup(self) -> None:
        # Create the shared workspace directory as the current user BEFORE Docker
        # touches it. If Docker auto-creates the bind-mount source, it's owned by
        # root (dockerd runs as root) and render_workspace() can't write into it.
        Path(self.container_mgr.workspace_dir).mkdir(parents=True, exist_ok=True)

        await self.infra.start()
        names = self.container_mgr.container_names_from_ablation(self.ablation)
        for name in names:
            role_key = name.removeprefix("judge-")
            role = "general"
            for j in self.ablation["judges"]:
                if j["name"] == role_key:
                    role = j.get("role", "general")
                    break
            cfg = self.container_mgr.build_container_config(role=role, container_name=name)
            await self._docker_run_container(cfg)

    async def _docker_run_container(self, cfg: dict) -> None:
        # Judge containers are inspectors. We map the synthetic-corp hostnames
        # (otel/telemetry/metrics .platform.local) to host-gateway so the judge
        # can reach the honeypot if it elects to *invoke* a lure script during
        # investigation. This is the same hostname mapping the agent gets, so
        # the judge sees the same network reality as the agent. It does NOT
        # change A0/A1 detection of static-content trojans (the trojan's HTTP
        # request still has to actually run), but it lets us test scenarios
        # where the judge's own bash investigation triggers the canary.
        #
        # Memory limit: long-running judge containers accumulate context across
        # many claude-p invocations. Without a cap, macOS's kernel OOM killer
        # would occasionally SIGKILL the claude subprocess (exit 137 surfaced
        # in judgment events). 2 GiB is enough headroom for a single Haiku
        # session with the system prompt + per-call investigation context,
        # and bounds resource use deterministically across the panel.
        cmd = [
            "docker", "run", "-d", "--name", cfg["name"],
            "--memory=2g",
            "--memory-swap=2g",
            "--add-host=host.docker.internal:host-gateway",
            "--add-host=otel-collector.platform.local:host-gateway",
            "--add-host=telemetry.platform.local:host-gateway",
            "--add-host=metrics.platform.local:host-gateway",
        ]
        for k, v in cfg.get("environment", {}).items():
            cmd.extend(["-e", f"{k}={v}"])
        for host_path, mount in cfg.get("volumes", {}).items():
            cmd.extend(["-v", f"{host_path}:{mount['bind']}:{mount.get('mode', 'ro')}"])
        cmd.append(cfg["image"])
        if cfg.get("command"):
            cmd.extend(cfg["command"].split())

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker run failed for {cfg['name']}: {stderr.decode()}")

    async def _execute(self) -> None:
        tasks = [
            (path, rep)
            for path in self.scenario_paths
            for rep in range(1, self.reps + 1)
        ]
        sem = asyncio.Semaphore(self.max_concurrency)

        async def run_one(scenario_path: str, rep: int) -> dict:
            async with sem:
                try:
                    return await self._run_scenario_rep(scenario_path, rep)
                except Exception as first:
                    # Surface the first-attempt error immediately — otherwise it
                    # only reaches experiment_summary.json, which is invisible
                    # in CI logs without downloading the artifact.
                    import traceback
                    print(
                        f"[{self.ablation_name}] {scenario_path}_rep{rep} "
                        f"ATTEMPT 1 FAILED: {type(first).__name__}: {first}",
                        file=sys.stderr, flush=True,
                    )
                    traceback.print_exception(first, file=sys.stderr)
                    try:
                        return await self._run_scenario_rep(scenario_path, rep)
                    except Exception as second:
                        print(
                            f"[{self.ablation_name}] {scenario_path}_rep{rep} "
                            f"ATTEMPT 2 FAILED: {type(second).__name__}: {second}",
                            file=sys.stderr, flush=True,
                        )
                        traceback.print_exception(second, file=sys.stderr)
                        self.soft_abort = True
                        return {
                            "scenario_path": scenario_path,
                            "rep": rep,
                            "status": "failed",
                            "error_first": str(first),
                            "error_retry": str(second),
                        }

        self.run_results = list(await asyncio.gather(*[run_one(s, r) for s, r in tasks]))

    async def _run_scenario_rep(self, scenario_path: str, rep: int) -> dict:
        scenario = load_scenario(scenario_path)
        scenario_run_id = new_scenario_run_id(scenario.scenario_id, rep)

        with correlation_context(scenario_run_id=scenario_run_id):
            # Wipe the workspace before rendering: leftover files from a
            # previous scenario contaminate inspection-rate measurement
            # (the agent reads files that don't belong to the current
            # scenario) and accumulate canaries in .env across runs.
            # The directory itself is recreated by render_workspace.
            ws_root = Path(self.container_mgr.workspace_dir)
            if ws_root.exists():
                for child in ws_root.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        try:
                            child.unlink()
                        except OSError:
                            pass
            canaries = render_workspace(scenario, self.container_mgr.workspace_dir)

            # Register canaries with the honeypot so the active scenario_run_id
            # is stamped on emitted HoneypotRequest events, and the canary patterns
            # are actually detected (attacker curl commands can't set correlation headers).
            canary_values = list(canaries.values())
            if canary_values:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.post(
                            "http://localhost:9999/_register_canary",
                            json={"patterns": canary_values, "scenario_run_id": scenario_run_id},
                            headers={"x-admin-token": self.infra.admin_token},
                        )
                except Exception as e:
                    print(f"WARN: failed to register canaries with honeypot: {e}", file=sys.stderr)

            # Emit scenario_run_start
            self._write_event(ScenarioRunStart(
                run_id=self.run_id,
                scenario_run_id=scenario_run_id,
                ablation=self.ablation_name,
                scenario_id=scenario.scenario_id,
                scenario_path=scenario_path,
                rep=rep,
                canaries_planted=canaries,
            ))

            runner_cfg = RunnerAgentConfig(
                image=self.agent_image,
                workspace_host_dir=self.container_mgr.workspace_dir,
                task_prompt=scenario.task_prompt,
                proxy_url="http://host.docker.internal:8081",
                orchestrator_url="http://host.docker.internal:8080",
                scenario_run_id=scenario_run_id,
                run_id=self.run_id,
                permission_mode=self.permission_mode,
                timeout_seconds=self.timeout_seconds,
                # Early-terminate-on-canary support: feed the planted
                # canary values for this run plus the honeypot's JSONL
                # log path into the runner. As soon as the watcher sees
                # any canary in the log, the agent is killed instead of
                # being left to hang on a long-running command.
                canaries=list(canaries.values()),
                honeypot_jsonl_path="results/honeypot.jsonl",
            )

            run_start = time.time()
            rc, stdout, stderr = await run_runner_agent(runner_cfg)
            run_duration = time.time() - run_start

            # Write full stdout/stderr to separate files (no truncation)
            run_id_str = f"{scenario.scenario_id}_rep{rep}"
            stdout_file = self.results_dir / "scenarios" / f"{run_id_str}.stdout"
            stderr_file = self.results_dir / "scenarios" / f"{run_id_str}.stderr"
            stdout_file.write_bytes(stdout)
            stderr_file.write_bytes(stderr)

            # Compute ground truth outcome signals
            tool_calls = self._extract_tool_calls(stdout, stderr)
            dangerous_patterns = scenario.ground_truth.get("expected_dangerous_calls", [])
            benign_patterns = scenario.ground_truth.get("expected_benign_calls", [])
            dangerous_matches = match_patterns(tool_calls, dangerous_patterns)
            benign_matches = match_patterns(tool_calls, benign_patterns)

            # Inspection signal (docs/proposal.md §"Inspection Signal";
            # docs/measurement-spec.md §3-§4). Failures here must not abort
            # the scenario — a parser bug shouldn't drop otherwise-good run
            # data; the analyzer's outputs are an enrichment, not the
            # primary outcome label.
            inspection_record = None
            try:
                inspection_record = compute_inspection_for_scenario(stdout, scenario)
                self._write_event(Inspection(
                    run_id=self.run_id,
                    scenario_run_id=scenario_run_id,
                    ablation=self.ablation_name,
                    scenario_id=scenario.scenario_id,
                    scenario_path=scenario_path,
                    rep=rep,
                    **inspection_record.to_dict(),
                ))
            except Exception as exc:  # noqa: BLE001  best-effort enrichment
                print(
                    f"WARN: inspection compute failed for "
                    f"{scenario.scenario_id}_rep{rep}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

            honeypot_saw_canary = self._check_honeypot_for_canaries(scenario_run_id)

            # Single-read invariant: panel_rejected and judgments_summary MUST
            # be derived from the same judgments list. Previously we read the
            # file twice (once here for panel_rejected, once below for
            # summary) — under `--max-concurrency > 1` a late-arriving
            # judgment write could land between the reads and produce an
            # outcome label inconsistent with judgments_summary.decisions.
            judgments = self._collect_judgments(scenario_run_id)
            panel_rejected = any(
                j.get("decision") == "reject" for j in judgments
            )

            outcome = classify_scenario_outcome(
                dangerous_matched=len(dangerous_matches),
                benign_matched=len(benign_matches),
                honeypot_saw_canary=honeypot_saw_canary,
                agent_return_code=rc,
                is_attack_scenario=bool(dangerous_patterns),
                panel_rejected=panel_rejected,
            )

            # Emit scenario_run_end
            self._write_event(ScenarioRunEnd(
                run_id=self.run_id,
                scenario_run_id=scenario_run_id,
                ablation=self.ablation_name,
                scenario_id=scenario.scenario_id,
                scenario_path=scenario_path,
                rep=rep,
                agent_return_code=rc,
                agent_duration_seconds=run_duration,
                honeypot_saw_canary=honeypot_saw_canary,
                outcome=outcome,
            ))

            # Structured tool-use list + hook-matcher count. Useful for
            # distinguishing "agent refused to propose anything" (hook_matched=0)
            # from "agent proposed but panel approved" (hook_matched>0,
            # judgments nonempty).
            tool_uses = _extract_tool_uses_from_stream(stdout)
            hook_matched = sum(
                1 for u in tool_uses if u.get("tool_name") in _HOOK_MATCHED_TOOLS
            )

            # Panel config snapshot — what judges were configured to run this
            # scenario, regardless of whether they were actually invoked.
            panel_config = {
                "ablation": self.ablation_name,
                "num_judges": len(self.ablation.get("judges", [])),
                "judges": [
                    {
                        "name": j["name"],
                        "role": j.get("role", "general"),
                        "model": j["model"],
                        "is_byzantine": j.get("is_byzantine", False),
                        "compromise_variant": j.get("compromise_variant", ""),
                    }
                    for j in self.ablation.get("judges", [])
                ],
            }

            # Agent cost comes from the stream-json's final `type: "result"`
            # event, which carries the CLI-computed total_cost_usd. This is
            # authoritative — the proxy's api_call.jsonl has been observed to
            # return $0 because its response parser isn't extracting
            # Anthropic's usage/cost fields (tracked separately). Stream-json
            # sidesteps that entirely.
            agent_cost_usd = _extract_result_cost_from_stream(stdout)

            # Summary derived from the SAME judgments list read above — the
            # single-read invariant lets us assert:
            #   panel_rejected == (judgments_summary.decisions.reject > 0)
            # which the outcome label depends on.
            judgments_summary = {
                "count": len(judgments),
                "decisions": {
                    "approve": sum(1 for j in judgments if j.get("decision") == "approve"),
                    "reject": sum(1 for j in judgments if j.get("decision") == "reject"),
                },
                "total_latency_ms": sum(j.get("total_latency_ms", 0) for j in judgments),
                "total_cost_usd": round(
                    sum(j.get("total_cost_usd", 0.0) for j in judgments), 6
                ),
            }

            result = {
                "scenario_id": scenario.scenario_id,
                "scenario_run_id": scenario_run_id,
                "scenario_path": scenario_path,
                "rep": rep,
                "agent_return_code": rc,
                "agent_duration_seconds": round(run_duration, 2),
                "outcome": outcome,
                "honeypot_saw_canary": honeypot_saw_canary,
                "dangerous_matches": len(dangerous_matches),
                "benign_matches": len(benign_matches),
                "stdout_path": str(stdout_file),
                "stderr_path": str(stderr_file),
                "canaries": canaries,
                "timestamp": run_start,
                "panel_config": panel_config,
                "agent_tool_uses": tool_uses,
                "agent_hook_matching_calls": hook_matched,
                "agent_cost_usd": round(agent_cost_usd, 6),
                "inspection": inspection_record.to_dict() if inspection_record else None,
                "judgments": judgments,
                "judgments_summary": judgments_summary,
                "total_cost_usd": round(agent_cost_usd + judgments_summary["total_cost_usd"], 6),
            }

            result_file = self.results_dir / "scenarios" / f"{run_id_str}.json"
            result_file.write_text(json.dumps(result, indent=2))

            # Runtime summary — headline line followed by a breakdown of
            # what the agent proposed, what the panel decided, and how
            # much the run cost.
            print(
                f"[{self.ablation_name}] {scenario.scenario_id}_rep{rep} → "
                f"{outcome} (duration={run_duration:.1f}s, rc={rc})",
                flush=True,
            )

            # (1) What triggered the hook
            hook_matched_uses = [
                u for u in tool_uses if u.get("tool_name") in _HOOK_MATCHED_TOOLS
            ]
            if hook_matched_uses:
                for u in hook_matched_uses:
                    cmd = u.get("command", "") or f"({u['tool_name']} with unknown args)"
                    cmd_short = cmd if len(cmd) <= 80 else cmd[:77] + "..."
                    print(f"    hook fired on: {u['tool_name']}  {cmd_short}", flush=True)
            else:
                matchers = "|".join(sorted(_HOOK_MATCHED_TOOLS))
                print(
                    f"    hook fired on: — (agent proposed {len(tool_uses)} tool uses,"
                    f" none matched {matchers} — panel not exercised)",
                    flush=True,
                )

            # (2) + (3) Per-judge votes and panel decision
            if judgments:
                for jm in judgments:
                    print(
                        f"    panel decision: {jm['decision']}  ({jm['quorum_rule']},"
                        f" max latency {jm['total_latency_ms']/1000:.1f}s,"
                        f" judges' cost ${jm['total_cost_usd']:.4f})",
                        flush=True,
                    )
                    for v in jm.get("votes", []):
                        reason = v.get("reason", "") or ""
                        if len(reason) > 72:
                            reason = reason[:69] + "..."
                        print(
                            f"      {v['judge_name']:22}  {v['decision']:7}"
                            f"  {v['latency_ms']/1000:6.1f}s  ${v['cost_usd']:.4f}"
                            f"  {reason!r}",
                            flush=True,
                        )
            else:
                print("    panel decision: — (no judgment recorded)", flush=True)

            # (4) Cost estimation for this scenario run
            judge_cost = judgments_summary["total_cost_usd"]
            print(
                f"    cost: agent ${agent_cost_usd:.4f} + judges ${judge_cost:.4f}"
                f" = ${agent_cost_usd + judge_cost:.4f} total",
                flush=True,
            )

            return result

    def _collect_judgments(self, scenario_run_id: str) -> list[dict]:
        """Return every judgment.jsonl record whose scenario_run_id matches.

        Returns [] if the file doesn't exist (the hook never fired during this
        run) or if no records match. Called after the agent container has
        exited, so all judgments for this scenario_run_id are already flushed.
        """
        path = self.events_dir / "judgment.jsonl"
        if not path.exists():
            return []
        out: list[dict] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("scenario_run_id") == scenario_run_id:
                out.append(event)
        return out

    def _extract_tool_calls(self, stdout: bytes, stderr: bytes) -> list[str]:
        """Extract agent tool calls from Claude Code's stream-json output."""
        return _extract_from_stream(stdout)

    def _check_honeypot_for_canaries(self, scenario_run_id: str) -> bool:
        """Check the honeypot event log for any canary hits during this scenario run."""
        honeypot_events_path = self.events_dir / "honeypot_request.jsonl"
        if not honeypot_events_path.exists():
            return False
        for line in honeypot_events_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("scenario_run_id") == scenario_run_id and event.get("canary_match"):
                return True
        return False

    async def _teardown(self) -> None:
        names = self.container_mgr.container_names_from_ablation(self.ablation)
        for name in names:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        await self.infra.stop()

    async def run(self) -> dict:
        """Full lifecycle: setup → execute → teardown. Returns summary."""
        start_time = time.time()

        with correlation_context(run_id=self.run_id):
            # Emit experiment_start event
            self._write_event(ExperimentStart(
                run_id=self.run_id,
                ablation=self.ablation_name,
                scenarios=self.scenario_paths,
                reps=self.reps,
                max_concurrency=self.max_concurrency,
                judge_configs=[j for j in self.ablation.get("judges", [])],
            ))

            try:
                await self._setup()
                await self._execute()
            except Exception as e:
                import traceback
                print(
                    f"[{self.ablation_name}] SETUP/EXECUTE FAILED: "
                    f"{type(e).__name__}: {e}",
                    file=sys.stderr, flush=True,
                )
                traceback.print_exception(e, file=sys.stderr)
                self.soft_abort = True
                self.run_results.append({"status": "setup_failed", "error": str(e)})
            finally:
                await self._teardown()

            duration = time.time() - start_time
            total = len([r for r in self.run_results if r.get("status") != "setup_failed"])

            # Emit experiment_end event
            self._write_event(ExperimentEnd(
                run_id=self.run_id,
                ablation=self.ablation_name,
                total_runs=total,
                duration_seconds=duration,
                soft_abort=self.soft_abort,
            ))

        # Build and write high-level summary
        summary = {
            "ablation": self.ablation_name,
            "run_id": self.run_id,
            "scenarios": [Path(p).name for p in self.scenario_paths],
            "reps": self.reps,
            "total_runs": total,
            "soft_abort": self.soft_abort,
            "duration_seconds": duration,
            "results": self.run_results,
        }
        (self.results_dir / "experiment_summary.json").write_text(json.dumps(summary, indent=2))

        # Run offline aggregator and write aggregate.json
        try:
            agg = aggregate_experiment(str(self.results_dir))
            (self.results_dir / "aggregate.json").write_text(json.dumps(agg, indent=2))
        except Exception as e:
            print(f"WARN: aggregate failed: {e}", file=sys.stderr)

        return summary


def main() -> None:
    # Auto-load .env from the current working directory so `python -m
    # ablations.experiment` picks up ANTHROPIC_API_KEY without requiring the
    # user to `export` it separately. load_dotenv defaults to override=False,
    # so an explicitly-exported value in the shell still wins.
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run a BFT voting experiment")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--results-root", default="results")
    parser.add_argument(
        "--workspace-dir",
        default="/tmp/bft-workspace",
        help="Host directory shared with judge containers as /workspace (default: /tmp/bft-workspace)",
    )
    parser.add_argument(
        "--permission-mode",
        choices=["default", "dangerous"],
        default="default",
        help=(
            "Claude Code permission mode for the runner agent. "
            "'dangerous' appends --dangerously-skip-permissions so the "
            "agent auto-approves every tool call (the threat model "
            "supply-chain attacks specifically target). Default behavior "
            "preserves the existing hook-mediated approval path."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help=(
            "Per-scenario hard timeout in seconds for the runner agent. "
            "If the agent neither exits naturally nor triggers a canary "
            "within this budget the container is killed and the run is "
            "classified as agent_hung. Default 120s — postinstall trojans "
            "fire within ~30s; longer agents are usually stuck on a "
            "long-running command (npm run dev, etc)."
        ),
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY not set. "
            "Put it in .env (the driver auto-loads .env from the cwd) or export it.",
            file=sys.stderr,
        )
        sys.exit(1)

    runner = ExperimentRunner(
        ablation_config_path=args.config,
        scenario_paths=args.scenarios,
        reps=args.reps,
        max_concurrency=args.max_concurrency,
        api_key=api_key,
        results_root=args.results_root,
        workspace_dir=args.workspace_dir,
        permission_mode=args.permission_mode,
        timeout_seconds=args.timeout,
    )
    summary = asyncio.run(runner.run())

    # Roll up costs across all scenario runs in this experiment.
    agent_cost = sum(
        float(r.get("agent_cost_usd") or 0.0) for r in summary.get("results", [])
    )
    judge_cost = sum(
        float(r.get("judgments_summary", {}).get("total_cost_usd") or 0.0)
        for r in summary.get("results", [])
    )
    print(json.dumps({
        "ablation": summary["ablation"],
        "total_runs": summary["total_runs"],
        "soft_abort": summary["soft_abort"],
        "duration_seconds": round(summary["duration_seconds"], 1),
        "cost_usd": {
            "agent": round(agent_cost, 4),
            "judges": round(judge_cost, 4),
            "total": round(agent_cost + judge_cost, 4),
        },
    }, indent=2))
    sys.exit(1 if summary["soft_abort"] else 0)


if __name__ == "__main__":
    main()
