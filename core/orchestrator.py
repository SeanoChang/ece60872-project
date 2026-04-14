"""Orchestrator — FastAPI server that receives tool call JSON from the judge hook,
dispatches judges in parallel, collects votes, applies majority rule, and returns
the decision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import deque
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.agentic_judge import run_agentic_judge
from core.judge_agent import StatelessJudge
from core.logger import JSONLLogger
from core.types import JudgeConfig, JudgeVote, ToolCall, VoteResult
from core.voting import majority_vote


# ---------------------------------------------------------------------------
# run_judges helper
# ---------------------------------------------------------------------------


async def run_judges(
    tool_call: ToolCall,
    judge_configs: list[JudgeConfig],
    memory: list[dict] | None = None,
) -> list[JudgeVote]:
    """Dispatch judges in parallel — stateless via API, agentic via docker exec."""
    tasks = []
    context: dict[str, Any] | None = {"memory": memory} if memory else None

    for config in judge_configs:
        if config.mode == "agentic":
            tasks.append(run_agentic_judge(
                container_name=f"judge-{config.name}",
                tool_call=tool_call,
                judge_name=config.name,
                model_id=config.model,
            ))
        else:
            judge = StatelessJudge(config)
            tasks.append(judge.evaluate(tool_call, context))

    return list(await asyncio.gather(*tasks))


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------


def create_app(config: dict) -> FastAPI:
    """Create and return a FastAPI application configured for the given ablation config.

    Parameters
    ----------
    config:
        Ablation configuration dict with keys:
            ablation    — ablation label string
            judges      — list of judge config dicts
            memory_window — (optional) int, rolling window size (default 10)
            log_path    — path to the JSONL log file
    """
    app = FastAPI(title="BFT Voting Orchestrator")

    # Build JudgeConfig objects from the config dicts
    judge_configs: list[JudgeConfig] = [
        JudgeConfig(
            name=j["name"],
            model=j["model"],
            system_prompt_path=j["system_prompt_path"],
            temperature=j.get("temperature", 0.0),
            role=j.get("role", "general"),
            is_byzantine=j.get("is_byzantine", False),
            compromise_variant=j.get("compromise_variant", ""),
            mode=j.get("mode", "stateless"),
            timeout_seconds=j.get("timeout_seconds", 15),
        )
        for j in config.get("judges", [])
    ]

    memory_window: int = config.get("memory_window", 10)
    log_path: str = config.get("log_path", "logs/orchestrator.jsonl")
    logger = JSONLLogger(log_path)

    # Rolling memory of recent tool call records
    memory: deque[dict] = deque(maxlen=memory_window)
    # judgment_counter not needed — judges self-manage their memory

    # ------------------------------------------------------------------
    # POST /judge
    # ------------------------------------------------------------------

    @app.post("/judge")
    async def judge(payload: dict) -> JSONResponse:
        """Receive a PreToolUse hook payload, dispatch judges, and return the decision."""
        tool_call = ToolCall.from_hook_payload(payload)

        # Dispatch judges in parallel
        t0 = time.time()
        votes: list[JudgeVote] = await run_judges(
            tool_call,
            judge_configs,
            memory=list(memory) if memory else None,
        )

        # Aggregate via majority vote
        result: VoteResult = majority_vote(votes)
        total_latency_ms = (time.time() - t0) * 1000

        # Build the log record
        judge_records = [
            {
                "judge_name": v.judge_name,
                "model": v.model_id,
                "decision": v.decision,
                "confidence": v.confidence,
                "reason": v.reason,
                "is_byzantine": v.is_byzantine,
                "latency_ms": v.latency_ms,
                "cost_usd": v.cost_usd,
            }
            for v in votes
        ]

        log_record: dict[str, Any] = {
            "timestamp": time.time(),
            "session_id": tool_call.session_id,
            "ablation": config.get("ablation", ""),
            "tool_call": {
                "tool_name": tool_call.tool_name,
                "tool_input": tool_call.tool_input,
            },
            "judges": judge_records,
            "decision": result.decision,
            "quorum_rule": result.quorum_rule,
            "total_latency_ms": result.total_latency_ms,
            "total_cost_usd": result.total_cost_usd,
        }

        # Append to rolling memory (stateless judges get this as context)
        memory.append(log_record)
        # Agentic judges self-manage their MEMORY.md — no orchestrator injection

        # Persist to JSONL
        logger.append(log_record)

        # Build response
        response_body = {
            "decision": result.decision,
            "reason": next(
                (v.reason for v in votes if v.decision == result.decision), ""
            ),
            "votes": [
                {
                    "judge": v.judge_name,
                    "decision": v.decision,
                    "confidence": v.confidence,
                }
                for v in votes
            ],
        }

        return JSONResponse(content=response_body)

    # ------------------------------------------------------------------
    # GET /health
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> JSONResponse:
        """Return server health status and judge count."""
        return JSONResponse(content={"status": "ok", "judges": len(judge_configs)})

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="BFT Voting Orchestrator")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to ablation config JSON file",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        ablation_config = json.load(f)

    app = create_app(ablation_config)
    uvicorn.run(app, host=args.host, port=args.port)
