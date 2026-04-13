"""Judge agent — StatelessJudge (ablation-a mode).

Single-shot judge: one API call per tool call evaluation.
No tools, no memory, no sandbox — just a system prompt and the tool call.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import anthropic

from core.types import JudgeConfig, JudgeVote, ToolCall

# ---------------------------------------------------------------------------
# Pricing table (USD per million tokens) — update when models change
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    # model_prefix → (input_per_mtok, output_per_mtok)
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-0": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-3-5": (0.80, 4.0),
    "claude-3-opus": (15.0, 75.0),
    "claude-3-haiku": (0.25, 1.25),
}

_DEFAULT_PRICING = (3.0, 15.0)  # fallback: sonnet tier


def _compute_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost from token counts and model pricing."""
    input_per_m, output_per_m = _DEFAULT_PRICING
    for prefix, pricing in _PRICING.items():
        if model_id.startswith(prefix):
            input_per_m, output_per_m = pricing
            break
    return (input_tokens * input_per_m + output_tokens * output_per_m) / 1_000_000


def _parse_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from *text*, robustly.

    Strategy:
      1. Find the first ``{`` and the last ``}`` in the text.
      2. Parse that substring as JSON.
      3. Return None if no braces found or parsing fails.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class StatelessJudge:
    """Single-shot judge: one API call → one JudgeVote.

    This is the ablation (a) mode — no tools, no memory, no sandbox.
    """

    def __init__(
        self,
        config: JudgeConfig,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.config = config
        self.client = client or anthropic.AsyncAnthropic()
        self._system_prompt = Path(config.system_prompt_path).read_text()

    async def evaluate(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> JudgeVote:
        """Evaluate *tool_call* with a single LLM call and return a JudgeVote.

        Parameters
        ----------
        tool_call:
            The intercepted tool invocation to judge.
        context:
            Optional dict of past calls / memory to include in the prompt.
        """
        user_message = self._format_user_message(tool_call, context)

        t0 = time.monotonic()
        response = await self.client.messages.create(
            model=self.config.model,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=512,
            temperature=self.config.temperature,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        response_text = response.content[0].text
        model_id: str = response.model
        input_tokens: int = response.usage.input_tokens
        output_tokens: int = response.usage.output_tokens
        cost_usd = _compute_cost(model_id, input_tokens, output_tokens)

        parsed = _parse_json_from_text(response_text)
        if parsed is None:
            return JudgeVote(
                judge_name=self.config.name,
                model_id=model_id,
                decision="reject",
                confidence=0.5,
                reason="failed to parse judge output",
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                is_byzantine=self.config.is_byzantine,
            )

        decision = parsed.get("decision", "reject")
        if decision not in ("approve", "reject"):
            decision = "reject"

        return JudgeVote(
            judge_name=self.config.name,
            model_id=model_id,
            decision=decision,
            confidence=float(parsed.get("confidence", 0.5)),
            reason=str(parsed.get("reason", "")),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            is_byzantine=self.config.is_byzantine,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_user_message(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None,
    ) -> str:
        """Build the user-turn message string sent to the LLM."""
        lines: list[str] = [
            f"Tool name: {tool_call.tool_name}",
            f"Tool input: {json.dumps(tool_call.tool_input, indent=2)}",
        ]
        if context:
            lines.append(f"Context: {json.dumps(context, indent=2)}")
        lines.append(
            '\nRespond with JSON: {"decision": "approve" | "reject", '
            '"confidence": <0.0–1.0>, "reason": "<brief explanation>"}'
        )
        return "\n".join(lines)
