"""Read-only MCP server for retrieval, topic browsing, and stats over the question bank."""

from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from question_bank import answers
from question_bank.corrections import apply_corrections, load_corrections
from question_bank.paths import resolve_bank_root
from question_search import config, embed, errors, flatten, lexical, store


SearchCore = Callable[..., list[dict[str, Any]]]
Embedder = Callable[[list[str]], list[list[float]]]
LexicalSearch = Callable[..., list[dict[str, Any]]]

_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TOPIC_LEVELS = frozenset({"area", "topic", "subtopic"})
_QUESTION_VIEWS = frozenset({"practice", "solution"})


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


def _presentation_question(root: Path, question: dict[str, Any], view: str) -> dict[str, Any]:
    """Return a practice (answer-safe) or solution copy with validated image paths."""
    presented = copy.deepcopy(question)
    if view == "practice":
        presented.pop("answer", None)
        presented.pop("rubric", None)

    assets_dir = (root / "assets").resolve()

    def resolve_blocks(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                resolve_blocks(item)
        elif isinstance(value, dict):
            for item in value.values():
                resolve_blocks(item)
            if value.get("type") == "image" and isinstance(value.get("src"), str):
                image_path = (root / value["src"]).resolve()
                if not image_path.is_relative_to(assets_dir) or not image_path.is_file():
                    raise ValueError("Question image resolves outside the bank assets or is missing")
                value["src"] = str(image_path)

    resolve_blocks(presented)
    return presented


def _load_registry(root: Path) -> list[tuple[str, str, str]]:
    """Return (slug, display name, level) rows from the bank or bundled docs/tags.md."""
    candidates = (
        root / "docs" / "tags.md",
        Path(__file__).resolve().parents[2] / "docs" / "tags.md",
    )
    text = ""
    for candidate in candidates:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
            break
    if not text:
        return []

    rows: list[tuple[str, str, str]] = []
    in_registry = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## Registry"):
            in_registry = True
            continue
        if in_registry and line.startswith("## "):
            break
        parts = [part.strip() for part in line.split("|")]
        if in_registry and len(parts) == 3 and _SLUG_RE.fullmatch(parts[0]):
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def _list_topics(
    root: Path,
    *,
    query: str | None = None,
    level: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    if query is not None and not isinstance(query, str):
        raise ValueError("query must be a string")
    if level is not None and level not in _TOPIC_LEVELS:
        raise ValueError("level must be one of: area, topic, subtopic")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer between 1 and 200")

    questions_dir = root / "questions"
    fixes = load_corrections(root)
    counts: dict[str, int] = defaultdict(int)
    year_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    if questions_dir.is_dir():
        for path in sorted(questions_dir.glob("*.json")):
            try:
                question = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(question, dict):
                continue
            fix = fixes.get(str(question.get("id")))
            if fix:
                question = {**question, **fix}
            if (question.get("status") or "active") != "active":
                continue
            year = question.get("year")
            for tag in question.get("tags") or []:
                if isinstance(tag, str) and tag:
                    counts[tag] += 1
                    if isinstance(year, int) and not isinstance(year, bool):
                        year_counts[tag][year] += 1

    needle = query.strip().lower() if query else ""
    topics = [
        {
            "slug": slug,
            "name": name,
            "level": lvl,
            "active_questions": counts.get(slug, 0),
            "by_year": {
                str(year): count for year, count in sorted(year_counts.get(slug, {}).items())
            },
        }
        for slug, name, lvl in _load_registry(root)
        if (not level or lvl == level) and needle in f"{slug} {name}".lower()
    ]
    topics.sort(key=lambda item: (-item["active_questions"], item["slug"]))
    return {"total": len(topics), "topics": topics[:limit]}


def create_server(
    bank_root: Path | None = None,
    answers_path: Path | None = None,
    search_core: SearchCore | None = None,
    embedder: Embedder | None = None,
    lexical_search: LexicalSearch = lexical.search,
) -> MCPServer:
    """Create the stdio MCP server, optionally with paths/core functions for tests."""
    root = (bank_root or resolve_bank_root()).resolve()
    questions_dir = root / "questions"
    answer_log = answers_path or answers.answers_path(root)
    explicit_semantic = search_core is not None or embedder is not None
    server = MCPServer(
        name="question-bank",
        title="Question Bank",
        description="Read-only retrieval, topic browsing, and stats over the question bank.",
    )

    @server.tool(name="search-questions", description="Return ranked questions that best match a student objective.")
    def search_questions(objective: str, filters: dict[str, Any] = {}, limit: int = 10) -> list[dict[str, Any]]:
        """Search the bank using semantic search when available, falling back to local BM25."""
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("objective must be a non-empty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")

        query_text = objective.strip()
        tags, exam, year_range, status = _normalise_filters(filters)
        ranked: list[dict[str, Any]] | None = None
        if explicit_semantic:
            active_embedder = embedder or embed.embed
            active_search = search_core or store.search_questions
            vectors = active_embedder([query_text])
            if not vectors:
                raise ValueError("Embedding returned no query vector")
            ranked = active_search(
                query_vector=vectors[0],
                limit=limit,
                status=status,
                exam=exam,
                year_range=year_range,
                tags=tags,
            )
        elif config.OPENROUTER_API_KEY:
            try:
                vectors = embed.embed([query_text])
                if not vectors:
                    raise errors.EmbeddingApiError("Embedding returned no query vector")
                ranked = store.search_questions(
                    query_vector=vectors[0],
                    limit=limit,
                    status=status,
                    exam=exam,
                    year_range=year_range,
                    tags=tags,
                )
            except errors.QuestionSearchError:
                ranked = None

        if ranked is None:
            ranked = lexical_search(
                query_text,
                limit=limit,
                status=status,
                exam=exam,
                year_range=year_range,
                tags=tags,
                root=root,
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

    @server.tool(
        name="get-question",
        description="Return a stored question in answer-safe practice view (default) or solution view.",
    )
    def get_question(id: str, view: str = "practice") -> dict[str, Any]:
        """Read one question: practice view omits answer/rubric; solution view includes them."""
        if not isinstance(id, str):
            raise ValueError("id must be a string")
        if not isinstance(view, str) or view not in _QUESTION_VIEWS:
            raise ValueError("view must be 'practice' or 'solution'")
        _, question = _read_question(questions_dir, id)
        return _presentation_question(root, question, view)

    @server.tool(
        name="list-topics",
        description="List registered topic tags (slug, name, level) with active question counts and per-year frequency.",
    )
    def list_topics(
        query: str | None = None,
        level: str | None = None,
        limit: int = 40,
    ) -> dict[str, Any]:
        """List registered topics with active counts and by_year breakdown."""
        return _list_topics(root, query=query, level=level, limit=limit)

    @server.tool(name="get-stats", description="Return accuracy aggregations from the append-only answer log.")
    def get_stats() -> dict[str, Any]:
        """Read aggregate practice statistics without writing any bank data."""
        return _calculate_stats(answer_log)

    return server


mcp = create_server()


def main() -> None:
    """Run the question-bank MCP server over standard input/output."""
    mcp.run(transport="stdio")
