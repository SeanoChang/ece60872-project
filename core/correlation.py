from __future__ import annotations

import contextlib
import time
import uuid
from contextvars import ContextVar

_run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
_scenario_run_id_var: ContextVar[str | None] = ContextVar("scenario_run_id", default=None)
_judgment_id_var: ContextVar[str | None] = ContextVar("judgment_id", default=None)


def _short() -> str:
    return uuid.uuid4().hex[:8]


def new_run_id() -> str:
    return f"exp-{int(time.time() * 1000)}-{_short()}"


def new_scenario_run_id(scenario_id: str, rep: int) -> str:
    return f"{scenario_id}-rep{rep}-{_short()}"


def new_judgment_id() -> str:
    return f"j-{int(time.time() * 1000)}-{_short()}"


def current_run_id() -> str | None:
    return _run_id_var.get()


def current_scenario_run_id() -> str | None:
    return _scenario_run_id_var.get()


def current_judgment_id() -> str | None:
    return _judgment_id_var.get()


@contextlib.contextmanager
def correlation_context(
    *,
    run_id: str | None = None,
    scenario_run_id: str | None = None,
    judgment_id: str | None = None,
):
    """Set correlation IDs for the duration of the context, then restore."""
    tokens = []
    if run_id is not None:
        tokens.append(_run_id_var.set(run_id))
    if scenario_run_id is not None:
        tokens.append(_scenario_run_id_var.set(scenario_run_id))
    if judgment_id is not None:
        tokens.append(_judgment_id_var.set(judgment_id))
    try:
        yield
    finally:
        for tok in reversed(tokens):
            var = tok.var
            var.reset(tok)
