"""Per-user answer logging and history storage."""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

from question_bank.corrections import apply_corrections


DEFAULT_USER = "marcos"
_USER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_REQUIRED = {"question_id", "session_id", "given_answer", "is_correct"}
_OPTIONAL = {"time_spent"}


def validate_user(name: str) -> str:
    """Validate a username string against allowed pattern."""
    if not isinstance(name, str) or not _USER_RE.match(name):
        raise ValueError(f"Invalid username: {name!r}")
    return name


def current_user() -> str:
    """Return the active username from environment or default."""
    user = os.environ.get("QUESTION_BANK_USER", DEFAULT_USER)
    return validate_user(user)


def answers_path(root: Path | str, user: str | None = None) -> Path:
    """Return path to user's answers.jsonl file."""
    if user is None:
        user = current_user()
    else:
        validate_user(user)
    return Path(root) / "data" / "users" / user / "answers.jsonl"


def list_users(root: Path | str) -> list[str]:
    """Return list of valid usernames with directories under data/users."""
    users_dir = Path(root) / "data" / "users"
    if not users_dir.is_dir():
        return []
    users = []
    for entry in sorted(users_dir.iterdir()):
        if entry.is_dir() and _USER_RE.match(entry.name):
            users.append(entry.name)
    return users


def create_user(root: Path | str, name: str) -> Path:
    """Create user directory idempotently."""
    validate_user(name)
    user_dir = Path(root) / "data" / "users" / name
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def read_answers(path: Path | str) -> list[dict[str, Any]]:
    """Read answers JSON lines file and return list of valid record dicts."""
    p = Path(path)
    if not p.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("answer record must be a JSON object")
    if set(request) - _REQUIRED - _OPTIONAL or not _REQUIRED <= set(request):
        raise ValueError("answer record has missing or unsupported fields")
    for field in ("question_id", "session_id"):
        if not isinstance(request[field], str) or not request[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if not isinstance(request["given_answer"], str) or len(request["given_answer"]) > 100000:
        raise ValueError("given_answer must be a string of at most 100000 characters")
    if type(request["is_correct"]) is not bool:
        raise ValueError("is_correct must be a boolean")
    if "time_spent" in request and (
        type(request["time_spent"]) is not int or request["time_spent"] < 0
    ):
        raise ValueError("time_spent must be a non-negative integer")
    return request


def _question(root: Path, question_id: str) -> dict[str, Any]:
    if not question_id or Path(question_id).name != question_id:
        raise ValueError("question_id must be a single file name component")
    questions_dir = (root / "questions").resolve()
    path = (questions_dir / f"{question_id}.json").resolve()
    if path.parent != questions_dir or not path.is_file():
        raise ValueError("question_id does not identify a bank question")
    try:
        question = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("question file must contain valid JSON") from exc
    if not isinstance(question, dict):
        raise ValueError("question file must contain an object")
    return apply_corrections(question, root)


def record_answer(root: Path | str, user: str, request: dict[str, Any]) -> dict[str, Any]:
    """Append one graded question attempt to the user's answers log."""
    validate_user(user)
    req = _validate_request(request)
    bank_root = Path(root).resolve()
    question_id = req["question_id"].strip()
    session_id = req["session_id"].strip()
    question = _question(bank_root, question_id)
    record: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "question_id": question_id,
        "session_id": session_id,
        "given_answer": req["given_answer"],
        "is_correct": req["is_correct"],
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exam": question.get("exam"),
        "year": question.get("year"),
        "tags": list(question.get("tags") or []),
    }
    if "time_spent" in req:
        record["time_spent"] = req["time_spent"]

    log_path = answers_path(bank_root, user)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            stream.seek(0)
            for line in stream:
                if not line.strip():
                    continue
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(existing, dict) and (
                    existing.get("question_id"), existing.get("session_id")
                ) == (question_id, session_id):
                    raise ValueError("this question is already recorded in the session")
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return record
