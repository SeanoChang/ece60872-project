"""core/infra.py — manages proxy/honeypot/orchestrator subprocesses."""
import asyncio
import os
import secrets
import signal
import time
from pathlib import Path

import httpx


# Env-var allowlist for subprocesses. Prevents leakage of unrelated credentials
# (AWS_*, GCP_*, etc.) from the researcher's shell into spawned services.
_ENV_ALLOW_PREFIXES: tuple[str, ...] = ("BFT_", "LC_", "LANG", "CONDA_")
_ENV_ALLOW_EXACT: frozenset[str] = frozenset({
    "PATH", "HOME", "USER", "TERM", "SHELL", "PYTHONPATH", "PYTHONHOME",
    "PWD", "TMPDIR", "TZ",
})


async def wait_for_health(
    url: str,
    timeout_seconds: float,
    poll_interval: float = 1.0,
) -> bool:
    """Poll *url* until it returns HTTP 200 or the deadline is reached.

    Returns True on the first HTTP 200 response, False if the timeout elapses
    without a successful response.
    """
    deadline = time.monotonic() + timeout_seconds

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return True
            except Exception:
                pass

            if time.monotonic() >= deadline:
                return False

            await asyncio.sleep(poll_interval)


class InfrastructureServices:
    """Manages the proxy, honeypot, and orchestrator subprocesses."""

    def __init__(
        self,
        api_key: str,
        results_dir: str,
        orchestrator_config_path: str,
        proxy_port: int = 8081,
        honeypot_port: int = 9999,
        orchestrator_port: int = 8080,
        run_id: str = "",
        ablation: str = "",
    ) -> None:
        self.api_key = api_key
        self.orchestrator_config_path = orchestrator_config_path
        self.proxy_port = proxy_port
        self.honeypot_port = honeypot_port
        self.orchestrator_port = orchestrator_port
        self.run_id = run_id
        self.ablation = ablation

        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.events_dir = self.results_dir / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)

        # Shared secret for privileged honeypot endpoints (e.g. /_register_canary).
        # Fresh per experiment run so a leaked token dies with the run.
        self.admin_token: str = secrets.token_urlsafe(32)

        self._procs: list[asyncio.subprocess.Process] = []

    def _build_subprocess_env(self) -> dict[str, str]:
        """Return an env dict with experiment-level config propagated to subprocesses.

        Uses an allowlist to prevent unrelated credentials in the researcher's
        shell environment from leaking into spawned services.
        """
        env: dict[str, str] = {
            k: v for k, v in os.environ.items()
            if k in _ENV_ALLOW_EXACT or any(k.startswith(p) for p in _ENV_ALLOW_PREFIXES)
        }
        env["ANTHROPIC_API_KEY"] = self.api_key
        env["BFT_RUN_ID"] = self.run_id
        env["BFT_ABLATION"] = self.ablation
        env["BFT_EVENTS_DIR"] = str(self.events_dir)
        env["BFT_ADMIN_TOKEN"] = self.admin_token
        return env

    async def start(self) -> None:
        """Start all three infrastructure subprocesses and wait for health."""
        env = self._build_subprocess_env()

        proxy_log = open(self.results_dir / "proxy.log", "wb")
        honeypot_log = open(self.results_dir / "honeypot.log", "wb")
        orchestrator_log = open(self.results_dir / "orchestrator.log", "wb")

        # Bind to 0.0.0.0 so Linux Docker containers can reach the services via
        # `host.docker.internal:host-gateway` (maps to the bridge gateway IP, not
        # loopback). CLI defaults remain 127.0.0.1 for standalone invocation.
        proxy_proc = await asyncio.create_subprocess_exec(
            "python", "-m", "core.api_proxy",
            "--host", "0.0.0.0",
            "--port", str(self.proxy_port),
            stdout=proxy_log,
            stderr=proxy_log,
            env=env,
        )

        honeypot_proc = await asyncio.create_subprocess_exec(
            "python", "-m", "core.honeypot",
            "--host", "0.0.0.0",
            "--port", str(self.honeypot_port),
            stdout=honeypot_log,
            stderr=honeypot_log,
            env=env,
        )

        orchestrator_proc = await asyncio.create_subprocess_exec(
            "python", "-m", "core.orchestrator",
            "--config", self.orchestrator_config_path,
            "--host", "0.0.0.0",
            "--port", str(self.orchestrator_port),
            stdout=orchestrator_log,
            stderr=orchestrator_log,
            env=env,
        )

        self._procs = [proxy_proc, honeypot_proc, orchestrator_proc]

        # Await orchestrator and honeypot health in parallel.
        # (api_proxy does not yet expose /health; omitted here.)
        orch_healthy, honey_healthy = await asyncio.gather(
            wait_for_health(
                f"http://localhost:{self.orchestrator_port}/health",
                timeout_seconds=60,
            ),
            wait_for_health(
                f"http://localhost:{self.honeypot_port}/health",
                timeout_seconds=60,
            ),
        )

        if not orch_healthy:
            await self.stop()
            raise RuntimeError("Orchestrator did not become healthy within 60s")
        if not honey_healthy:
            await self.stop()
            raise RuntimeError("Honeypot did not become healthy within 60s")

    async def stop(self) -> None:
        """Send SIGTERM to all subprocesses and wait for them to exit."""
        for proc in self._procs:
            if proc.returncode is None:
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass

        for proc in self._procs:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        self._procs = []
