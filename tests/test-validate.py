"""Tests for the curation validator and one-shot promotion command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from question_bank.validate import (
    load_registered_tags,
    suspending_warning_codes,
    validate_bank,
)


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


def make_enade_question(question_id: str = "enade-2021-9") -> dict:
    question = make_question(question_id)
    question.update(
        {
            "exam": "enade",
            "year": 2021,
            "number": 9,
            "component": "specific",
            "course": "computer-science",
            "source": "ENADE 2021 Ciência da Computação, question 9",
        }
    )
    return question


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
    questions.mkdir(parents=True, exist_ok=True)
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


def test_mixed_legacy_and_image_backed_options_are_valid(tmp_path):
    question = make_question()
    question["options"] = [
        "alpha",
        [{"type": "text", "content": "bravo"}, {"type": "image", "src": "assets/b.png", "alt": "imagem da opção"}],
        [{"type": "image", "src": "assets/c.png", "alt": "imagem da opção"}],
        "delta",
        "echo",
    ]
    result = validate_one(tmp_path, question)
    assert result.format_clean
    assert result.question["options"][0] == "alpha"
    assert result.question["options"][3] == "delta"


def test_enade_objective_question_requires_supported_course_and_component(tmp_path):
    result = validate_one(tmp_path, make_enade_question())
    assert result.format_clean


def test_source_reviewed_complete_enade_records_have_no_mid_sentence_warning(tmp_path):
    objective = make_enade_question("enade-2014-10")
    objective["year"] = 2014
    objective["number"] = 10
    objective["stem"] = "Prompt complete; é correto o que se afirma em"
    assert "stem_ends_mid_sentence" not in codes(validate_one(tmp_path, objective))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exam", "poscomp"),
        ("year", 2017),
        ("number", 11),
        ("type", "discursive"),
    ],
)
def test_source_review_exception_requires_consistent_enade_identity(tmp_path, field, value):
    question = make_enade_question("enade-2014-10")
    question["year"] = 2014
    question["number"] = 10
    question["stem"] = "Prompt complete; é correto o que se afirma em"
    question[field] = value

    assert "stem_ends_mid_sentence" in codes(validate_one(tmp_path, question))


def test_source_review_exception_requires_filename_to_match_reviewed_id(tmp_path):
    question = make_enade_question("enade-2014-10")
    question["year"] = 2014
    question["number"] = 10
    question["stem"] = "Prompt complete; é correto o que se afirma em"

    assert "stem_ends_mid_sentence" in codes(
        validate_one(tmp_path, question, filename="enade-2014-11.json")
    )


def test_unreviewed_enade_stem_still_gets_mid_sentence_warning(tmp_path):
    question = make_enade_question("enade-2017-10")
    question["stem"] = "A respeito do problema, assinale a opção correta"
    assert "stem_ends_mid_sentence" in codes(validate_one(tmp_path, question))


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("exam", "Not Valid!", "invalid_exam"),
        ("year", 2019, "invalid_year"),
        ("component", "general", "invalid_component"),
        ("course", "information-systems", "invalid_course"),
    ],
)
def test_enade_scope_fields_are_enforced(tmp_path, field, value, expected):
    question = make_enade_question()
    question[field] = value
    result = validate_one(tmp_path, question)
    assert expected in codes(result)


def test_discursive_question_requires_only_a_rubric(tmp_path):
    question = make_enade_question("enade-2021-d3")
    question.update(
        {
            "type": "discursive",
            "number": 3,
            "rubric": [{"type": "text", "content": "Resposta esperada com justificativa."}],
        }
    )
    question.pop("options")
    question.pop("answer")
    result = validate_one(tmp_path, question)
    assert result.format_clean

    question["options"] = []
    question["answer"] = "A"
    (tmp_path / "forbidden").mkdir()
    result = validate_one(tmp_path / "forbidden", question)
    assert {"forbidden_options", "forbidden_answer"} <= codes(result)


def test_discursive_question_requires_nonempty_rubric(tmp_path):
    question = make_enade_question("enade-2021-d3")
    question.update({"type": "discursive", "number": 3, "rubric": []})
    question.pop("options")
    question.pop("answer")
    result = validate_one(tmp_path, question)
    assert "invalid_rubric_content" in codes(result)


def test_context_must_resolve_to_an_existing_context_file(tmp_path):
    question = make_enade_question()
    question["context"] = "enade-2021-context-1"
    result = validate_one(tmp_path, question)
    assert "missing_context" in codes(result)

    context_dir = tmp_path / "contexts"
    context_dir.mkdir()
    (context_dir / "enade-2021-context-1.json").write_text("{}", encoding="utf-8")
    questions_dir = tmp_path / "questions-ok"
    questions_dir.mkdir()
    write_question(questions_dir, question)
    result = validate_bank(questions_dir, write_registry(tmp_path)).questions[0]
    assert "missing_context" not in codes(result)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda question: question.pop("source"), "missing_required_field"),
        (lambda question: question.__setitem__("source", ""), "empty_required_field"),
        (lambda question: question.__setitem__("year", 2001), "invalid_year"),
        (lambda question: question.__setitem__("number", 101), "invalid_number"),
        (lambda question: question.__setitem__("type", "essay"), "invalid_type"),
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


def make_concurso_question(
    exam: str = "fgv",
    question_id: str = "fgv-trf1-2024-analista-ti-45",
) -> dict:
    return {
        "id": question_id,
        "type": "mc",
        "exam": exam,
        "year": 2024,
        "number": 45,
        "stem": "Considere uma tabela hash com encadeamento para armazenamento de chaves.",
        "options": ["alpha", "bravo", "charlie", "delta", "echo"],
        "answer": "C",
        "source": "FGV - TRF1 2024 (Analista de TI), questão 45",
        "tags": ["matematica"],
        "provenance": {
            "banca": exam,
            "organ": "TRF1",
            "role": "Analista Judiciário - TI",
            "roles": ["Analista Judiciário - TI"],
            "year": 2024,
            "exam_date": "2024-09-29",
            "caderno": "Tipo 1",
            "cadernos": ["Tipo 1"],
            "gabarito_kind": "definitivo",
            "prova_url": "https://conhecimento.fgv.br/sites/default/files/concursos/30.pdf",
            "prova_sha256": "a" * 64,
            "gabarito_url": "https://conhecimento.fgv.br/sites/default/files/concursos/gab.pdf",
            "gabarito_sha256": "b" * 64,
            "sources": [
                {
                    "kind": "prova",
                    "url": "https://conhecimento.fgv.br/sites/default/files/concursos/30.pdf",
                    "sha256": "a" * 64,
                },
                {
                    "kind": "definitivo",
                    "url": "https://conhecimento.fgv.br/sites/default/files/concursos/gab.pdf",
                    "sha256": "b" * 64,
                },
            ],
            "round_trip_verified": True,
        },
    }


@pytest.mark.parametrize("exam", ["fgv", "iades", "cesgranrio", "fcpc"])
def test_concurso_exams_validate_with_4_or_5_options_and_provenance(tmp_path, exam):
    q5 = make_concurso_question(exam=exam, question_id=f"{exam}-org-2024-ti-01")
    r5 = validate_one(tmp_path / f"{exam}-5", q5)
    assert r5.format_clean
    assert not r5.warnings

    q4 = make_concurso_question(exam=exam, question_id=f"{exam}-org-2010-ti-02")
    q4["year"] = 2010
    q4["provenance"]["year"] = 2010
    q4["options"] = ["alpha", "bravo", "charlie", "delta"]
    q4["answer"] = "D"
    r4 = validate_one(tmp_path / f"{exam}-4", q4)
    assert r4.format_clean


def test_concurso_validation_rejects_missing_or_invalid_provenance_and_bad_years(tmp_path):
    no_prov = make_concurso_question()
    no_prov.pop("provenance")
    assert "missing_provenance" in codes(validate_one(tmp_path / "no-prov", no_prov))

    bad_year = make_concurso_question()
    bad_year["year"] = 1989
    assert "invalid_year" in codes(validate_one(tmp_path / "bad-year", bad_year))

    bad_ans = make_concurso_question()
    bad_ans["options"] = ["alpha", "bravo", "charlie", "delta"]
    bad_ans["answer"] = "E"
    assert "answer_out_of_range" in codes(validate_one(tmp_path / "bad-ans", bad_ans))

    bad_src = make_concurso_question()
    bad_src["provenance"]["prova_url"] = "https://www.qconcursos.com/questoes/123"
    bad_src["provenance"]["sources"][0]["url"] = "https://www.qconcursos.com/questoes/123"
    assert "invalid_provenance_sources" in codes(validate_one(tmp_path / "bad-src", bad_src))

