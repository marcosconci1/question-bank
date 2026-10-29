from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest


MODULE_ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT = MODULE_ROOT / "integrations" / "hermes"
TOOLS_PATH = HERMES_ROOT / "questionbank-tools.py"
PLUGIN_PATH = HERMES_ROOT / "question-bank" / "__init__.py"
RECORDER_PATH = HERMES_ROOT / "question-bank" / "skills" / "question-practice" / "scripts" / "record-answer.py"


def load_module(monkeypatch: pytest.MonkeyPatch, path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def load_tools(monkeypatch: pytest.MonkeyPatch):
    config = types.ModuleType("hermes_cli.config")
    config.load_config = lambda: {"question_bank": {"enabled": True}}
    package = types.ModuleType("hermes_cli")
    package.config = config
    monkeypatch.setitem(sys.modules, "hermes_cli", package)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config)
    return load_module(monkeypatch, TOOLS_PATH, "question_practice_tools_test")


class ToolContext:
    def __init__(self):
        self.tools = []
        self.skills = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_skill(self, name, path):
        self.skills.append((name, path))


def write_question(root: Path, question: dict) -> Path:
    questions = root / "questions"
    questions.mkdir(parents=True, exist_ok=True)
    path = questions / f"{question['id']}.json"
    path.write_text(json.dumps(question), encoding="utf-8")
    return path


def test_practice_view_redacts_answers_and_resolves_images(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    image = tmp_path / "assets" / "choice.png"
    image.parent.mkdir()
    image.write_bytes(b"png")
    question = {
        "id": "poscomp-2024-01",
        "stem": [{"type": "image", "src": "assets/choice.png", "alt": "choice"}],
        "options": ["A", "B", "C", "D", "E"],
        "answer": "C",
    }
    write_question(tmp_path, question)
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))

    practice = json.loads(tools.get_question({"id": question["id"], "view": "practice"}))
    assert "answer" not in practice
    assert practice["stem"][0]["src"] == str(image)
    solution = json.loads(tools.get_question({"id": question["id"], "view": "solution"}))
    assert solution["answer"] == "C"
    assert solution["stem"][0]["src"] == str(image)
    legacy = json.loads(tools.get_question({"id": question["id"]}))
    assert legacy == question


def test_practice_view_withholds_discursive_rubric(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    question = {"id": "enade-2021-d3", "stem": "Discuss.", "rubric": ["Expected answer"]}
    write_question(tmp_path, question)
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))

    assert "rubric" not in json.loads(tools.get_question({"id": question["id"], "view": "practice"}))
    assert json.loads(tools.get_question({"id": question["id"], "view": "solution"}))["rubric"] == ["Expected answer"]
    assert json.loads(tools.get_question({"id": question["id"], "view": "invalid"})) == {
        "error": "invalid_question_request", "field": "view"
    }


def test_plugin_registers_four_tools_and_practice_skills(monkeypatch):
    plugin = load_module(monkeypatch, PLUGIN_PATH, "question_bank_plugin_test")
    context = ToolContext()
    plugin.register(context)

    assert [tool["name"] for tool in context.tools] == ["search-questions", "get-question", "list-topics", "get-stats"]
    view = context.tools[1]["schema"]["parameters"]["properties"]["view"]
    assert view["enum"] == ["practice", "solution"]
    assert [(name, path.is_file()) for name, path in context.skills] == [("question-practice", True)]


def test_recorder_appends_denormalized_attempt_and_rejects_duplicate(monkeypatch, tmp_path):
    recorder = load_module(monkeypatch, RECORDER_PATH, "question_answer_recorder_test")
    question = {"id": "poscomp-2024-01", "exam": "poscomp", "year": 2024, "tags": ["databases"]}
    question_path = write_question(tmp_path, question)
    before = question_path.read_bytes()
    request = {
        "question_id": question["id"],
        "session_id": "session-test",
        "given_answer": "C",
        "is_correct": True,
        "time_spent": 42,
    }

    record = recorder.record_answer(request, bank_root=tmp_path)
    lines = (tmp_path / "data" / "users" / "marcos" / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved == record
    assert saved["exam"] == "poscomp"
    assert saved["year"] == 2024
    assert saved["tags"] == ["databases"]
    assert saved["time_spent"] == 42
    assert saved["timestamp"].endswith("Z")
    assert question_path.read_bytes() == before

    with pytest.raises(ValueError, match="already recorded"):
        recorder.record_answer(request, bank_root=tmp_path)
    assert len((tmp_path / "data" / "users" / "marcos" / "answers.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_recorder_cli_accepts_json_on_standard_input(tmp_path):
    question = {"id": "poscomp-2024-01", "exam": "poscomp", "year": 2024, "tags": ["databases"]}
    write_question(tmp_path, question)
    request = {
        "question_id": question["id"],
        "session_id": "session-cli",
        "given_answer": "A",
        "is_correct": False,
    }
    result = subprocess.run(
        [sys.executable, str(RECORDER_PATH), "--input", "-"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env={"QUESTION_BANK_ROOT": str(tmp_path)},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    saved = json.loads((tmp_path / "data" / "users" / "marcos" / "answers.jsonl").read_text(encoding="utf-8"))
    assert saved["given_answer"] == "A"
    assert saved["is_correct"] is False


def test_recorded_attempt_feeds_stats_error_ranking(monkeypatch, tmp_path):
    tools = load_tools(monkeypatch)
    recorder = load_module(monkeypatch, RECORDER_PATH, "question_answer_stats_recorder_test")
    question = {"id": "poscomp-2024-01", "exam": "poscomp", "year": 2024, "tags": ["databases"]}
    write_question(tmp_path, question)
    recorder.record_answer(
        {
            "question_id": question["id"],
            "session_id": "session-stats",
            "given_answer": "A",
            "is_correct": False,
        },
        bank_root=tmp_path,
    )
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda command, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout='{"qdrant_points": 1, "pending_indexing": 0}',
            stderr="",
        ),
    )

    stats = json.loads(tools.get_stats({}))
    assert stats["overall"] == {"total": 1, "correct": 0, "incorrect": 1, "accuracy": 0.0}
    assert stats["error_ranking"][0] == {
        "tag": "databases",
        "total": 1,
        "correct": 0,
        "incorrect": 1,
        "accuracy": 0.0,
    }
    assert stats["index_status"] == {"qdrant_points": 1, "pending_indexing": 0}
