from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import types

import pytest


MODULE_ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT = MODULE_ROOT / "integrations" / "hermes"
TOOLS_PATH = HERMES_ROOT / "questionbank-tools.py"
PLUGIN_PATH = HERMES_ROOT / "question-bank" / "__init__.py"
RECORDER_PATH = HERMES_ROOT / "question-bank" / "skills" / "question-practice" / "scripts" / "record-answer.py"
CLAUDE_RECORDER_PATH = MODULE_ROOT / "integrations" / "claude" / "skills" / "question-practice" / "scripts" / "record-answer.py"


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
    assert [(name, path.is_file()) for name, path in context.skills] == [
        ("question-practice", True),
        ("exercise-list", True),
    ]


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
    lines = (tmp_path / "data" / "users" / "default" / "answers.jsonl").read_text(encoding="utf-8").splitlines()
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
    assert len((tmp_path / "data" / "users" / "default" / "answers.jsonl").read_text(encoding="utf-8").splitlines()) == 1


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
    saved = json.loads((tmp_path / "data" / "users" / "default" / "answers.jsonl").read_text(encoding="utf-8"))
    assert saved["given_answer"] == "A"
    assert saved["is_correct"] is False


@pytest.mark.parametrize("recorder_path", [RECORDER_PATH, CLAUDE_RECORDER_PATH])
def test_standalone_recorder_cli_defaults_and_explicit_user_without_host_context(tmp_path, recorder_path):
    question = {"id": "poscomp-2024-01", "exam": "poscomp", "year": 2024, "tags": []}
    write_question(tmp_path, question)
    old_log = tmp_path / "data" / "users" / "legacy_student" / "answers.jsonl"
    old_log.parent.mkdir(parents=True)
    old_bytes = b'{"id":"old-history"}\n'
    old_log.write_bytes(old_bytes)
    request = {"question_id": question["id"], "session_id": "cli", "given_answer": "A", "is_correct": True}

    default_result = subprocess.run(
        ["python3", "-I", str(recorder_path), "--input", "-"], input=json.dumps(request),
        capture_output=True, text=True, env={"QUESTION_BANK_ROOT": str(tmp_path)}, check=False,
    )
    assert default_result.returncode == 0, default_result.stderr
    default_log = tmp_path / "data" / "users" / "default" / "answers.jsonl"
    assert len(default_log.read_text(encoding="utf-8").splitlines()) == 1
    assert old_log.read_bytes() == old_bytes

    env_result = subprocess.run(
        ["python3", "-I", str(recorder_path), "--input", "-"],
        input=json.dumps({**request, "session_id": "cli-env"}), capture_output=True,
        text=True, env={"QUESTION_BANK_ROOT": str(tmp_path), "QUESTION_BANK_USER": "env_student"}, check=False,
    )
    assert env_result.returncode == 0, env_result.stderr
    env_log = tmp_path / "data" / "users" / "env_student" / "answers.jsonl"
    assert len(env_log.read_text(encoding="utf-8").splitlines()) == 1

    explicit_result = subprocess.run(
        ["python3", "-I", str(recorder_path), "--input", "-", "--user", "legacy_student"],
        input=json.dumps({**request, "session_id": "cli-explicit"}), capture_output=True,
        text=True, env={"QUESTION_BANK_ROOT": str(tmp_path), "QUESTION_BANK_USER": "env_student"}, check=False,
    )
    assert explicit_result.returncode == 0, explicit_result.stderr
    legacy_log = tmp_path / "data" / "users" / "legacy_student" / "answers.jsonl"
    assert len(legacy_log.read_text(encoding="utf-8").splitlines()) == 2
    duplicate_result = subprocess.run(
        ["python3", "-I", str(recorder_path), "--input", "-", "--user", "legacy_student"],
        input=json.dumps({**request, "session_id": "cli-explicit"}), capture_output=True,
        text=True, env={"QUESTION_BANK_ROOT": str(tmp_path)}, check=False,
    )
    assert duplicate_result.returncode == 2
    assert len(legacy_log.read_text(encoding="utf-8").splitlines()) == 2
    before_invalid = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    invalid_result = subprocess.run(
        ["python3", "-I", str(recorder_path), "--input", "-", "--user", "../escape"],
        input=json.dumps({**request, "session_id": "invalid"}), capture_output=True,
        text=True, env={"QUESTION_BANK_ROOT": str(tmp_path)}, check=False,
    )
    assert invalid_result.returncode == 2
    after_invalid = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after_invalid == before_invalid

    invalid_env_result = subprocess.run(
        ["python3", "-I", str(recorder_path), "--input", "-"],
        input=json.dumps({**request, "session_id": "invalid-env"}), capture_output=True,
        text=True, env={"QUESTION_BANK_ROOT": str(tmp_path), "QUESTION_BANK_USER": "../escape"}, check=False,
    )
    assert invalid_env_result.returncode == 2
    after_invalid_env = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after_invalid_env == before_invalid


def test_shipped_skill_contracts_are_portable_and_host_specific():
    claude_practice = (MODULE_ROOT / "integrations/claude/skills/question-practice/SKILL.md").read_text(encoding="utf-8")
    hermes_practice = (MODULE_ROOT / "integrations/hermes/question-bank/skills/question-practice/SKILL.md").read_text(encoding="utf-8")
    for skill in (claude_practice, hermes_practice):
        assert "version: 0.2.0" in skill
    for forbidden in ("question_bank.enabled", "vision_analyze", "terminal", "library"):
        assert forbidden not in claude_practice
    for required in ("search-questions", "get-question", "get-stats", "Read", "Bash"):
        assert required in claude_practice
    assert "${CLAUDE_SKILL_DIR}" in claude_practice
    assert "get-question(id)" in claude_practice
    assert "practice" in claude_practice
    claude_recorder = CLAUDE_RECORDER_PATH.read_text(encoding="utf-8")
    assert "hermes" not in claude_recorder.lower()
    assert "from question_bank" not in claude_recorder
    assert "import question_bank" not in claude_recorder

    for platform in ("claude", "hermes"):
        exercise_path = (
            MODULE_ROOT / f"integrations/{platform}/skills/exercise-list/SKILL.md"
            if platform == "claude"
            else MODULE_ROOT / "integrations/hermes/question-bank/skills/exercise-list/SKILL.md"
        )
        exercise = exercise_path.read_text(encoding="utf-8")
        assert "version: 0.2.0" in exercise
        assert "learner supplies a syllabus or course-material path" in exercise
        assert "Save only on explicit request" in exercise
        assert "report its question ID" in exercise
        assert re.search(r"~/(?=\S)", exercise) is None
        for forbidden in ("ROADMAP.md", "question-bank-repair"):
            assert forbidden not in exercise


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
