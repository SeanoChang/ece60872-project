"""core/infra.py — manages proxy/honeypot/orchestrator subprocesses."""
import asyncio
import os
import signal
import time
from pathlib import Path

import httpx


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
    ) -> None:
        self.api_key = api_key
        self.orchestrator_config_path = orchestrator_config_path
        self.proxy_port = proxy_port
        self.honeypot_port = honeypot_port
        self.orchestrator_port = orchestrator_port

        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self._procs: list[asyncio.subprocess.Process] = []

    async def start(self) -> None:
        """Start all three infrastructure subprocesses and wait for health."""
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = self.api_key

        proxy_log = open(self.results_dir / "proxy.log", "wb")
        honeypot_log = open(self.results_dir / "honeypot.log", "wb")
        orchestrator_log = open(self.results_dir / "orchestrator.log", "wb")

        proxy_proc = await asyncio.create_subprocess_exec(
            "python", "-m", "core.api_proxy",
            "--port", str(self.proxy_port),
            stdout=proxy_log,
            stderr=proxy_log,
            env=env,
        )

        honeypot_proc = await asyncio.create_subprocess_exec(
            "python", "-m", "core.honeypot",
            "--port", str(self.honeypot_port),
            stdout=honeypot_log,
            stderr=honeypot_log,
            env=env,
        )

        orchestrator_proc = await asyncio.create_subprocess_exec(
            "python", "-m", "core.orchestrator",
            "--config", self.orchestrator_config_path,
            "--port", str(self.orchestrator_port),
            stdout=orchestrator_log,
            stderr=orchestrator_log,
            env=env,
        )

        self._procs = [proxy_proc, honeypot_proc, orchestrator_proc]

        healthy = await wait_for_health(
            f"http://localhost:{self.orchestrator_port}/health",
            timeout_seconds=60,
        )

        if not healthy:
            await self.stop()
            raise RuntimeError("Orchestrator did not become healthy within 60s")

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
