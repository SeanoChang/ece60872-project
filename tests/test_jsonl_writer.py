"""Concurrency tests for JSONLLogger.append_event.

Verifies that writes beyond POSIX PIPE_BUF (~4KB) remain line-atomic when
many threads append concurrently to the same file.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from core.logger import JSONLLogger


class _Ev(BaseModel):
    i: int
    payload: str


def test_append_event_is_line_atomic(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JSONLLogger(str(path))
    N = 200
    big_payload = "x" * 8000  # > PIPE_BUF

    def worker(i: int) -> None:
        logger.append_event(_Ev(i=i, payload=big_payload))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(worker, range(N)))

    lines = path.read_text().splitlines()
    assert len(lines) == N, f"expected {N} lines, got {len(lines)}"
    seen = set()
    for line in lines:
        obj = json.loads(line)  # must not raise
        seen.add(obj["i"])
        assert obj["payload"] == big_payload
    assert seen == set(range(N))
