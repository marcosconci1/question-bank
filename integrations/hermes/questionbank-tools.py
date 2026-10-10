"""Portable native Hermes tools for read-only question-bank access."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MAX_LIMIT = 50


def available() -> bool:
    """Return whether the active Hermes profile enables question-bank tools."""
    from hermes_cli.config import load_config

    return bool(load_config().get("question_bank", {}).get("enabled", False))


def _error(code: str, **details: Any) -> str:
    return json.dumps({"error": code, **details}, ensure_ascii=False)


def _bank_root() -> Path:
    return Path(os.environ.get("QUESTION_BANK_ROOT", str(ROOT))).resolve()


def _cli_binary() -> Path:
    return Path(os.environ.get("QUESTION_SEARCH_BIN", str(ROOT / ".venv/bin/question-search")))


def _run_cli(command: str, arguments: list[str]) -> dict[str, Any]:
    """Run the owned CLI without leaking the gateway Python environment."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    proc = subprocess.run(
        [str(_cli_binary()), command, "--json", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    output = proc.stdout if proc.returncode == 0 else proc.stderr
    decoded = json.loads(output)
    if not isinstance(decoded, (dict, list)):
        raise ValueError("Question-search returned an invalid JSON payload")
    return decoded


def _normalise_filters(filters: Any) -> tuple[dict[str, Any], list[str]]:
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    allowed = {"tags", "exam", "year_from", "year_to", "status"}
    unexpected = sorted(set(filters) - allowed)
    if unexpected:
        raise ValueError(f"Unsupported filters: {', '.join(unexpected)}")

    normalised: dict[str, Any] = {}
    arguments: list[str] = []
    tags = filters.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
            raise ValueError("filters.tags must be a list of non-empty strings")
        normalised["tags"] = [tag.strip() for tag in tags]
        arguments.extend(["--tags", ",".join(normalised["tags"])])

    exam = filters.get("exam")
    if exam is not None:
        if not isinstance(exam, str) or not exam.strip():
            raise ValueError("filters.exam must be a non-empty string")
        normalised["exam"] = exam.strip()
        arguments.extend(["--exam", normalised["exam"]])

    year_from = filters.get("year_from")
    year_to = filters.get("year_to")
    for name, value in (("year_from", year_from), ("year_to", year_to)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"filters.{name} must be an integer")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("filters.year_from cannot be after filters.year_to")
    if year_from is not None or year_to is not None:
        lower = 0 if year_from is None else year_from
        upper = 9999 if year_to is None else year_to
        normalised["years"] = f"{lower}-{upper}"
        arguments.extend(["--years", normalised["years"]])

    status = filters.get("status", "active")
    if not isinstance(status, str) or not status.strip():
        raise ValueError("filters.status must be a non-empty string")
    normalised["status"] = status.strip().lower()
    arguments.extend(["--status", normalised["status"]])
    return normalised, arguments


def search_questions(args: dict[str, Any], **kwargs: Any) -> str:
    """Return CLI-ranked questions that match one student objective."""
    if not available():
        return _error("question_bank_disabled")
    if not isinstance(args, dict) or set(args) - {"objective", "filters", "limit"}:
        return _error("invalid_question_request")
    objective = args.get("objective")
    limit = args.get("limit", 10)
    if not isinstance(objective, str) or not objective.strip():
        return _error("invalid_question_request", field="objective")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        return _error("invalid_question_request", field="limit")
    try:
        _, filter_arguments = _normalise_filters(args.get("filters", {}))
        result = _run_cli("query", [objective.strip(), "--top-k", str(limit), *filter_arguments])
        if not isinstance(result, list):
            raise ValueError("Question search returned an unexpected result")
        return json.dumps(result, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        return _error("question_bank_adapter_error", error_class=type(exc).__name__)


def _question_path(question_id: str) -> Path:
    if not question_id or Path(question_id).name != question_id:
        raise ValueError("Question id must be a single file name component")
    questions_dir = (_bank_root() / "questions").resolve()
    path = (questions_dir / f"{question_id}.json").resolve()
    if path.parent != questions_dir:
        raise ValueError("Question id resolves outside the question bank")
    return path


def get_question(args: dict[str, Any], **kwargs: Any) -> str:
    """Return one complete source-of-truth question, including its answer key."""
    if not available():
        return _error("question_bank_disabled")
    if not isinstance(args, dict) or set(args) != {"id"} or not isinstance(args["id"], str):
        return _error("invalid_question_request", field="id")
    try:
        question_path = _question_path(args["id"])
        if not question_path.is_file():
            return _error("question_not_found", id=args["id"])
        question = json.loads(question_path.read_text(encoding="utf-8"))
        if not isinstance(question, dict):
            raise ValueError("Question file does not contain an object")
        return json.dumps(question, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error("question_bank_adapter_error", error_class=type(exc).__name__)


def _empty_stats(note: str) -> dict[str, Any]:
    return {
        "note": note,
        "overall": {"total": 0, "correct": 0, "incorrect": 0, "accuracy": 0.0},
        "per_tag": [],
        "error_ranking": [],
        "per_exam": [],
        "weekly_trend": [],
    }


def _week_key(timestamp: object) -> str | None:
    if not isinstance(timestamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def _answer_stats(answer_log: Path) -> dict[str, Any]:
    if not answer_log.is_file():
        return _empty_stats("No answers log exists yet.")
    rows: list[dict[str, Any]] = []
    invalid_rows = 0
    for line in answer_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            invalid_rows += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            invalid_rows += 1
    if not rows:
        return _empty_stats("The answers log has no valid records." if invalid_rows else "The answers log is empty.")

    totals = {"total": 0, "correct": 0}
    by_tag: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_exam: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_week: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    for row in rows:
        correct = row.get("is_correct") is True
        totals["total"] += 1
        totals["correct"] += int(correct)
        for tag in row.get("tags", []) if isinstance(row.get("tags"), list) else []:
            if isinstance(tag, str) and tag:
                by_tag[tag]["total"] += 1
                by_tag[tag]["correct"] += int(correct)
        if isinstance(row.get("exam"), str) and row["exam"]:
            by_exam[row["exam"]]["total"] += 1
            by_exam[row["exam"]]["correct"] += int(correct)
        week = _week_key(row.get("timestamp"))
        if week:
            by_week[week]["total"] += 1
            by_week[week]["correct"] += int(correct)

    def aggregate(key: str, values: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
        return [
            {
                key: label,
                "total": counts["total"],
                "correct": counts["correct"],
                "incorrect": counts["total"] - counts["correct"],
                "accuracy": round(counts["correct"] / counts["total"], 4),
            }
            for label, counts in sorted(values.items())
        ]

    per_tag = aggregate("tag", by_tag)
    return {
        "note": f"Ignored {invalid_rows} invalid answer-log record(s)." if invalid_rows else "",
        "overall": {
            "total": totals["total"],
            "correct": totals["correct"],
            "incorrect": totals["total"] - totals["correct"],
            "accuracy": round(totals["correct"] / totals["total"], 4),
        },
        "per_tag": per_tag,
        "error_ranking": sorted(per_tag, key=lambda item: (-item["incorrect"], item["accuracy"], item["tag"])),
        "per_exam": aggregate("exam", by_exam),
        "weekly_trend": aggregate("week", by_week),
    }


def get_stats(args: dict[str, Any], **kwargs: Any) -> str:
    """Return index status and read-only aggregations over the optional answer log."""
    if not available():
        return _error("question_bank_disabled")
    if not isinstance(args, dict) or args:
        return _error("invalid_question_request")
    try:
        index_status = _run_cli("status", [])
        if not isinstance(index_status, dict):
            raise ValueError("Question status returned an unexpected result")
        result = _answer_stats(_bank_root() / "data" / "answers.jsonl")
        result["index_status"] = index_status
        return json.dumps(result, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        return _error("question_bank_adapter_error", error_class=type(exc).__name__)


def register(ctx: Any) -> None:
    """Register the complete read-only question-bank surface."""
    definitions = (
        (
            "search-questions",
            "Search ranked questions by a student objective with optional deterministic filters.",
            search_questions,
            {
                "objective": {"type": "string", "description": "The student learning objective or question."},
                "filters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "exam": {"type": "string"},
                        "year_from": {"type": "integer"},
                        "year_to": {"type": "integer"},
                        "status": {"type": "string", "default": "active"},
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": 10},
            },
            ["objective"],
        ),
        (
            "get-question",
            "Return a complete stored question, including its answer key or rubric.",
            get_question,
            {"id": {"type": "string", "description": "The exact question identifier."}},
            ["id"],
        ),
        (
            "get-stats",
            "Return question-bank index status and optional answer-log aggregations without writing data.",
            get_stats,
            {},
            [],
        ),
    )
    for name, description, handler, properties, required in definitions:
        ctx.register_tool(
            name=name,
            toolset="question-bank",
            emoji="📝",
            check_fn=available,
            handler=handler,
            schema={
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        )
