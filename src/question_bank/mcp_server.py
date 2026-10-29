"""Read-only MCP server for semantic retrieval from the question bank."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from question_bank import answers
from question_bank.corrections import apply_corrections
from question_search import config, embed, flatten, store


SearchCore = Callable[..., list[dict[str, Any]]]
Embedder = Callable[[list[str]], list[list[float]]]


def _question_path(questions_dir: Path, question_id: str) -> Path:
    """Return a question file path without allowing an id to escape the bank."""
    if not question_id or Path(question_id).name != question_id:
        raise ValueError("Question id must be a single file name component")

    question_file = (questions_dir / f"{question_id}.json").resolve()
    if question_file.parent != questions_dir.resolve():
        raise ValueError("Question id resolves outside the question bank")
    return question_file


def _read_question(questions_dir: Path, question_id: str) -> tuple[Path, dict[str, Any]]:
    question_file = _question_path(questions_dir, question_id)
    if not question_file.is_file():
        raise ValueError(f"Question not found: {question_id}")
    try:
        question = json.loads(question_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Question file is not valid JSON: {question_id}") from exc
    if not isinstance(question, dict):
        raise ValueError(f"Question file does not contain an object: {question_id}")
    return question_file, apply_corrections(question, questions_dir.parent)


def _stem_preview(question: dict[str, Any]) -> str:
    """Return the first 200 characters of the stem, excluding answer/options."""
    return flatten.flatten_blocks(question.get("stem"))[:200]


def _normalise_filters(filters: dict[str, Any]) -> tuple[list[str] | None, str | None, tuple[int, int] | None, str]:
    """Translate the public MCP filter shape to the existing search core shape."""
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")

    allowed = {"tags", "exam", "year_from", "year_to", "status"}
    unexpected = sorted(set(filters) - allowed)
    if unexpected:
        raise ValueError(f"Unsupported filters: {', '.join(unexpected)}")

    tags_value = filters.get("tags")
    if tags_value is not None and (
        not isinstance(tags_value, list) or not all(isinstance(tag, str) for tag in tags_value)
    ):
        raise ValueError("filters.tags must be a list of strings")
    tags = [tag.strip() for tag in tags_value or [] if tag.strip()] or None

    exam_value = filters.get("exam")
    if exam_value is not None and not isinstance(exam_value, str):
        raise ValueError("filters.exam must be a string")
    exam = exam_value.strip().lower() if exam_value and exam_value.strip() else None

    year_from = filters.get("year_from")
    year_to = filters.get("year_to")
    if year_from is not None and (isinstance(year_from, bool) or not isinstance(year_from, int)):
        raise ValueError("filters.year_from must be an integer")
    if year_to is not None and (isinstance(year_to, bool) or not isinstance(year_to, int)):
        raise ValueError("filters.year_to must be an integer")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("filters.year_from cannot be after filters.year_to")
    # The core accepts a closed range.  Question years are positive integers, so
    # open public bounds can be represented without widening the requested side.
    year_range = None
    if year_from is not None or year_to is not None:
        year_range = (year_from if year_from is not None else 0, year_to if year_to is not None else 9999)

    status_value = filters.get("status", "active")
    if not isinstance(status_value, str):
        raise ValueError("filters.status must be a string")
    status = status_value.strip().lower() or "active"
    return tags, exam, year_range, status


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


def _calculate_stats(answers_path: Path) -> dict[str, Any]:
    """Aggregate the append-only answer log without changing it."""
    if not answers_path.is_file():
        return _empty_stats("No answers log exists yet.")

    rows: list[dict[str, Any]] = []
    invalid_rows = 0
    for line in answers_path.read_text(encoding="utf-8").splitlines():
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
        note = "The answers log is empty."
        if invalid_rows:
            note = "The answers log has no valid records."
        return _empty_stats(note)

    totals = {"total": 0, "correct": 0}
    by_tag: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_exam: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_week: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})

    for row in rows:
        correct = row.get("is_correct") is True
        totals["total"] += 1
        totals["correct"] += int(correct)

        tags = row.get("tags")
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag:
                    by_tag[tag]["total"] += 1
                    by_tag[tag]["correct"] += int(correct)

        exam = row.get("exam")
        if isinstance(exam, str) and exam:
            by_exam[exam]["total"] += 1
            by_exam[exam]["correct"] += int(correct)

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
    error_ranking = sorted(
        per_tag,
        key=lambda item: (-item["incorrect"], item["accuracy"], item["tag"]),
    )
    note = ""
    if invalid_rows:
        note = f"Ignored {invalid_rows} invalid answer-log record(s)."
    return {
        "note": note,
        "overall": {
            "total": totals["total"],
            "correct": totals["correct"],
            "incorrect": totals["total"] - totals["correct"],
            "accuracy": round(totals["correct"] / totals["total"], 4),
        },
        "per_tag": per_tag,
        "error_ranking": error_ranking,
        "per_exam": aggregate("exam", by_exam),
        "weekly_trend": aggregate("week", by_week),
    }


def create_server(
    bank_root: Path | None = None,
    answers_path: Path | None = None,
    search_core: SearchCore = store.search_questions,
    embedder: Embedder = embed.embed,
) -> MCPServer:
    """Create the stdio MCP server, optionally with paths/core functions for tests."""
    root = (bank_root or config.BANK_ROOT).resolve()
    questions_dir = root / "questions"
    answer_log = answers_path or answers.answers_path(root)
    server = MCPServer(
        name="question-bank",
        title="Question Bank",
        description="Read-only semantic retrieval over the question bank.",
    )

    @server.tool(name="search-questions", description="Return ranked questions that best match a student objective.")
    def search_questions(objective: str, filters: dict[str, Any] = {}, limit: int = 10) -> list[dict[str, Any]]:
        """Search the semantic index; filters are enforced by the existing search core."""
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("objective must be a non-empty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")

        tags, exam, year_range, status = _normalise_filters(filters)
        vectors = embedder([objective.strip()])
        if not vectors:
            raise ValueError("Embedding returned no query vector")
        ranked = search_core(
            query_vector=vectors[0],
            limit=limit,
            status=status,
            exam=exam,
            year_range=year_range,
            tags=tags,
        )

        results: list[dict[str, Any]] = []
        for result in ranked[:limit]:
            question_id = str(result.get("id", ""))
            question_file, question = _read_question(questions_dir, question_id)
            results.append(
                {
                    "id": question_id,
                    "path": str(question_file.relative_to(root)),
                    "preview": _stem_preview(question),
                    "tags": list(question.get("tags") or []),
                    "status": question.get("status") or "active",
                    "year": question.get("year"),
                    "exam": question.get("exam"),
                }
            )
        return results

    @server.tool(name="get-question", description="Return the complete stored question, including its answer key or rubric.")
    def get_question(id: str) -> dict[str, Any]:
        """Read one source-of-truth question object without withholding answer data."""
        if not isinstance(id, str):
            raise ValueError("id must be a string")
        _, question = _read_question(questions_dir, id)
        return question

    @server.tool(name="get-stats", description="Return accuracy aggregations from the append-only answer log.")
    def get_stats() -> dict[str, Any]:
        """Read aggregate practice statistics without writing any bank data."""
        return _calculate_stats(answer_log)

    return server


mcp = create_server()


def main() -> None:
    """Run the question-bank MCP server over standard input/output."""
    mcp.run(transport="stdio")
