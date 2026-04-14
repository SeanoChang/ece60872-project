"""Tests for core/infra.py — infrastructure service management."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.infra import wait_for_health, InfrastructureServices


@pytest.mark.asyncio
async def test_wait_for_health_success():
    """wait_for_health returns True when the URL responds with HTTP 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client_instance = MagicMock()
    mock_client_instance.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client_cm):
        ok = await wait_for_health("http://localhost:8080/health", timeout_seconds=2)

    assert ok is True


@pytest.mark.asyncio
async def test_wait_for_health_timeout():
    """wait_for_health returns False when connection always fails within timeout."""
    mock_client_instance = MagicMock()
    mock_client_instance.get = AsyncMock(side_effect=Exception("connection refused"))

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client_cm):
        # poll_interval=0.1 ensures at least one retry before timeout_seconds=1 elapses
        ok = await wait_for_health(
            "http://localhost:9999/health", timeout_seconds=1, poll_interval=0.1
        )

    assert ok is False


def test_infrastructure_services_init(tmp_path):
    """InfrastructureServices stores api_key and initialises _procs to empty list."""
    results_dir = str(tmp_path / "results")
    config_path = str(tmp_path / "config.json")

    svc = InfrastructureServices(
        api_key="sk-ant-TEST",
        results_dir=results_dir,
        orchestrator_config_path=config_path,
    )

    assert svc.api_key == "sk-ant-TEST"
    assert svc._procs == []


def test_build_subprocess_env_contains_bft_vars(tmp_path):
    """_build_subprocess_env returns a dict with all BFT_* env vars set correctly."""
    results_dir = str(tmp_path / "results")
    config_path = str(tmp_path / "config.json")

    svc = InfrastructureServices(
        api_key="sk-ant-TESTKEY",
        results_dir=results_dir,
        orchestrator_config_path=config_path,
        run_id="run-abc-123",
        ablation="A4",
    )

    env = svc._build_subprocess_env()

    assert env["ANTHROPIC_API_KEY"] == "sk-ant-TESTKEY"
    assert env["BFT_RUN_ID"] == "run-abc-123"
    assert env["BFT_ABLATION"] == "A4"
    assert env["BFT_EVENTS_DIR"] == str(svc.events_dir)


def test_build_subprocess_env_filters_unrelated_secrets(tmp_path, monkeypatch):
    """Shell env vars outside the allowlist do not leak into subprocess env."""
    # Inject a fake credential in the parent env — must not appear downstream.
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "hunter2-fake")
    monkeypatch.setenv("GCP_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("BFT_CUSTOM_FLAG", "allowed-through")

    svc = InfrastructureServices(
        api_key="sk-test",
        results_dir=str(tmp_path / "results"),
        orchestrator_config_path=str(tmp_path / "config.json"),
    )

    env = svc._build_subprocess_env()

    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GCP_SERVICE_ACCOUNT_JSON" not in env
    # BFT_* prefix is allowlisted
    assert env.get("BFT_CUSTOM_FLAG") == "allowed-through"
    # The explicitly-set BFT_ADMIN_TOKEN must be present and non-empty
    assert env["BFT_ADMIN_TOKEN"] == svc.admin_token
    assert len(svc.admin_token) >= 32


def test_admin_token_is_unique_per_instance(tmp_path):
    """Each InfrastructureServices instance gets a fresh admin_token."""
    svc_a = InfrastructureServices(
        api_key="k",
        results_dir=str(tmp_path / "a"),
        orchestrator_config_path=str(tmp_path / "c.json"),
    )
    svc_b = InfrastructureServices(
        api_key="k",
        results_dir=str(tmp_path / "b"),
        orchestrator_config_path=str(tmp_path / "c.json"),
    )
    assert svc_a.admin_token != svc_b.admin_token


def test_build_subprocess_env_defaults(tmp_path):
    """_build_subprocess_env works with default run_id/ablation (empty strings)."""
    results_dir = str(tmp_path / "results2")
    config_path = str(tmp_path / "config.json")

    svc = InfrastructureServices(
        api_key="sk-ant-DEFAULTKEY",
        results_dir=results_dir,
        orchestrator_config_path=config_path,
    )

    env = svc._build_subprocess_env()

    assert env["BFT_RUN_ID"] == ""
    assert env["BFT_ABLATION"] == ""
    assert "BFT_EVENTS_DIR" in env


def test_events_dir_created(tmp_path):
    """InfrastructureServices.__init__ creates the events/ subdirectory."""
    results_dir = str(tmp_path / "results3")
    config_path = str(tmp_path / "config.json")

    svc = InfrastructureServices(
        api_key="sk-ant-KEY",
        results_dir=results_dir,
        orchestrator_config_path=config_path,
    )

    assert svc.events_dir.exists()
    assert svc.events_dir.is_dir()


@pytest.mark.asyncio
async def test_infra_awaits_honeypot_health(tmp_path):
    """InfrastructureServices.start() awaits health for both orchestrator and honeypot."""
    results_dir = str(tmp_path / "results")
    config_path = str(tmp_path / "config.json")

    svc = InfrastructureServices(
        api_key="sk-ant-TEST",
        results_dir=results_dir,
        orchestrator_config_path=config_path,
        proxy_port=18081,
        honeypot_port=19999,
        orchestrator_port=18080,
    )

    # Mock subprocess creation so we don't actually spawn python processes.
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock(return_value=0)

    calls: list[str] = []

    async def fake_wait_for_health(url, timeout_seconds, poll_interval=1.0):
        calls.append(url)
        return True

    with (
        patch(
            "core.infra.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch("core.infra.wait_for_health", new=fake_wait_for_health),
    ):
        await svc.start()

    # Two health checks expected: orchestrator + honeypot.
    assert len(calls) == 2, f"expected 2 health calls, got {calls}"
    joined = " ".join(calls)
    assert ":18080/health" in joined, f"orchestrator health missing: {calls}"
    assert ":19999/health" in joined, f"honeypot health missing: {calls}"
