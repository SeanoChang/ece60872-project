"""Core dataclasses for the BFT voting guardrail system."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# ToolCall — represents a single tool invocation intercepted by a PreToolUse hook
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """Immutable record of a tool call received from a Claude Code PreToolUse hook."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    session_id: str
    cwd: str = ""

    @property
    def command(self) -> str:
        """Return the primary string argument: 'command' for Bash, 'file_path' for file tools."""
        return self.tool_input.get("command", self.tool_input.get("file_path", ""))

    @classmethod
    def from_hook_payload(cls, payload: dict[str, Any]) -> ToolCall:
        """Construct a ToolCall from the JSON payload Claude Code sends to PreToolUse hooks.

        Expected payload keys (as emitted by Claude Code hook stdin):
            toolName    — name of the tool being called
            toolUseId   — unique ID for this tool use
            sessionId   — Claude Code session identifier
            cwd         — working directory at time of call
            tool_input  — dict of arguments passed to the tool
        """
        return cls(
            tool_name=payload["toolName"],
            tool_input=payload.get("tool_input", {}),
            tool_use_id=payload["toolUseId"],
            session_id=payload["sessionId"],
            cwd=payload.get("cwd", ""),
        )


# ---------------------------------------------------------------------------
# JudgeConfig — static configuration for a single judge
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeConfig:
    """Immutable configuration for a judge (honest or Byzantine)."""

    name: str
    model: str
    system_prompt_path: str
    temperature: float = 0.0
    role: Literal["param", "intent", "threat", "general"] = "general"
    is_byzantine: bool = False
    compromise_variant: str = ""
    mode: Literal["stateless", "agentic"] = "stateless"
    timeout_seconds: int = 15

    @property
    def prompt_hash(self) -> str:
        """Return the SHA-256 hex digest of the file at system_prompt_path."""
        content = open(self.system_prompt_path, encoding="utf-8").read()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# JudgeVote — one judge's verdict on a single ToolCall
# ---------------------------------------------------------------------------


@dataclass
class JudgeVote:
    """Mutable record of a single judge's verdict for one ToolCall evaluation."""

    judge_name: str
    model_id: str
    decision: Literal["approve", "reject"]
    confidence: float
    reason: str
    investigation_steps: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    is_byzantine: bool = False


# ---------------------------------------------------------------------------
# VoteResult — aggregated outcome from all judges for one ToolCall
# ---------------------------------------------------------------------------


@dataclass
class VoteResult:
    """Mutable aggregated result produced by the voting orchestrator."""

    decision: Literal["approve", "reject"]
    votes: list[JudgeVote]
    quorum_rule: str
    total_latency_ms: float
    total_cost_usd: float
