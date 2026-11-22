"""In-process MCP protocol tests for the read-only question-bank server."""

import json

import pytest
from mcp.client import Client

from question_bank.mcp_server import create_server


def _tool_data(result):
    assert result.is_error is not True
    assert result.structured_content is not None
    # MCP wraps a top-level list in {"result": ...}; object results are direct.
    if set(result.structured_content) == {"result"}:
        return result.structured_content["result"]
    return result.structured_content


@pytest.fixture
def fixture_bank(tmp_path):
    questions = tmp_path / "questions"
    questions.mkdir()
    active = {
        "id": "poscomp-2024-52",
        "exam": "poscomp",
        "year": 2024,
        "status": "active",
        "stem": "Deadlock detection from a transaction wait graph.",
        "options": ["Wait graph", "No wait"],
        "answer": "A",
        "tags": ["databases", "concurrency"],
    }
    suspended = {
        "id": "poscomp-2023-01",
        "exam": "poscomp",
        "year": 2023,
        "status": "suspended",
        "stem": "A suspended question.",
        "answer": "B",
        "tags": ["databases"],
    }
    for question in (active, suspended):
        (questions / f"{question['id']}.json").write_text(json.dumps(question), encoding="utf-8")
    return tmp_path, active, suspended


@pytest.mark.anyio
async def test_mcp_tools_are_exactly_the_read_only_surface(fixture_bank):
    root, _, _ = fixture_bank
    server = create_server(root, search_core=lambda **_: [], embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools.tools} == {
        "search-questions",
        "get-question",
        "list-topics",
        "get-stats",
    }


@pytest.mark.anyio
async def test_search_questions_is_ranked_filtered_and_not_shuffled(fixture_bank):
    root, active, suspended = fixture_bank
    calls = []

    def ranked_search(**kwargs):
        calls.append(kwargs)
        return [
            {"id": active["id"]},
            {"id": suspended["id"]},
        ] if kwargs["status"] == "all" else [{"id": active["id"]}]

    server = create_server(root, search_core=ranked_search, embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        first = _tool_data(
            await client.call_tool(
                "search-questions", {"objective": "detect deadlocks", "filters": {"status": "active"}, "limit": 1}
            )
        )
        second = _tool_data(await client.call_tool("search-questions", {"objective": "detect deadlocks", "limit": 1}))
        widened = _tool_data(
            await client.call_tool(
                "search-questions",
                {"objective": "databases", "filters": {"status": "all", "tags": ["databases"]}, "limit": 10},
            )
        )

    assert first == second
    assert len(first) == 1
    assert first[0] == {
        "id": active["id"],
        "path": "questions/poscomp-2024-52.json",
        "preview": active["stem"],
        "tags": active["tags"],
        "status": "active",
        "year": 2024,
        "exam": "poscomp",
    }
    assert [item["id"] for item in widened] == [active["id"], suspended["id"]]
    assert calls[0]["status"] == "active"
    assert calls[-1]["tags"] == ["databases"]


@pytest.mark.anyio
async def test_search_questions_falls_back_to_keyless_lexical_search(fixture_bank, monkeypatch):
    root, active, _ = fixture_bank
    monkeypatch.setattr("question_bank.mcp_server.config.OPENROUTER_API_KEY", "")
    server = create_server(root)
    async with Client(server, mode="legacy") as client:
        hits = _tool_data(
            await client.call_tool("search-questions", {"objective": "deadlock wait graph", "limit": 5})
        )
    assert [item["id"] for item in hits] == [active["id"]]


@pytest.mark.anyio
async def test_get_question_defaults_to_answer_safe_practice_view_and_supports_solution(fixture_bank):
    root, active, _ = fixture_bank
    server = create_server(root, search_core=lambda **_: [], embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        practice = _tool_data(await client.call_tool("get-question", {"id": active["id"]}))
        solution = _tool_data(
            await client.call_tool("get-question", {"id": active["id"], "view": "solution"})
        )
        invalid = await client.call_tool("get-question", {"id": active["id"], "view": "raw"})

    assert "answer" not in practice
    assert "rubric" not in practice
    assert practice["id"] == active["id"]
    assert practice["stem"] == active["stem"]
    assert solution == active
    assert solution["answer"] == "A"
    assert invalid.is_error is True


@pytest.mark.anyio
async def test_list_topics_counts_active_questions_by_year_with_corrections_and_filters(tmp_path):
    (tmp_path / "questions").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "corrections").mkdir()
    (tmp_path / "docs" / "tags.md").write_text(
        "# Tags\n\n## Registry (seeded)\n\n"
        "databases | Databases | area\n"
        "concurrency | Concurrency Control | topic\n"
        "empty-tag | Unused Topic | subtopic\n",
        encoding="utf-8",
    )
    questions = (
        {"id": "q1", "status": "active", "year": 2022, "tags": ["databases", "concurrency"]},
        {"id": "q2", "status": "active", "year": 2024, "tags": ["databases"]},
        {"id": "q3", "status": "active", "year": 2024, "tags": ["databases"]},
        {"id": "q4", "status": "suspended", "year": 2023, "tags": ["databases"]},
    )
    for q in questions:
        (tmp_path / "questions" / f"{q['id']}.json").write_text(json.dumps(q), encoding="utf-8")
    # Suspend q3 via corrections overlay so active count drops to 2 (one in 2022, one in 2024).
    (tmp_path / "corrections" / "log.jsonl").write_text(
        json.dumps({"question_id": "q3", "field": "status", "new_value": "suspended"}) + "\n",
        encoding="utf-8",
    )

    server = create_server(tmp_path)
    async with Client(server, mode="legacy") as client:
        all_topics = _tool_data(await client.call_tool("list-topics", {}))
        filtered = _tool_data(await client.call_tool("list-topics", {"query": "conc", "level": "topic"}))
        limited = _tool_data(await client.call_tool("list-topics", {"limit": 1}))
        bad_level = await client.call_tool("list-topics", {"level": "bogus"})

    assert all_topics["total"] == 3
    assert all_topics["topics"] == [
        {
            "slug": "databases",
            "name": "Databases",
            "level": "area",
            "active_questions": 2,
            "by_year": {"2022": 1, "2024": 1},
        },
        {
            "slug": "concurrency",
            "name": "Concurrency Control",
            "level": "topic",
            "active_questions": 1,
            "by_year": {"2022": 1},
        },
        {
            "slug": "empty-tag",
            "name": "Unused Topic",
            "level": "subtopic",
            "active_questions": 0,
            "by_year": {},
        },
    ]
    assert filtered["total"] == 1
    assert [t["slug"] for t in filtered["topics"]] == ["concurrency"]
    assert limited["total"] == 3
    assert len(limited["topics"]) == 1
    assert bad_level.is_error is True


@pytest.mark.anyio
async def test_get_stats_explains_an_absent_or_empty_log(fixture_bank):
    root, _, _ = fixture_bank
    server = create_server(root, search_core=lambda **_: [], embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        stats = _tool_data(await client.call_tool("get-stats"))
    assert stats["overall"] == {"total": 0, "correct": 0, "incorrect": 0, "accuracy": 0.0}
    assert stats["per_tag"] == []
    assert stats["note"] == "No answers log exists yet."

    answers_file = root / "data" / "users" / "marcos" / "answers.jsonl"
    answers_file.parent.mkdir(parents=True)
    answers_file.write_text("\n", encoding="utf-8")
    async with Client(server, mode="legacy") as client:
        empty_stats = _tool_data(await client.call_tool("get-stats"))
    assert empty_stats["overall"]["total"] == 0
    assert empty_stats["note"] == "The answers log is empty."


@pytest.mark.anyio
async def test_get_stats_aggregates_tags_exams_and_weeks(fixture_bank):
    root, _, _ = fixture_bank
    answers_file = root / "data" / "users" / "marcos" / "answers.jsonl"
    answers_file.parent.mkdir(parents=True)
    answers_file.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"id": "q1", "given_answer": "A", "is_correct": True, "tags": ["databases", "concurrency"], "exam": "poscomp", "year": 2024, "session_id": "s1", "timestamp": "2024-01-02T10:00:00Z"},
                {"id": "q2", "given_answer": "B", "is_correct": False, "tags": ["databases"], "exam": "poscomp", "year": 2024, "session_id": "s1", "timestamp": "2024-01-03T10:00:00Z"},
                {"id": "q3", "given_answer": "A", "is_correct": False, "tags": ["networks"], "exam": "enade", "year": 2024, "session_id": "s2", "timestamp": "2024-01-10T10:00:00Z"},
            ]
        ) + "\n",
        encoding="utf-8",
    )
    server = create_server(root, search_core=lambda **_: [], embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        stats = _tool_data(await client.call_tool("get-stats"))

    assert stats["overall"] == {"total": 3, "correct": 1, "incorrect": 2, "accuracy": 0.3333}
    assert stats["per_tag"] == [
        {"tag": "concurrency", "total": 1, "correct": 1, "incorrect": 0, "accuracy": 1.0},
        {"tag": "databases", "total": 2, "correct": 1, "incorrect": 1, "accuracy": 0.5},
        {"tag": "networks", "total": 1, "correct": 0, "incorrect": 1, "accuracy": 0.0},
    ]
    assert [entry["tag"] for entry in stats["error_ranking"]] == ["networks", "databases", "concurrency"]
    assert stats["per_exam"] == [
        {"exam": "enade", "total": 1, "correct": 0, "incorrect": 1, "accuracy": 0.0},
        {"exam": "poscomp", "total": 2, "correct": 1, "incorrect": 1, "accuracy": 0.5},
    ]
    assert stats["weekly_trend"] == [
        {"week": "2024-W01", "total": 2, "correct": 1, "incorrect": 1, "accuracy": 0.5},
        {"week": "2024-W02", "total": 1, "correct": 0, "incorrect": 1, "accuracy": 0.0},
    ]
