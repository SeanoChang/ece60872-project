"""Tests for core.honeypot.HoneypotServer — written TDD-first."""
import pytest
import httpx

from core.honeypot import HoneypotServer


@pytest.fixture
async def server(tmp_path):
    """Start a honeypot on a random port, yield it, then stop it."""
    log_file = tmp_path / "honeypot.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=["CANARY-TOKEN-12345"],
    )
    await hp.start()
    yield hp
    await hp.stop()


@pytest.fixture
async def multi_canary_server(tmp_path):
    """Honeypot configured with two distinct canary patterns."""
    log_file = tmp_path / "honeypot_multi.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=["CANARY-ALPHA", "CANARY-BETA"],
    )
    await hp.start()
    yield hp
    await hp.stop()


# ---------------------------------------------------------------------------
# Test 1 — POST with canary in body → canary_match=True, HTTP 200, status ok
# ---------------------------------------------------------------------------


async def test_honeypot_logs_request(server: HoneypotServer):
    """POST with canary string in body produces canary_match=True and 200 ok."""
    base_url = f"http://127.0.0.1:{server.port}"
    async with httpx.AsyncClient(base_url=base_url) as client:
        resp = await client.post("/exfil", content="secret: CANARY-TOKEN-12345 data here")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    logs = server.get_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log["canary_match"] is True
    assert log["method"] == "POST"
    assert "exfil" in log["path"]


# ---------------------------------------------------------------------------
# Test 2 — POST with normal body → canary_match=False
# ---------------------------------------------------------------------------


async def test_honeypot_no_canary(server: HoneypotServer):
    """POST with a normal body (no canary) produces canary_match=False."""
    base_url = f"http://127.0.0.1:{server.port}"
    async with httpx.AsyncClient(base_url=base_url) as client:
        resp = await client.post("/data", content="totally normal body text")

    assert resp.status_code == 200
    logs = server.get_logs()
    assert len(logs) == 1
    assert logs[0]["canary_match"] is False


# ---------------------------------------------------------------------------
# Test 3 — GET with canary in query param → canary_match=True
# ---------------------------------------------------------------------------


async def test_honeypot_canary_in_url(server: HoneypotServer):
    """GET with canary token in query string produces canary_match=True."""
    base_url = f"http://127.0.0.1:{server.port}"
    async with httpx.AsyncClient(base_url=base_url) as client:
        resp = await client.get("/search", params={"token": "CANARY-TOKEN-12345"})

    assert resp.status_code == 200
    logs = server.get_logs()
    assert len(logs) == 1
    assert logs[0]["canary_match"] is True
    assert logs[0]["method"] == "GET"


# ---------------------------------------------------------------------------
# Test 4 — saw_canary property returns True after a canary request
# ---------------------------------------------------------------------------


async def test_honeypot_saw_canary_property(server: HoneypotServer):
    """saw_canary is False initially, True after a canary request."""
    assert server.saw_canary is False

    base_url = f"http://127.0.0.1:{server.port}"
    async with httpx.AsyncClient(base_url=base_url) as client:
        await client.post("/leak", content="CANARY-TOKEN-12345")

    assert server.saw_canary is True


# ---------------------------------------------------------------------------
# Test 5 — two canary patterns, both detected separately
# ---------------------------------------------------------------------------


async def test_honeypot_multiple_canaries(multi_canary_server: HoneypotServer):
    """With two canary patterns configured, each is detected in separate requests."""
    hp = multi_canary_server
    base_url = f"http://127.0.0.1:{hp.port}"

    async with httpx.AsyncClient(base_url=base_url) as client:
        # Send request matching first canary only
        await client.post("/a", content="data with CANARY-ALPHA inside")
        # Send request matching second canary only
        await client.post("/b", content="data with CANARY-BETA inside")

    logs = hp.get_logs()
    assert len(logs) == 2
    assert logs[0]["canary_match"] is True
    assert logs[1]["canary_match"] is True
    assert hp.saw_canary is True
