from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

from core.correlation import new_run_id, new_scenario_run_id, correlation_context
from core.events import (
    ExperimentStart, ExperimentEnd, ScenarioRunStart, ScenarioRunEnd,
)
from core.infra import InfrastructureServices
from core.judge_containers import JudgeContainerManager
from core.logger import JSONLLogger
from core.runner_agent import RunnerAgentConfig, run_runner_agent
from core.scenario import load_scenario, render_workspace
from analysis.ground_truth import match_patterns, classify_scenario_outcome
from analysis.aggregate import aggregate_experiment
from core.stream_parser import extract_tool_calls as _extract_from_stream


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
        cmd = [
            "docker", "run", "-d", "--name", cfg["name"],
            "--add-host=host.docker.internal:host-gateway",
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

            honeypot_saw_canary = self._check_honeypot_for_canaries(scenario_run_id)

            outcome = classify_scenario_outcome(
                dangerous_matched=len(dangerous_matches),
                benign_matched=len(benign_matches),
                honeypot_saw_canary=honeypot_saw_canary,
                agent_return_code=rc,
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

            # Print runtime summary line for post-hoc review
            print(
                f"[{self.ablation_name}] {scenario.scenario_id}_rep{rep} → "
                f"{outcome} (duration={run_duration:.1f}s, rc={rc})",
                flush=True,
            )

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
            }

            result_file = self.results_dir / "scenarios" / f"{run_id_str}.json"
            result_file.write_text(json.dumps(result, indent=2))
            return result

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
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    runner = ExperimentRunner(
        ablation_config_path=args.config,
        scenario_paths=args.scenarios,
        reps=args.reps,
        max_concurrency=args.max_concurrency,
        api_key=api_key,
        results_root=args.results_root,
        workspace_dir=args.workspace_dir,
    )
    summary = asyncio.run(runner.run())
    print(json.dumps({
        "ablation": summary["ablation"],
        "total_runs": summary["total_runs"],
        "soft_abort": summary["soft_abort"],
        "duration_seconds": round(summary["duration_seconds"], 1),
    }, indent=2))
    sys.exit(1 if summary["soft_abort"] else 0)


if __name__ == "__main__":
    main()
