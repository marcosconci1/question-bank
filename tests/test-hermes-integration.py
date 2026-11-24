"""Tests for the portable native Hermes question-bank adapter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


TOOLS_PATH = Path(__file__).resolve().parents[1] / "integrations" / "hermes" / "questionbank-tools.py"


def load_tools(monkeypatch: pytest.MonkeyPatch, enabled: bool = True):
    config = types.ModuleType("hermes_cli.config")
    config.load_config = lambda: {"question_bank": {"enabled": enabled}}
    package = types.ModuleType("hermes_cli")
    package.config = config
    monkeypatch.setitem(sys.modules, "hermes_cli", package)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config)
    spec = importlib.util.spec_from_file_location("questionbank_tools_test", TOOLS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToolContext:
    def __init__(self):
        self.tools = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


def test_register_exposes_exactly_the_four_read_only_tools(monkeypatch):
    tools = load_tools(monkeypatch)
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    assert tools._current_user() == "default"
    monkeypatch.setenv("QUESTION_BANK_USER", "legacy_student")
    assert tools._current_user() == "legacy_student"
    monkeypatch.setenv("QUESTION_BANK_USER", "../invalid")
    with pytest.raises(ValueError):
        tools._current_user()
    monkeypatch.delenv("QUESTION_BANK_USER")
    context = ToolContext()
    tools.register(context)
    assert [tool["name"] for tool in context.tools] == ["search-questions", "get-question", "list-topics", "get-stats"]
    assert all(tool["check_fn"] is tools.available for tool in context.tools)


def test_disabled_config_returns_json_error_from_every_handler(monkeypatch):
    tools = load_tools(monkeypatch, enabled=False)
    for handler, args in (
        (tools.search_questions, {"objective": "deadlock detection"}),
        (tools.get_question, {"id": "poscomp-2024-01"}),
        (tools.get_stats, {}),
        (tools.list_topics, {}),
    ):
        assert json.loads(handler(args)) == {"error": "question_bank_disabled"}


def test_get_question_returns_complete_object_including_answer_key(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    questions = tmp_path / "questions"
    questions.mkdir()
    expected = {"id": "poscomp-2024-01", "stem": "Which option?", "answer": "C", "rubric": "Answer C."}
    (questions / "poscomp-2024-01.json").write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))
    assert json.loads(tools.get_question({"id": "poscomp-2024-01"})) == expected


def test_search_passes_the_objective_to_question_search_cli(monkeypatch):
    tools = load_tools(monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return types.SimpleNamespace(returncode=0, stdout='[{"id": "poscomp-2024-01"}]', stderr="")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    result = json.loads(tools.search_questions({"objective": "transaction deadlocks", "limit": 3}))
    assert result == [{"id": "poscomp-2024-01"}]
    assert calls[0][0][1:] == ["query", "--json", "transaction deadlocks", "--top-k", "3", "--status", "active"]
    assert "PYTHONPATH" not in calls[0][1]["env"]
    assert "PYTHONHOME" not in calls[0][1]["env"]


def test_all_tools_leave_bank_files_unchanged(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    questions = tmp_path / "questions"
    questions.mkdir()
    question = {"id": "poscomp-2024-01", "stem": "Question", "answer": "A"}
    question_path = questions / "poscomp-2024-01.json"
    question_path.write_text(json.dumps(question), encoding="utf-8")
    answers_path = tmp_path / "data" / "users" / "default" / "answers.jsonl"
    answers_path.parent.mkdir(parents=True)
    answers_path.write_text(json.dumps({"is_correct": True, "tags": ["databases"], "exam": "poscomp"}) + "\n", encoding="utf-8")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda command, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout="[]" if command[1] == "query" else '{"bank_questions_on_disk": 1}',
            stderr="",
        ),
    )
    assert json.loads(tools.search_questions({"objective": "Question"})) == []
    assert json.loads(tools.get_question({"id": "poscomp-2024-01"}))["answer"] == "A"
    assert json.loads(tools.get_stats({}))["overall"]["total"] == 1
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_list_topics_counts_only_active_questions_and_applies_corrections(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))
    (tmp_path / "questions").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "tags.md").write_text(
        "# Tags\n\n## Registry (seeded)\n\n"
        "trees | Trees | topic\nsorting | Sorting | topic\navl | AVL | subtopic\n\n## Aliases\nignored | x | topic\n",
        encoding="utf-8",
    )
    for qid, status, tags in (("a", "active", ["trees", "avl"]), ("b", "active", ["trees"]), ("c", "suspended", ["trees"])):
        (tmp_path / "questions" / f"{qid}.json").write_text(
            json.dumps({"id": qid, "status": status, "tags": tags}), encoding="utf-8"
        )
    (tmp_path / "corrections").mkdir()
    (tmp_path / "corrections" / "log.jsonl").write_text(
        json.dumps({"question_id": "b", "field": "status", "new_value": "suspended"}) + "\n", encoding="utf-8"
    )
    result = json.loads(tools.list_topics({}))
    assert result["total"] == 3
    assert [(t["slug"], t["active_questions"]) for t in result["topics"]] == [
        ("avl", 1), ("trees", 1), ("sorting", 0)
    ]
    only = json.loads(tools.list_topics({"query": "tree", "level": "topic"}))
    assert [t["slug"] for t in only["topics"]] == ["trees"]
    assert "error" in json.loads(tools.list_topics({"level": "bogus"}))
    assert "error" in json.loads(tools.list_topics({"unknown": 1}))


def test_list_topics_reports_active_question_counts_by_year(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))
    (tmp_path / "questions").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "tags.md").write_text(
        "# Tags\n\n## Registry (seeded)\n\ntrees | Trees | topic\n", encoding="utf-8"
    )
    questions = (
        {"id": "early", "status": "active", "year": 2020, "tags": ["trees"]},
        {"id": "late", "status": "active", "year": 2023, "tags": ["trees"]},
        {"id": "missing-year", "status": "active", "tags": ["trees"]},
        {"id": "inactive", "status": "suspended", "year": 2024, "tags": ["trees"]},
    )
    for question in questions:
        (tmp_path / "questions" / f"{question['id']}.json").write_text(
            json.dumps(question), encoding="utf-8"
        )

    result = json.loads(tools.list_topics({}))
    topic = result["topics"][0]
    assert topic["active_questions"] == 3
    assert topic["by_year"] == {"2020": 1, "2023": 1}


def test_list_topics_falls_back_to_bundled_plugin_tags_standalone(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    bank = tmp_path / "bank"
    (bank / "questions").mkdir(parents=True)
    (bank / "questions" / "q1.json").write_text(
        json.dumps({"id": "q1", "status": "active", "year": 2024, "tags": ["banco-de-dados", "algebra-linear"]}),
        encoding="utf-8",
    )
    (bank / "questions" / "q2.json").write_text(
        json.dumps({"id": "q2", "status": "suspended", "year": 2023, "tags": ["banco-de-dados"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(bank))

    fallback = json.loads(tools.list_topics({"limit": 200}))
    assert "error" not in fallback, fallback
    assert fallback["total"] > 100
    top_two = {t["slug"]: t for t in fallback["topics"][:2]}
    assert set(top_two) == {"algebra-linear", "banco-de-dados"}
    assert top_two["banco-de-dados"] == {
        "slug": "banco-de-dados",
        "name": "Banco De Dados",
        "level": "topic",
        "active_questions": 1,
        "by_year": {"2024": 1},
    }
    for invalid in (
        {"level": "invalid"},
        {"limit": 0},
        {"limit": 201},
        {"limit": True},
        {"query": 42},
        {"extra": "bad"},
    ):
        assert json.loads(tools.list_topics(invalid))["error"] == "invalid_question_request"

    # Standalone plugin directory copied outside checkout works in isolated Python (-I) with no engine import
    import shutil
    import subprocess

    plugin_src = TOOLS_PATH.parent / "question-bank"
    standalone_dir = tmp_path / "isolated-hermes" / "plugins" / "question-bank"
    shutil.copytree(plugin_src, standalone_dir)
    script = (
        "import importlib.util, json, sys, types\n"
        "cfg = types.ModuleType('hermes_cli.config')\n"
        "cfg.load_config = lambda: {'question_bank': {'enabled': True}}\n"
        "pkg = types.ModuleType('hermes_cli'); pkg.config = cfg\n"
        "sys.modules['hermes_cli'] = pkg; sys.modules['hermes_cli.config'] = cfg\n"
        "spec = importlib.util.spec_from_file_location('standalone_qb', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
        "print(mod.list_topics({'query': 'banco de dados', 'level': 'topic'}))\n"
    )
    proc = subprocess.run(
        ["python3", "-I", "-c", script, str(standalone_dir / "tools.py")],
        env={"QUESTION_BANK_ROOT": str(bank)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    isolated_payload = json.loads(proc.stdout)
    assert isolated_payload == {
        "total": 1,
        "topics": [
            {
                "slug": "banco-de-dados",
                "name": "Banco De Dados",
                "level": "topic",
                "active_questions": 1,
                "by_year": {"2024": 1},
            }
        ],
    }


def test_bundled_plugin_tags_matches_engine_registry_and_topic_parity(monkeypatch, tmp_path):
    from starlette.testclient import TestClient

    from question_bank.mcp_server import _list_topics
    from question_bank.tag_registry import bundled_tags
    from web.server import create_app

    repo_root = TOOLS_PATH.parents[2]
    plugin_tags = repo_root / "integrations" / "hermes" / "question-bank" / "tags.md"
    engine_tags = repo_root / "src" / "question_bank" / "tags.md"
    assert plugin_tags.is_file()
    assert plugin_tags.read_bytes() == engine_tags.read_bytes() == bundled_tags().read_bytes()

    tools = load_tools(monkeypatch)
    bank = tmp_path / "parity-bank"
    (bank / "questions").mkdir(parents=True)
    (bank / "questions" / "q1.json").write_text(
        json.dumps({"id": "q1", "status": "active", "year": 2022, "tags": ["banco-de-dados"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(bank))

    # Parity on fallback registry (no bank/docs/tags.md)
    hermes_fallback = json.loads(tools.list_topics({"level": "area", "limit": 200}))
    mcp_fallback = _list_topics(bank, level="area", limit=200)
    web_fallback = TestClient(create_app(bank)).get("/api/topics", params={"level": "area", "limit": 200}).json()
    assert hermes_fallback == mcp_fallback == web_fallback

    # Parity on local bank/docs/tags.md override
    (bank / "docs").mkdir()
    (bank / "docs" / "tags.md").write_text(
        "# Local Override\n\n## Registry\n\nbanco-de-dados | Custom DB | topic\ncustom-area | Custom Area | area\n",
        encoding="utf-8",
    )
    hermes_override = json.loads(tools.list_topics({"limit": 200}))
    mcp_override = _list_topics(bank, limit=200)
    web_override = TestClient(create_app(bank)).get("/api/topics", params={"limit": 200}).json()
    assert hermes_override == mcp_override == web_override
    assert hermes_override["total"] == 2
    assert hermes_override["topics"][0]["name"] == "Custom DB"
