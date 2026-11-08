"""Small local JSONL journal for question-bank diagnostics."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from question_bank.paths import resolve_bank_root

JOURNAL_NAME = "events.log.jsonl"
RETENTION_DAYS = 30
MAX_JOURNAL_BYTES = 1024 * 1024
_LOCK = threading.Lock()
_SECRET_KEY = re.compile(r"(?:api[_-]?key|token|secret|password)", re.IGNORECASE)
_TOKEN_TEXT = re.compile(
    r"(?i)\b(?:sk-(?:or-)?[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|"
    r"github_pat_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{8,})\b"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


def journal_path(bank_root: str | os.PathLike[str] | None = None) -> Path:
    root = Path(bank_root).expanduser().resolve() if bank_root is not None else resolve_bank_root()
    return root / "reports" / JOURNAL_NAME


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(item, str(k)) for k, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", _TOKEN_TEXT.sub("[REDACTED]", value))[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize(str(value))


def _timestamp(line: str) -> datetime | None:
    try:
        event = json.loads(line)
        stamp = datetime.fromisoformat(event["ts"])
    except (ValueError, TypeError, KeyError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def trim_lines(
    lines: list[str],
    *,
    now: datetime | None = None,
    max_age_days: int = RETENTION_DAYS,
    max_bytes: int = MAX_JOURNAL_BYTES,
) -> list[str]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
    valid = [line for line in lines if (stamp := _timestamp(line)) is not None and stamp >= cutoff]
    total = sum(len(line.encode("utf-8")) + 1 for line in valid)
    drop = 0
    while drop < len(valid) and total > max_bytes:
        total -= len(valid[drop].encode("utf-8")) + 1
        drop += 1
    return valid[drop:]


def _trim_locked(path: Path) -> None:
    try:
        lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except FileNotFoundError:
        return
    kept = trim_lines(lines)
    if kept == lines:
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("".join(line + "\n" for line in kept))
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def append_event(
    bank_root: str | os.PathLike[str] | None,
    action: str,
    outcome: str,
    **details: Any,
) -> None:
    """Append one sanitized event, enforcing age and byte retention."""
    event = _sanitize({"ts": datetime.now(timezone.utc).isoformat(), "action": action,
                       "outcome": outcome, **details})
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    path = journal_path(bank_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        _trim_locked(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(line)
        _trim_locked(path)


def read_events(bank_root: str | os.PathLike[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
    path = journal_path(bank_root)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines[-max(0, limit):] if limit else []:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(_sanitize(event))
    return events
