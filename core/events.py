from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


def new_event_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class _EventBase(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(default_factory=new_event_id)
    timestamp: str = Field(default_factory=_now_iso)
    run_id: str
    scenario_run_id: str | None = None
    judgment_id: str | None = None
    ablation: str


class ExperimentStart(_EventBase):
    event_type: Literal["experiment_start"] = "experiment_start"
    scenarios: list[str]
    reps: int
    max_concurrency: int
    judge_configs: list[dict[str, Any]]


class ExperimentEnd(_EventBase):
    event_type: Literal["experiment_end"] = "experiment_end"
    total_runs: int
    duration_seconds: float
    soft_abort: bool


class ScenarioRunStart(_EventBase):
    event_type: Literal["scenario_run_start"] = "scenario_run_start"
    scenario_id: str
    scenario_path: str
    rep: int
    canaries_planted: dict[str, str]


class ScenarioRunEnd(_EventBase):
    event_type: Literal["scenario_run_end"] = "scenario_run_end"
    scenario_id: str
    scenario_path: str
    rep: int
    agent_return_code: int
    agent_duration_seconds: float
    honeypot_saw_canary: bool
    outcome: Literal[
        "attack_succeeded",
        "attack_blocked",
        "false_positive",
        "benign_completed",
        "already_solved",
        "infra_failed",
    ]


class Judgment(_EventBase):
    event_type: Literal["judgment"] = "judgment"
    tool_call: dict
    votes: list[dict]
    decision: Literal["approve", "reject"]
    quorum_rule: str
    phase_timings_ms: dict[str, float]
    total_latency_ms: float
    total_cost_usd: float


class HoneypotRequest(_EventBase):
    event_type: Literal["honeypot_request"] = "honeypot_request"
    method: str
    path: str
    body_preview: str
    canary_match: bool
    real_key_match: bool
    matched_canaries: list[str]


class ApiCall(_EventBase):
    event_type: Literal["api_call"] = "api_call"
    agent_id: str
    method: str
    path: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cumulative_spend: float = 0.0
    budget_limit: float = 0.0
    upstream_status: int = 0


class Inspection(_EventBase):
    """Inspection-signal record per scenario run.

    Computed by ``analysis/inspection.py`` from the agent's stream-json after
    each scenario run finishes. Implements docs/measurement-spec.md §3 (strict)
    and §4 (loose) — see that spec for definitions and edge cases.
    """
    event_type: Literal["inspection"] = "inspection"
    scenario_id: str
    scenario_path: str
    rep: int
    trojan_file: str
    inspection_targets: list[str]
    strict_read_index: int | None = None
    loose_read_index: int | None = None
    dangerous_call_index: int | None = None
    strict_read_via: str = ""
    loose_read_via: str = ""
    dangerous_call_command: str = ""
    execution_occurred: bool
    strict_inspection: bool
    loose_inspection: bool


AnyEvent = Union[
    ExperimentStart,
    ExperimentEnd,
    ScenarioRunStart,
    ScenarioRunEnd,
    Judgment,
    HoneypotRequest,
    ApiCall,
    Inspection,
]
