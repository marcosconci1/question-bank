"""Portable native Hermes tools for read-only question-bank access."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
MAX_LIMIT = 50
DEFAULT_USER = "marcos"
_USER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _validate_user(name: str) -> str:
    if not isinstance(name, str) or not _USER_RE.match(name):
        raise ValueError(f"Invalid username: {name!r}")
    return name


def _current_user() -> str:
    user = os.environ.get("QUESTION_BANK_USER", DEFAULT_USER)
    return _validate_user(user)


def _answers_path(root: Path, user: str | None = None) -> Path:
    if user is None:
        user = _current_user()
    else:
        _validate_user(user)
    return root / "data" / "users" / user / "answers.jsonl"


def available() -> bool:
    """Return whether the active Hermes profile enables question-bank tools."""
    from hermes_cli.config import load_config

    return bool(load_config().get("question_bank", {}).get("enabled", False))


def _error(code: str, **details: Any) -> str:
    return json.dumps({"error": code, **details}, ensure_ascii=False)


def _bank_root() -> Path:
    return Path(os.environ.get("QUESTION_BANK_ROOT", str(ROOT))).resolve()


def _cli_binary() -> Path:
    return Path(os.environ.get("QUESTION_SEARCH_BIN", str(ROOT / "question-search.sh")))


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


def _load_fixes() -> dict[str, dict[str, Any]]:
    """Read corrections/log.jsonl (last entry per field wins). See question_bank.corrections."""
    log = _bank_root() / "corrections" / "log.jsonl"
    fixes: dict[str, dict[str, Any]] = {}
    if not log.is_file():
        return fixes
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("question_id"), str)
            and isinstance(entry.get("field"), str)
            and entry["field"] not in {"id", "exam", "year", "number", "new-question"}
            and "new_value" in entry
        ):
            fixes.setdefault(entry["question_id"], {})[entry["field"]] = entry["new_value"]
    return fixes


def _apply_corrections(question: dict[str, Any], fixes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    fixes = _load_fixes() if fixes is None else fixes
    fix = fixes.get(str(question.get("id")))
    return {**question, **fix} if fix else question


def _question_path(question_id: str) -> Path:
    if not question_id or Path(question_id).name != question_id:
        raise ValueError("Question id must be a single file name component")
    questions_dir = (_bank_root() / "questions").resolve()
    path = (questions_dir / f"{question_id}.json").resolve()
    if path.parent != questions_dir:
        raise ValueError("Question id resolves outside the question bank")
    return path


def _presentation_question(question: dict[str, Any], view: str) -> dict[str, Any]:
    presented = json.loads(json.dumps(question))
    if view == "practice":
        presented.pop("answer", None)
        presented.pop("rubric", None)
    assets_dir = (_bank_root() / "assets").resolve()

    def resolve_blocks(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                resolve_blocks(item)
        elif isinstance(value, dict):
            for item in value.values():
                resolve_blocks(item)
            if value.get("type") == "image" and isinstance(value.get("src"), str):
                image_path = (_bank_root() / value["src"]).resolve()
                if not image_path.is_relative_to(assets_dir) or not image_path.is_file():
                    raise ValueError("Question image resolves outside the bank assets or is missing")
                value["src"] = str(image_path)

    resolve_blocks(presented)
    return presented


def get_question(args: dict[str, Any], **kwargs: Any) -> str:
    """Return a source question, an answer-safe practice view, or a solution view."""
    if not available():
        return _error("question_bank_disabled")
    if not isinstance(args, dict) or not isinstance(args.get("id"), str):
        return _error("invalid_question_request", field="id")
    if set(args) - {"id", "view"}:
        return _error("invalid_question_request")
    view = args.get("view")
    if view is not None and view not in {"practice", "solution"}:
        return _error("invalid_question_request", field="view")
    try:
        question_path = _question_path(args["id"])
        if not question_path.is_file():
            return _error("question_not_found", id=args["id"])
        question = json.loads(question_path.read_text(encoding="utf-8"))
        if not isinstance(question, dict):
            raise ValueError("Question file does not contain an object")
        question = _apply_corrections(question)
        if view is not None:
            question = _presentation_question(question, view)
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
        result = _answer_stats(_answers_path(_bank_root()))
        result["index_status"] = index_status
        return json.dumps(result, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        return _error("question_bank_adapter_error", error_class=type(exc).__name__)


def _registry() -> list[tuple[str, str, str]]:
    """Return (slug, display name, level) rows from docs/tags.md."""
    rows: list[tuple[str, str, str]] = []
    in_registry = False
    for raw in (_bank_root() / "docs" / "tags.md").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## Registry"):
            in_registry = True
            continue
        if in_registry and line.startswith("## "):
            break
        parts = [part.strip() for part in line.split("|")]
        if in_registry and len(parts) == 3 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", parts[0]):
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def list_topics(args: dict[str, Any], **kwargs: Any) -> str:
    """List registered topic tags with their active question counts."""
    if not available():
        return _error("question_bank_disabled")
    if not isinstance(args, dict) or set(args) - {"query", "level", "limit"}:
        return _error("invalid_question_request")
    query, level, limit = args.get("query"), args.get("level"), args.get("limit", 40)
    if query is not None and not isinstance(query, str):
        return _error("invalid_question_request", field="query")
    if level is not None and level not in {"area", "topic", "subtopic"}:
        return _error("invalid_question_request", field="level")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        return _error("invalid_question_request", field="limit")
    try:
        fixes = _load_fixes()
        counts: dict[str, int] = defaultdict(int)
        for path in (_bank_root() / "questions").glob("*.json"):
            question = _apply_corrections(json.loads(path.read_text(encoding="utf-8")), fixes)
            if question.get("status") == "active":
                for tag in question.get("tags", []):
                    counts[tag] += 1
        needle = query.strip().lower() if query else ""
        topics = [
            {"slug": slug, "name": name, "level": lvl, "active_questions": counts.get(slug, 0)}
            for slug, name, lvl in _registry()
            if (not level or lvl == level) and needle in f"{slug} {name}".lower()
        ]
        topics.sort(key=lambda t: (-t["active_questions"], t["slug"]))
        return json.dumps({"total": len(topics), "topics": topics[:limit]}, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
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
            "Return a stored question, an answer-safe practice view, or a solution view.",
            get_question,
            {
                "id": {"type": "string", "description": "The exact question identifier."},
                "view": {
                    "type": "string",
                    "enum": ["practice", "solution"],
                    "description": "Practice omits answer/rubric; solution includes them. Both resolve image paths.",
                },
            },
            ["id"],
        ),
        (
            "list-topics",
            "List registered topic tags (slug, name, level) with active question counts, to plan exercise lists.",
            list_topics,
            {
                "query": {"type": "string", "description": "Case-insensitive text matched against slug and name."},
                "level": {"type": "string", "enum": ["area", "topic", "subtopic"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 40},
            },
            [],
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
