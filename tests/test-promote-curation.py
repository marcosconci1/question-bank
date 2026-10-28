"""Tests for exam-scoped curation decisions."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from question_bank.validate import ValidationIssue

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "promote-curation.py"
SPEC = importlib.util.spec_from_file_location("promote_curation", SCRIPT)
assert SPEC and SPEC.loader
CURATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CURATION)


def result(exam: str, stem: str):
    return SimpleNamespace(
        question={"exam": exam, "type": "mc", "stem": stem},
        warnings=[ValidationIssue("stem_ends_mid_sentence", "heuristic warning", "warning")],
    )


def test_source_complete_enade_option_lead_ins_do_not_suspend():
    for question_id, ending in (
        ("enade-2005-50", "Estão certos apenas os itens"),
        ("enade-2005-66", "Estão certos apenas os trechos"),
        ("enade-2005-68", "São adequados apenas os requisitos"),
        ("enade-2005-43", "respectivamente, iguais a"),
    ):
        question = result("enade", f"Questão completa, {ending}")
        question.question.update(
            {
                "id": question_id,
                "year": 2005,
                "number": int(question_id.rsplit("-", 1)[1]),
                "options": ["A", "B", "C", "D", "E"],
                "answer": "A",
            }
        )
        assert CURATION.curation_reasons(question) == []


def test_incomplete_enade_and_poscomp_stems_remain_suspended():
    assert CURATION.curation_reasons(result("enade", "Enunciado incompleto")) == [
        "stem_ends_mid_sentence"
    ]
    assert CURATION.curation_reasons(result("poscomp", "Estão certos apenas os itens")) == [
        "stem_ends_mid_sentence"
    ]


def test_unverified_enade_table_question_remains_suspended():
    question = result("enade", "Tabela incompleta. Estão certos apenas os itens")
    question.question["id"] = "enade-2005-44"
    assert CURATION.curation_reasons(question) == ["stem_ends_mid_sentence"]


def test_reviewed_source_complete_enade_questions_are_promoted():
    for question_id in (
        "enade-2005-44",
        "enade-2014-9",
        "enade-2014-10",
        "enade-2014-11",
        "enade-2014-14",
        "enade-2014-15",
        "enade-2014-17",
        "enade-2014-18",
        "enade-2014-20",
        "enade-2014-21",
        "enade-2014-22",
        "enade-2014-23",
        "enade-2014-24",
        "enade-2014-25",
        "enade-2014-26",
        "enade-2014-27",
        "enade-2014-29",
        "enade-2014-30",
        "enade-2014-31",
        "enade-2014-32",
        "enade-2014-33",
    ):
        question = result("enade", "Complete prompt, é correto o que se afirma em")
        year, number = (int(part) for part in question_id.split("-")[1:])
        question.question.update(
            {
                "id": question_id,
                "year": year,
                "number": number,
                "options": ["A", "B", "C", "D", "E"],
                "answer": "A",
            }
        )
        assert CURATION.curation_reasons(question) == []


def test_reviewed_discursive_prompt_requires_official_rubric():
    question = result("enade", "Prompt completo, faça o que se pede.")
    question.question.update(
        {
            "id": "enade-2014-d4",
            "year": 2014,
            "number": 4,
            "type": "discursive",
            "rubric": "Expected response",
        }
    )
    assert CURATION.curation_reasons(question) == []

    question.question["rubric"] = ""
    assert CURATION.curation_reasons(question) == ["stem_ends_mid_sentence"]


def test_curation_source_review_exception_requires_matching_year():
    question = result("enade", "Complete prompt, é correto o que se afirma em")
    question.question.update(
        {
            "id": "enade-2014-10",
            "year": 2017,
            "number": 10,
            "options": ["A", "B", "C", "D", "E"],
            "answer": "A",
        }
    )
    assert CURATION.curation_reasons(question) == ["stem_ends_mid_sentence"]


def test_source_review_keeps_incomplete_stems_suspended_with_specific_reasons():
    for question_id, reason in (
        ("enade-2014-19", "source_stem_incomplete"),
        ("enade-2017-10", "source_stem_ocr_incomplete"),
    ):
        question = result("enade", "Unverified source stem")
        question.question["id"] = question_id
        assert CURATION.curation_reasons(question) == [reason]


def test_source_review_report_covers_all_32_requested_records():
    report_path = SCRIPT.parents[1] / "reports" / "enade-cc-suspended-review.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    reviewed_ids = {item["id"] for item in report["items"]}
    assert len(reviewed_ids) == 32
    assert report["summary"] == {"reviewed": 32, "complete": 23, "kept_suspended": 9}
    assert CURATION.SOURCE_VERIFIED_ENADE_COMPLETION_IDS.intersection(reviewed_ids) == {
        item["id"] for item in report["items"] if item["decision"] == "complete"
    }
