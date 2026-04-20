"""Orchestrator — FastAPI server that receives tool call JSON from the judge hook,
dispatches judges in parallel, collects votes, applies majority rule, and returns
the decision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.agentic_judge import run_agentic_judge
from core.correlation import (
    correlation_context,
    current_run_id,
    current_scenario_run_id,
    new_judgment_id,
)
from core.events import Judgment
from core.logger import JSONLLogger
from core.types import JudgeConfig, JudgeVote, ToolCall, VoteResult
from core.voting import majority_vote


# ---------------------------------------------------------------------------
# run_judges helper
# ---------------------------------------------------------------------------


# Stagger between sequential judge launches (seconds). Three concurrent
# Claude Code investigations hitting the proxy at the same instant routinely
# exceeded the Anthropic Tier 1 limit of 30,000 input tokens per minute and
# one judge would 429-fail at CLI startup with 0 bytes output. Staggering the
# dispatches by a few seconds lets each judge's initial prompt + context load
# clear the TPM bucket before the next one starts; judges still overlap for
# most of their investigation, so wall-clock parallelism is preserved.
_JUDGE_STAGGER_SECONDS: float = 3.0


async def _launch_judge_with_delay(
    delay: float,
    *,
    container_name: str,
    tool_call: ToolCall,
    judge_name: str,
    model_id: str,
    transcript_dir: str | None,
) -> JudgeVote:
    if delay > 0:
        await asyncio.sleep(delay)
    return await run_agentic_judge(
        container_name=container_name,
        tool_call=tool_call,
        judge_name=judge_name,
        model_id=model_id,
        transcript_dir=transcript_dir,
    )


async def run_judges(
    tool_call: ToolCall,
    judge_configs: list[JudgeConfig],
    transcript_dir: str | None = None,
) -> list[JudgeVote]:
    """Dispatch agentic judges in parallel via docker exec, staggered to respect TPM limits."""
    tasks = [
        _launch_judge_with_delay(
            delay=i * _JUDGE_STAGGER_SECONDS,
            container_name=f"judge-{config.name}",
            tool_call=tool_call,
            judge_name=config.name,
            model_id=config.model,
            transcript_dir=transcript_dir,
        )
        for i, config in enumerate(judge_configs)
    ]
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
            timeout_seconds=j.get("timeout_seconds", 15),
        )
        for j in config.get("judges", [])
    ]

    log_path: str = config.get("log_path", "logs/orchestrator.jsonl")
    logger = JSONLLogger(log_path)
    events_dir: str | None = config.get("events_dir")

    # ------------------------------------------------------------------
    # POST /judge
    # ------------------------------------------------------------------

    # Directory where judges write their claude -p transcripts
    transcript_dir_path = config.get("transcript_dir")

    @app.post("/judge")
    async def judge(payload: dict, request: Request) -> JSONResponse:
        """Receive a PreToolUse hook payload, dispatch judges, and return the decision."""
        # A0 short-circuit: an empty judge panel means "agent alone, no guard."
        # Auto-approve every tool call and return immediately — no correlation
        # context is opened, no judgment event is emitted, because A0's
        # semantics are "panel was never involved." Emitting a judgment with
        # empty votes would misleadingly count A0 as a panel-exercised run.
        if not judge_configs:
            return JSONResponse(content={
                "decision": "approve",
                "reason": "A0 baseline: no judges configured; all tool calls auto-approved",
                "votes": [],
            })

        judgment_id = new_judgment_id()

        scenario_run_id = request.headers.get("x-scenario-run-id")
        run_id_hdr = request.headers.get("x-run-id")
        effective_run_id = run_id_hdr or os.environ.get("BFT_RUN_ID")

        with correlation_context(
            run_id=effective_run_id,
            scenario_run_id=scenario_run_id,
            judgment_id=judgment_id,
        ):
            hook_received_ms = time.time() * 1000
            tool_call = ToolCall.from_hook_payload(payload)

            # Dispatch judges in parallel
            t0 = time.time()
            votes: list[JudgeVote] = await run_judges(
                tool_call, judge_configs, transcript_dir=transcript_dir_path
            )

            # Aggregate via majority vote
            result: VoteResult = majority_vote(votes)
            hook_returned_ms = time.time() * 1000
            dispatch_duration_ms = (time.time() - t0) * 1000

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
                "hook_received_ms": hook_received_ms,
                "hook_returned_ms": hook_returned_ms,
                "dispatch_duration_ms": dispatch_duration_ms,
            }

            # Persist to JSONL
            logger.append(log_record)

            # Emit structured Judgment event if events_dir is configured
            if events_dir is not None:
                # Aggregate phase_timings_ms: take max across all votes per phase key
                agg_timings: dict[str, float] = {}
                for v in votes:
                    for phase, ms in v.phase_timings_ms.items():
                        if phase not in agg_timings or ms > agg_timings[phase]:
                            agg_timings[phase] = ms

                judgment_event = Judgment(
                    run_id=current_run_id() or "unknown",
                    scenario_run_id=current_scenario_run_id() or "unknown",
                    judgment_id=judgment_id,
                    ablation=config.get("ablation", ""),
                    tool_call={
                        "tool_name": tool_call.tool_name,
                        "tool_input": tool_call.tool_input,
                    },
                    votes=judge_records,
                    decision=result.decision,
                    quorum_rule=result.quorum_rule,
                    phase_timings_ms=agg_timings,
                    total_latency_ms=result.total_latency_ms,
                    total_cost_usd=result.total_cost_usd,
                )
                from pathlib import Path as _Path
                events_path = _Path(events_dir) / "judgment.jsonl"
                JSONLLogger(str(events_path)).append_event(judgment_event)

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
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1; containers reach via host.docker.internal)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        ablation_config = json.load(f)

    # Fallback: fill events_dir / ablation from env vars if not present in config
    if "events_dir" not in ablation_config:
        env_events_dir = os.environ.get("BFT_EVENTS_DIR")
        if env_events_dir:
            ablation_config["events_dir"] = env_events_dir
    if "ablation" not in ablation_config:
        env_abl = os.environ.get("BFT_ABLATION", "")
        if env_abl:
            ablation_config["ablation"] = env_abl

    app = create_app(ablation_config)
    uvicorn.run(app, host=args.host, port=args.port)
