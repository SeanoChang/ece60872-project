import asyncio
import pytest
from core.correlation import (
    new_run_id, new_scenario_run_id, new_judgment_id,
    current_run_id, current_scenario_run_id, current_judgment_id,
    correlation_context,
)


def test_new_run_id_has_prefix():
    rid = new_run_id()
    assert rid.startswith("exp-")


def test_new_scenario_run_id_has_rep():
    srid = new_scenario_run_id("my-scenario", 3)
    assert "my-scenario" in srid
    assert "rep3" in srid


def test_new_judgment_id_has_prefix():
    jid = new_judgment_id()
    assert jid.startswith("j-")


def test_correlation_context_sets_ids():
    with correlation_context(
        run_id="exp-test", scenario_run_id="sr-test", judgment_id="j-test"
    ):
        assert current_run_id() == "exp-test"
        assert current_scenario_run_id() == "sr-test"
        assert current_judgment_id() == "j-test"


def test_correlation_context_restores_on_exit():
    assert current_run_id() is None
    with correlation_context(run_id="exp-a"):
        assert current_run_id() == "exp-a"
    assert current_run_id() is None


@pytest.mark.asyncio
async def test_correlation_isolates_between_tasks():
    """Concurrent tasks in the same event loop see their own IDs."""
    async def task(rid: str) -> str:
        with correlation_context(run_id=rid):
            await asyncio.sleep(0.01)
            return current_run_id() or ""

    results = await asyncio.gather(*[task(f"r-{i}") for i in range(5)])
    assert results == [f"r-{i}" for i in range(5)]
