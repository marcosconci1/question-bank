"""Tests for the curation validator and one-shot promotion command."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from question_bank.validate import load_registered_tags, suspending_warning_codes, validate_bank


def make_question(question_id: str = "poscomp-2024-01") -> dict:
    return {
        "id": question_id,
        "type": "mc",
        "exam": "poscomp",
        "year": 2024,
        "number": 1,
        "stem": "Qual alternativa descreve corretamente uma propriedade importante?",
        "options": ["alpha", "bravo", "charlie", "delta", "echo"],
        "answer": "A",
        "source": "POSCOMP 2024, question 1",
        "tags": ["matematica"],
    }


def write_registry(tmp_path: Path, tags: tuple[str, ...] = ("matematica",)) -> Path:
    path = tmp_path / "tags.md"
    entries = "\n".join(f"{tag} | {tag} | area" for tag in tags)
    path.write_text(f"# Tags\n\n## Registry\n\n{entries}\n\n## Aliases\n", encoding="utf-8")
    return path


def write_question(directory: Path, question: dict, filename: str | None = None) -> Path:
    path = directory / (filename or f"{question['id']}.json")
    path.write_text(json.dumps(question, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def validate_one(tmp_path: Path, question: dict, filename: str | None = None):
    questions = tmp_path / "questions"
    questions.mkdir()
    write_question(questions, question, filename)
    return validate_bank(questions, write_registry(tmp_path)).questions[0]


def codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_valid_question_passes_and_bare_string_shorthand_is_valid(tmp_path):
    result = validate_one(tmp_path, make_question())
    assert result.format_clean
    assert not result.warnings


def test_schema_v2_block_lists_are_valid(tmp_path):
    question = make_question()
    question["stem"] = [{"type": "text", "content": question["stem"]}]
    question["options"] = [[{"type": "text", "content": option}] for option in question["options"]]
    result = validate_one(tmp_path, question)
    assert result.format_clean


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda question: question.pop("source"), "missing_required_field"),
        (lambda question: question.__setitem__("source", ""), "empty_required_field"),
        (lambda question: question.__setitem__("year", 2001), "invalid_year"),
        (lambda question: question.__setitem__("number", 101), "invalid_number"),
        (lambda question: question.__setitem__("type", "discursive"), "invalid_type"),
        (lambda question: question.__setitem__("options", question["options"][:4]), "invalid_option_count"),
        (lambda question: question["options"].__setitem__(2, ""), "empty_option_text"),
        (lambda question: question.__setitem__("answer", "F"), "invalid_answer"),
        (lambda question: question.__setitem__("tags", ["not-registered"]), "unregistered_tag"),
        (lambda question: question.__setitem__("stem", [{"type": "image", "src": "asset.png"}]), "invalid_stem_content"),
    ],
)
def test_format_failure_modes_are_detected(tmp_path, mutate, expected):
    question = make_question()
    mutate(question)
    result = validate_one(tmp_path, question)
    assert expected in codes(result)
    assert not result.format_clean


def test_id_filename_mismatch_and_duplicate_ids_are_detected(tmp_path):
    questions = tmp_path / "questions"
    questions.mkdir()
    first = make_question("poscomp-2024-01")
    second = make_question("poscomp-2024-01")
    write_question(questions, first, "wrong-name.json")
    write_question(questions, second, "another-name.json")
    report = validate_bank(questions, write_registry(tmp_path))
    assert all("duplicate_id" in codes(result) for result in report.questions)
    assert all("id_filename_mismatch" in codes(result) for result in report.questions)


def test_content_heuristics_are_warnings(tmp_path):
    question = make_question()
    question["stem"] = "Curta sem ponto"
    question["options"] = ["mesma opcao", "mesma opcao!", "charlie", "delta", "echo"]
    result = validate_one(tmp_path, question)
    assert result.format_clean
    assert {"short_stem", "stem_ends_mid_sentence", "near_duplicate_options"} <= codes(result)
    assert suspending_warning_codes(result.warnings) == ["short_stem", "stem_ends_mid_sentence"]


def test_registry_parser_uses_registry_section_only(tmp_path):
    tags_path = write_registry(tmp_path, ("matematica",))
    tags_path.write_text(
        tags_path.read_text(encoding="utf-8") + "\nexample | outside registry | area\n",
        encoding="utf-8",
    )
    assert load_registered_tags(tags_path) == {"matematica"}


def test_promotion_appends_fields_atomically_without_reformatting_existing_content(tmp_path):
    questions = tmp_path / "questions"
    questions.mkdir()
    active = make_question("poscomp-2024-01")
    suspended = make_question("poscomp-2024-02")
    suspended["number"] = 2
    suspended["stem"] = "Curta sem ponto"
    active_path = write_question(questions, active)
    suspended_path = write_question(questions, suspended)
    original_active = active_path.read_text(encoding="utf-8").rstrip()

    script = Path(__file__).resolve().parents[1] / "scripts" / "promote-curation.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--questions", str(questions), "--tags", str(write_registry(tmp_path))],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"total": 2, "active": 1, "suspended": 1}
    active_data = json.loads(active_path.read_text(encoding="utf-8"))
    suspended_data = json.loads(suspended_path.read_text(encoding="utf-8"))
    assert active_data["status"] == "active"
    assert "status_reason" not in active_data
    assert suspended_data["status"] == "suspended"
    assert suspended_data["status_reason"] == "short_stem;stem_ends_mid_sentence"
    promoted_active = active_path.read_text(encoding="utf-8")
    assert promoted_active.replace(',\n  "status": "active"', "") == original_active + "\n"


def test_update_reaudits_existing_fields_and_is_idempotent(tmp_path):
    questions = tmp_path / "questions"
    questions.mkdir()
    advisory = make_question("poscomp-2024-01")
    advisory["options"] = ["mesma opcao", "mesma opcao!", "charlie", "delta", "echo"]
    advisory["status"] = "suspended"
    advisory["status_reason"] = "near_duplicate_options"
    incomplete = make_question("poscomp-2024-02")
    incomplete["number"] = 2
    incomplete["stem"] = "Curta sem ponto"
    incomplete["status"] = "active"
    advisory_path = write_question(questions, advisory)
    incomplete_path = write_question(questions, incomplete)

    script = Path(__file__).resolve().parents[1] / "scripts" / "promote-curation.py"
    command = [
        sys.executable,
        str(script),
        "--update",
        "--questions",
        str(questions),
        "--tags",
        str(write_registry(tmp_path)),
    ]
    first = subprocess.run(command, check=False, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout) == {"total": 2, "active": 1, "suspended": 1}
    advisory_data = json.loads(advisory_path.read_text(encoding="utf-8"))
    incomplete_data = json.loads(incomplete_path.read_text(encoding="utf-8"))
    assert advisory_data["status"] == "active"
    assert "status_reason" not in advisory_data
    assert incomplete_data["status"] == "suspended"
    assert incomplete_data["status_reason"] == "short_stem;stem_ends_mid_sentence"

    after_first = {path: path.read_bytes() for path in questions.glob("*.json")}
    second = subprocess.run(command, check=False, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert {path: path.read_bytes() for path in questions.glob("*.json")} == after_first
