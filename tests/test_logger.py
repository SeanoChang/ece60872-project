"""Tests for core.logger.JSONLLogger — written TDD-first."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.logger import JSONLLogger


def test_logger_append_and_read(tmp_path):
    """Appending two records and reading back returns both with correct data."""
    log_path = tmp_path / "test.jsonl"
    logger = JSONLLogger(str(log_path))

    record1 = {"event": "start", "value": 1}
    record2 = {"event": "stop", "value": 2}

    logger.append(record1)
    logger.append(record2)

    records = logger.read_all()

    assert len(records) == 2
    assert records[0] == record1
    assert records[1] == record2


def test_logger_creates_parent_dirs(tmp_path):
    """Logger with a deeply nested path creates all intermediate directories."""
    nested_path = tmp_path / "a" / "b" / "c" / "log.jsonl"
    logger = JSONLLogger(str(nested_path))

    logger.append({"event": "test"})

    assert nested_path.exists()
    assert nested_path.parent.is_dir()


def test_logger_read_empty(tmp_path):
    """read_all on a non-existent file returns an empty list."""
    log_path = tmp_path / "nonexistent.jsonl"
    logger = JSONLLogger(str(log_path))

    result = logger.read_all()

    assert result == []


def test_logger_serializes_datetime(tmp_path):
    """Appending a record with a datetime value serializes without error."""
    log_path = tmp_path / "datetime_test.jsonl"
    logger = JSONLLogger(str(log_path))

    dt = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
    record = {"event": "timestamped", "ts": dt}

    logger.append(record)

    records = logger.read_all()
    assert len(records) == 1
    assert records[0]["event"] == "timestamped"
    # datetime was serialized to string via default=str
    assert isinstance(records[0]["ts"], str)
    assert "2026" in records[0]["ts"]
