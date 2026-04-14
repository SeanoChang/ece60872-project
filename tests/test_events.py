import pytest
from core.events import (
    ExperimentStart, ExperimentEnd, ScenarioRunStart, ScenarioRunEnd,
    Judgment, HoneypotRequest, ApiCall, new_event_id,
)


def test_experiment_start_requires_all_fields():
    ev = ExperimentStart(
        run_id="exp-1", ablation="A4",
        scenarios=["s.yaml"], reps=3, max_concurrency=2,
        judge_configs=[{"name": "param"}],
    )
    assert ev.schema_version == "1"
    assert ev.event_type == "experiment_start"
    assert len(ev.event_id) == 36  # uuid4 string length
    assert ev.scenario_run_id is None
    assert ev.judgment_id is None


def test_judgment_includes_timings():
    ev = Judgment(
        run_id="exp-1", scenario_run_id="sr-1", judgment_id="j-1",
        ablation="A4",
        tool_call={"tool_name": "Bash", "tool_input": {"command": "ls"}, "command": "ls"},
        votes=[{"judge_name": "p", "decision": "approve", "confidence": 0.9}],
        decision="approve",
        quorum_rule="majority-1",
        phase_timings_ms={"write_input_ms": 12.3, "claude_investigation_ms": 1500.0},
        total_latency_ms=1520.5,
        total_cost_usd=0.01,
    )
    assert ev.event_type == "judgment"
    assert ev.phase_timings_ms["write_input_ms"] == 12.3


def test_honeypot_request_matched_canaries():
    ev = HoneypotRequest(
        run_id="exp-1", scenario_run_id="sr-1", ablation="A4",
        method="POST", path="/exfil",
        body_preview="data=abc",
        canary_match=True, real_key_match=False,
        matched_canaries=["sk-ant-api03-CANARY-ABC"],
    )
    assert ev.canary_match is True
    assert len(ev.matched_canaries) == 1


def test_serialization_roundtrip():
    ev = ApiCall(
        run_id="exp-1", ablation="A4",
        agent_id="judge-param", method="POST", path="/v1/messages",
        model="claude-sonnet-4-6-20260101",
        input_tokens=100, output_tokens=50,
        cost_usd=0.001, cumulative_spend=0.001, budget_limit=0.5,
        upstream_status=200,
    )
    d = ev.model_dump()
    assert d["schema_version"] == "1"
    assert d["event_type"] == "api_call"
    ev2 = ApiCall(**d)
    assert ev2.agent_id == "judge-param"


def test_new_event_id_uniqueness():
    ids = {new_event_id() for _ in range(100)}
    assert len(ids) == 100
