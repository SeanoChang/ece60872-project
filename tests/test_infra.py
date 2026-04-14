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
