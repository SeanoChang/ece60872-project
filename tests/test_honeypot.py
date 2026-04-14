"""Tests for core.honeypot.HoneypotServer — written TDD-first."""
import json
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


# ---------------------------------------------------------------------------
# Test 6 — events_dir: hit with a canary request → JSONL file written
# ---------------------------------------------------------------------------


async def test_honeypot_events_dir_writes_jsonl(tmp_path):
    """HoneypotServer with events_dir set writes a honeypot_request.jsonl on canary hit."""
    log_file = tmp_path / "honeypot.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=["CANARY-TOKEN-XYZ"],
        ablation="test-ablation",
        events_dir=str(tmp_path),
    )
    await hp.start()
    try:
        base_url = f"http://127.0.0.1:{hp.port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            resp = await client.post("/exfil", content="stolen: CANARY-TOKEN-XYZ here")
        assert resp.status_code == 200
    finally:
        await hp.stop()

    events_file = tmp_path / "honeypot_request.jsonl"
    assert events_file.exists(), "honeypot_request.jsonl was not created"

    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1, f"Expected exactly 1 event line, got {len(lines)}"

    event = json.loads(lines[0])
    assert event["canary_match"] is True
    assert event["ablation"] == "test-ablation"


# ---------------------------------------------------------------------------
# Test 7 — /_register_canary endpoint registers patterns and stamps scenario_run_id
# ---------------------------------------------------------------------------


async def test_register_canary_endpoint(tmp_path):
    """POST /_register_canary adds patterns; subsequent hits stamp the active scenario_run_id."""
    log_file = tmp_path / "honeypot.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=[],
        ablation="test-ablation",
        events_dir=str(tmp_path),
    )
    await hp.start()
    try:
        base_url = f"http://127.0.0.1:{hp.port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            reg_resp = await client.post(
                "/_register_canary",
                json={"patterns": ["CANARY-ABC123"], "scenario_run_id": "sr-xyz"},
            )
            assert reg_resp.status_code == 200
            body = reg_resp.json()
            assert body["registered"] == 1
            assert body["total"] >= 1

            exfil_resp = await client.post("/exfil", content="leaked: CANARY-ABC123")
            assert exfil_resp.status_code == 200
    finally:
        await hp.stop()

    events_file = tmp_path / "honeypot_request.jsonl"
    assert events_file.exists(), "honeypot_request.jsonl was not created"

    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    # The register_canary endpoint must NOT emit an event; only /exfil should.
    assert len(lines) == 1, f"Expected exactly 1 event line (only /exfil), got {len(lines)}"

    event = json.loads(lines[0])
    assert event["canary_match"] is True
    assert event["scenario_run_id"] == "sr-xyz"


async def test_register_canary_rejects_bad_admin_token(tmp_path):
    """With admin_token set, /_register_canary rejects requests lacking/wrong token."""
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(tmp_path / "honeypot.jsonl"),
        canary_patterns=[],
        events_dir=str(tmp_path),
        admin_token="secret-token-abc",
    )
    await hp.start()
    try:
        base_url = f"http://127.0.0.1:{hp.port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            # No header → 401
            r1 = await client.post(
                "/_register_canary",
                json={"patterns": ["X"], "scenario_run_id": "sr"},
            )
            assert r1.status_code == 401

            # Wrong header → 401
            r2 = await client.post(
                "/_register_canary",
                json={"patterns": ["X"], "scenario_run_id": "sr"},
                headers={"x-admin-token": "wrong"},
            )
            assert r2.status_code == 401

            # Correct header → 200
            r3 = await client.post(
                "/_register_canary",
                json={"patterns": ["X"], "scenario_run_id": "sr"},
                headers={"x-admin-token": "secret-token-abc"},
            )
            assert r3.status_code == 200
            assert r3.json()["registered"] == 1
    finally:
        await hp.stop()


# ---------------------------------------------------------------------------
# Test 8 — /health endpoint returns 200 and does NOT emit a HoneypotRequest event
# ---------------------------------------------------------------------------


async def test_honeypot_health_endpoint(tmp_path):
    """GET /health returns 200 {"status": "ok"} and emits no HoneypotRequest event."""
    log_file = tmp_path / "honeypot.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=[],
        ablation="test-ablation",
        events_dir=str(tmp_path),
    )
    await hp.start()
    try:
        base_url = f"http://127.0.0.1:{hp.port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    finally:
        await hp.stop()

    events_file = tmp_path / "honeypot_request.jsonl"
    if events_file.exists():
        lines = [l for l in events_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 0, (
            f"/health must not emit a HoneypotRequest event; got {len(lines)} lines"
        )


# ---------------------------------------------------------------------------
# Test 9 — run_id is read from BFT_RUN_ID env var at construction time
# ---------------------------------------------------------------------------


async def test_honeypot_run_id_from_env(tmp_path, monkeypatch):
    """With BFT_RUN_ID set, emitted events have run_id == that value."""
    monkeypatch.setenv("BFT_RUN_ID", "run-abc123")

    log_file = tmp_path / "honeypot.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=["CANARY-ENVTEST"],
        ablation="test-ablation",
        events_dir=str(tmp_path),
    )
    await hp.start()
    try:
        base_url = f"http://127.0.0.1:{hp.port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            resp = await client.post("/exfil", content="leak CANARY-ENVTEST")
        assert resp.status_code == 200
    finally:
        await hp.stop()

    events_file = tmp_path / "honeypot_request.jsonl"
    assert events_file.exists()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["run_id"] == "run-abc123"


# ---------------------------------------------------------------------------
# Test 10 — per-pattern scenario attribution (I1+I2 cross-contamination fix)
# ---------------------------------------------------------------------------


async def test_register_canary_per_pattern_attribution(tmp_path):
    """Two scenarios register different canaries; exfil of the first stamps its sid."""
    log_file = tmp_path / "honeypot.jsonl"
    hp = HoneypotServer(
        host="127.0.0.1",
        port=0,
        log_path=str(log_file),
        canary_patterns=[],
        ablation="test-ablation",
        events_dir=str(tmp_path),
    )
    await hp.start()
    try:
        base_url = f"http://127.0.0.1:{hp.port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            resp1 = await client.post(
                "/_register_canary",
                json={"patterns": ["CANARY-A"], "scenario_run_id": "sr-alpha"},
            )
            assert resp1.status_code == 200
            resp2 = await client.post(
                "/_register_canary",
                json={"patterns": ["CANARY-B"], "scenario_run_id": "sr-beta"},
            )
            assert resp2.status_code == 200

            exfil = await client.post("/exfil", content="leaked CANARY-A")
            assert exfil.status_code == 200
    finally:
        await hp.stop()

    events_file = tmp_path / "honeypot_request.jsonl"
    assert events_file.exists()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1, f"expected 1 event, got {len(lines)}"

    event = json.loads(lines[0])
    assert event["canary_match"] is True
    assert event["scenario_run_id"] == "sr-alpha", (
        f"expected sr-alpha (CANARY-A owner), got {event['scenario_run_id']}"
    )
