"""API proxy that sits between containers and api.anthropic.com.

Containers set ANTHROPIC_BASE_URL to point at this proxy.  The proxy
injects the real API key into every request, enforces per-agent budgets,
and logs all traffic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Per-model pricing (USD per token)
# ---------------------------------------------------------------------------

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_token, output_per_token)
    "claude-opus-4-6": (15.0 / 1e6, 75.0 / 1e6),
    "claude-sonnet-4-6": (3.0 / 1e6, 15.0 / 1e6),
    "claude-haiku-4-5": (0.80 / 1e6, 4.0 / 1e6),
}

# Fallback if model not recognized
_DEFAULT_PRICING = (3.0 / 1e6, 15.0 / 1e6)  # Sonnet pricing

_ANTHROPIC_BASE = "https://api.anthropic.com"


def _get_pricing(model_id: str) -> tuple[float, float]:
    """Return (input_cost_per_token, output_cost_per_token) for a model ID.

    Matches on prefix so 'claude-sonnet-4-6-20260101' hits 'claude-sonnet-4-6'.
    """
    for prefix, pricing in _MODEL_PRICING.items():
        if model_id.startswith(prefix):
            return pricing
    return _DEFAULT_PRICING


class ApiProxy:
    """Reverse proxy that injects the real API key and enforces per-agent budgets.

    Parameters
    ----------
    host:
        Interface to listen on.
    port:
        Port to bind.  Pass 0 to let the OS choose a free port; the actual
        port is available as ``self.port`` after ``await start()``.
    api_key:
        Real Anthropic API key to inject into forwarded requests.
    budgets:
        Mapping from agent_id to spend limit in USD, e.g.
        ``{"agent-main": 5.0, "judge-a": 0.50}``.
    log_path:
        File path for JSONL log of every proxied request.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8081,
        api_key: str = "",
        budgets: dict[str, float] | None = None,
        log_path: str = "results/proxy.jsonl",
    ) -> None:
        self.host = host
        self._requested_port = port
        self.port: int = port  # updated after bind when port=0
        self._api_key = api_key
        self._budgets: dict[str, float] = budgets or {}
        self.log_path = log_path

        # Cumulative USD spend per agent_id
        self._spend: dict[str, float] = {agent: 0.0 for agent in self._budgets}

        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=120.0)
        self._app = self._build_app()
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_spend(self, agent_id: str) -> float:
        """Return the cumulative USD spend for *agent_id* (0.0 if unknown)."""
        return self._spend.get(agent_id, 0.0)

    async def start(self) -> None:
        """Start the uvicorn server and wait until it is accepting connections."""
        config = uvicorn.Config(
            app=self._app,
            host=self.host,
            port=self._requested_port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())

        while not self._server.started:
            await asyncio.sleep(0.05)

        if self._requested_port == 0:
            sockets = self._server.servers[0].sockets
            self.port = sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Gracefully shut down the uvicorn server and close the HTTP client."""
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await self._task
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Helper methods (testable without HTTP)
    # ------------------------------------------------------------------

    def _inject_headers(self, original_headers: dict) -> dict:
        """Return a new header dict with x-api-key injected and x-judge-id/host stripped.

        Parameters
        ----------
        original_headers:
            Headers as received from the container (keys may be any case).

        Returns
        -------
        dict
            Modified headers suitable for forwarding to api.anthropic.com.
        """
        result: dict[str, str] = {}
        for key, value in original_headers.items():
            lower = key.lower()
            if lower in ("x-judge-id", "host"):
                continue
            result[key] = value
        result["x-api-key"] = self._api_key
        return result

    def _check_budget(self, agent_id: str) -> bool:
        """Return True if *agent_id* is within its budget, False otherwise.

        An unknown agent_id (not present in ``self._budgets``) always returns
        False — we deny unknown callers.

        Note: this is a soft cap checked before each request. The actual cost
        is tracked after the response. A single large request can overshoot
        the budget. This is acceptable for experiment budgeting.
        """
        if agent_id not in self._budgets:
            return False
        limit = self._budgets[agent_id]
        current = self._spend.get(agent_id, 0.0)
        return current < limit

    def _track_spend(self, agent_id: str, response_body: dict) -> float:
        """Parse *response_body* for token usage, compute cost, and update cumulative spend.

        Parameters
        ----------
        agent_id:
            The agent whose budget to charge.
        response_body:
            Parsed JSON dict returned by api.anthropic.com.

        Returns
        -------
        float
            The cost (in USD) computed from this response, or 0.0 if no usage
            field is present.
        """
        usage = response_body.get("usage")
        if not usage:
            return 0.0

        model_id = response_body.get("model", "")
        input_price, output_price = _get_pricing(model_id)

        input_tokens: int = usage.get("input_tokens", 0)
        output_tokens: int = usage.get("output_tokens", 0)
        cost = input_tokens * input_price + output_tokens * output_price

        if agent_id in self._spend:
            self._spend[agent_id] += cost
        else:
            self._spend[agent_id] = cost

        return cost

    # ------------------------------------------------------------------
    # Internal — FastAPI app
    # ------------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.api_route(
            "/{path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        )
        async def proxy_request(path: str, request: Request) -> Response:
            agent_id = request.headers.get("x-judge-id", "")

            # Budget check (soft cap — actual cost tracked after response)
            if not self._check_budget(agent_id):
                return JSONResponse(
                    content={"error": "budget_exceeded", "agent_id": agent_id},
                    status_code=429,
                )

            # Build forwarded headers
            forward_headers = self._inject_headers(dict(request.headers))

            # Forward to Anthropic
            body_bytes = await request.body()
            upstream_url = f"{_ANTHROPIC_BASE}/{path}"
            if request.url.query:
                upstream_url += f"?{request.url.query}"

            upstream_resp = await self._client.request(
                method=request.method,
                url=upstream_url,
                headers=forward_headers,
                content=body_bytes,
            )

            # Parse response body for cost tracking
            try:
                resp_json: dict[str, Any] = upstream_resp.json()
            except Exception:
                resp_json = {}

            cost = self._track_spend(agent_id, resp_json)

            # Log the transaction
            self._append_log(
                agent_id=agent_id,
                method=request.method,
                path="/" + path,
                cost_usd=cost,
                cumulative_spend=self.get_spend(agent_id),
                budget_limit=self._budgets.get(agent_id),
            )

            return Response(
                content=upstream_resp.content,
                status_code=upstream_resp.status_code,
                headers=dict(upstream_resp.headers),
                media_type=upstream_resp.headers.get("content-type"),
            )

        return app

    def _append_log(
        self,
        *,
        agent_id: str,
        method: str,
        path: str,
        cost_usd: float,
        cumulative_spend: float,
        budget_limit: float | None,
    ) -> None:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "method": method,
            "path": path,
            "cost_usd": cost_usd,
            "cumulative_spend": cumulative_spend,
            "budget_limit": budget_limit,
        }
        log_path = Path(self.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run the ApiProxy standalone.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8081, help="Bind port (default: 8081)")
    parser.add_argument(
        "--log-path",
        default="results/proxy.jsonl",
        help="JSONL log output path",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not set; requests will be forwarded without a key.")

    default_budgets: dict[str, float] = {
        "agent-main": 5.0,
        "judge-a": 0.50,
        "judge-b": 0.50,
        "judge-c": 0.50,
    }

    proxy = ApiProxy(
        host=args.host,
        port=args.port,
        api_key=api_key,
        budgets=default_budgets,
        log_path=args.log_path,
    )

    async def _run() -> None:
        await proxy.start()
        print(
            f"ApiProxy listening on {proxy.host}:{proxy.port}  "
            f"(log → {proxy.log_path})"
        )
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await proxy.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _main()
