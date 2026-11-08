"""Validation coverage for free-form exam slugs."""

from __future__ import annotations

from pathlib import Path

import pytest

from question_bank.validate import validate_question


def make_question(exam: object = "sat-math") -> dict:
    return {
        "id": "sat-math-2024-1",
        "type": "mc",
        "exam": exam,
        "year": 2024,
        "number": 1,
        "stem": "Which answer describes a useful mathematical property?",
        "options": ["alpha", "bravo", "charlie", "delta", "echo"],
        "answer": "A",
        "source": "SAT Math 2024, question 1",
        "tags": ["unregistered-generic-tag"],
    }


def result(question: dict, path: Path | None = None):
    return validate_question(question, path or Path(f"{question['id']}.json"), set())


def codes(validation) -> set[str]:
    return {issue.code for issue in validation.issues}


def test_generic_slug_passes_structural_validation_without_exam_specific_warnings():
    validation = result(make_question())
    assert validation.format_clean
    assert not validation.warnings
    assert "unregistered_tag" not in codes(validation)


@pytest.mark.parametrize("exam", ["", "Weird Exam!", None])
def test_exam_must_be_a_lowercase_slug(exam):
    validation = result(make_question(exam))
    assert "invalid_exam" in codes(validation)


def test_enade_rules_still_apply_to_enade_records():
    question = make_question("enade")
    question.update({"id": "enade-2019-1", "year": 2019, "component": "other", "course": "other"})
    validation = result(question)
    assert {"invalid_year", "invalid_component", "invalid_course"} <= codes(validation)


def test_concurso_records_still_require_provenance():
    question = make_question("fgv")
    question["id"] = "fgv-2024-1"
    validation = result(question)
    assert "missing_provenance" in codes(validation)

