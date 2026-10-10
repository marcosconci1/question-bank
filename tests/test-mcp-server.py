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
    assert {tool.name for tool in tools.tools} == {"search-questions", "get-question", "get-stats"}


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
async def test_get_question_returns_the_complete_answer_bearing_object(fixture_bank):
    root, active, _ = fixture_bank
    server = create_server(root, search_core=lambda **_: [], embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        question = _tool_data(await client.call_tool("get-question", {"id": active["id"]}))
    assert question == active
    assert question["answer"] == "A"


@pytest.mark.anyio
async def test_get_stats_explains_an_absent_or_empty_log(fixture_bank):
    root, _, _ = fixture_bank
    server = create_server(root, search_core=lambda **_: [], embedder=lambda _: [[1.0]])
    async with Client(server, mode="legacy") as client:
        stats = _tool_data(await client.call_tool("get-stats"))
    assert stats["overall"] == {"total": 0, "correct": 0, "incorrect": 0, "accuracy": 0.0}
    assert stats["per_tag"] == []
    assert stats["note"] == "No answers log exists yet."

    (root / "data").mkdir()
    (root / "data" / "answers.jsonl").write_text("\n", encoding="utf-8")
    async with Client(server, mode="legacy") as client:
        empty_stats = _tool_data(await client.call_tool("get-stats"))
    assert empty_stats["overall"]["total"] == 0
    assert empty_stats["note"] == "The answers log is empty."


@pytest.mark.anyio
async def test_get_stats_aggregates_tags_exams_and_weeks(fixture_bank):
    root, _, _ = fixture_bank
    data_dir = root / "data"
    data_dir.mkdir()
    (data_dir / "answers.jsonl").write_text(
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
