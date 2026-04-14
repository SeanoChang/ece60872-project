"""JSONL logger with file-level locking for concurrent-safe append and read."""
import json
from pathlib import Path

from filelock import FileLock


class JSONLLogger:
    """Append-only JSONL logger backed by a FileLock for safe concurrent writes."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self.path) + ".lock")

    def append(self, record: dict) -> None:
        """Acquire lock, then append one JSON-serialised record followed by a newline."""
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")

    def append_event(self, event) -> None:
        """Append a pydantic event (any BaseModel) to the log as one JSON line.

        Uses the same file lock as :meth:`append` so concurrent writers of large
        payloads (beyond POSIX PIPE_BUF) cannot interleave partial lines.
        """
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")

    def read_all(self) -> list[dict]:
        """Return all records from the log file, or [] if the file does not exist."""
        if not self.path.exists():
            return []
        records: list[dict] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
