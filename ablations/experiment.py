from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from core.infra import InfrastructureServices
from core.judge_containers import JudgeContainerManager
from core.runner_agent import RunnerAgentConfig, run_runner_agent
from core.scenario import load_scenario, render_workspace


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

        # Write an effective config that carries the runtime transcript_dir
        self.ablation["transcript_dir"] = str(transcript_dir)
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
        )

        self.run_results: list[dict] = []
        self.soft_abort: bool = False

    async def _setup(self) -> None:
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
                    try:
                        return await self._run_scenario_rep(scenario_path, rep)
                    except Exception as second:
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
        canaries = render_workspace(scenario, self.container_mgr.workspace_dir)

        runner_cfg = RunnerAgentConfig(
            image=self.agent_image,
            workspace_host_dir=self.container_mgr.workspace_dir,
            task_prompt=scenario.task_prompt,
            proxy_url="http://host.docker.internal:8081",
            orchestrator_url="http://host.docker.internal:8080",
        )

        run_start = time.time()
        rc, stdout, stderr = await run_runner_agent(runner_cfg)
        run_duration = time.time() - run_start

        # Write full stdout / stderr to separate files (no truncation)
        run_id = f"{scenario.scenario_id}_rep{rep}"
        stdout_file = self.results_dir / "scenarios" / f"{run_id}.stdout"
        stderr_file = self.results_dir / "scenarios" / f"{run_id}.stderr"
        stdout_file.write_bytes(stdout)
        stderr_file.write_bytes(stderr)

        result = {
            "scenario_id": scenario.scenario_id,
            "scenario_path": scenario_path,
            "rep": rep,
            "agent_return_code": rc,
            "agent_duration_seconds": round(run_duration, 2),
            "stdout_path": str(stdout_file),
            "stderr_path": str(stderr_file),
            "canaries": canaries,
            "timestamp": run_start,
        }

        result_file = self.results_dir / "scenarios" / f"{run_id}.json"
        result_file.write_text(json.dumps(result, indent=2))
        return result

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
        start_time = time.time()
        try:
            await self._setup()
            await self._execute()
        except Exception as e:
            self.soft_abort = True
            self.run_results.append({"status": "setup_failed", "error": str(e)})
        finally:
            await self._teardown()

        total = len([r for r in self.run_results if r.get("status") != "setup_failed"])
        summary = {
            "ablation": self.ablation_name,
            "scenarios": [Path(p).name for p in self.scenario_paths],
            "reps": self.reps,
            "total_runs": total,
            "soft_abort": self.soft_abort,
            "duration_seconds": time.time() - start_time,
            "results": self.run_results,
        }
        (self.results_dir / "experiment_summary.json").write_text(json.dumps(summary, indent=2))
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a BFT voting experiment")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--results-root", default="results")
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
