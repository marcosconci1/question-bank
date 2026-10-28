#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import uuid


DEFAULT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_USER = "marcos"
_USER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
REQUIRED = {"question_id", "session_id", "given_answer", "is_correct"}
OPTIONAL = {"time_spent"}


def validate_user(name: str) -> str:
    if not isinstance(name, str) or not _USER_RE.match(name):
        raise ValueError(f"Invalid username: {name!r}")
    return name


def current_user() -> str:
    user = os.environ.get("QUESTION_BANK_USER", DEFAULT_USER)
    return validate_user(user)


def answers_path(root: Path, user: str | None = None) -> Path:
    if user is None:
        user = current_user()
    else:
        validate_user(user)
    return root / "data" / "users" / user / "answers.jsonl"


def _bank_root() -> Path:
    root = Path(os.environ.get("QUESTION_BANK_ROOT", str(DEFAULT_ROOT))).resolve()
    if not (root / "questions").is_dir():
        raise ValueError("QUESTION_BANK_ROOT must identify a question-bank module")
    return root


def _question(root: Path, question_id: str) -> dict[str, Any]:
    if not question_id or Path(question_id).name != question_id:
        raise ValueError("question_id must be a single file name component")
    questions_dir = (root / "questions").resolve()
    path = (questions_dir / f"{question_id}.json").resolve()
    if path.parent != questions_dir or not path.is_file():
        raise ValueError("question_id does not identify a bank question")
    question = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(question, dict):
        raise ValueError("question file must contain an object")
    return question


def _validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("answer record must be a JSON object")
    if set(request) - REQUIRED - OPTIONAL or not REQUIRED <= set(request):
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


def record_answer(request: dict[str, Any], bank_root: Path | None = None, user: str | None = None) -> dict[str, Any]:
    request = _validate_request(request)
    root = (bank_root or _bank_root()).resolve()
    question_id = request["question_id"].strip()
    session_id = request["session_id"].strip()
    question = _question(root, question_id)
    record = {
        "id": uuid.uuid4().hex,
        "question_id": question_id,
        "session_id": session_id,
        "given_answer": request["given_answer"],
        "is_correct": request["is_correct"],
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exam": question["exam"],
        "year": question["year"],
        "tags": list(question.get("tags") or []),
    }
    if "time_spent" in request:
        record["time_spent"] = request["time_spent"]
    log_path = answers_path(root, user)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
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
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Append one agent-graded question attempt")
    parser.add_argument("--input", required=True, help="JSON request path, or - for standard input")
    parser.add_argument("--user", default=None, help="Username to record attempt for")
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        record = record_answer(json.loads(raw), user=args.user)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, json.dumps({"error": "invalid_answer_record", "message": str(exc)}) + "\n")
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
