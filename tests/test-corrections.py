"""Corrections overlay: fixes apply on read, source files stay untouched."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from question_bank.corrections import apply_corrections, load_corrections
from question_bank.validate import load_registered_tags, validate_question

MODULE_ROOT = Path(os.environ.get("QUESTION_BANK_ROOT", Path(__file__).resolve().parents[1]))
ENGINE_ROOT = Path(__file__).resolve().parents[1]

requires_bank = pytest.mark.skipif(
    not (MODULE_ROOT / "questions").is_dir(),
    reason="bank data not present (engine repo tests run on synthetic fixtures)",
)


def _log(root: Path, *entries: dict) -> None:
    (root / "corrections").mkdir()
    (root / "corrections" / "log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\nnot json\n", encoding="utf-8"
    )


def test_last_entry_wins_and_bad_lines_are_skipped(tmp_path):
    _log(
        tmp_path,
        {"question_id": "q1", "field": "answer", "new_value": "A"},
        {"question_id": "q1", "field": "answer", "new_value": "C"},
        {"question_id": "q1", "field": "id", "new_value": "hijack"},
        {"question_id": "q1", "field": "new-question", "new_value": "x"},
        {"question_id": "q1", "field": "answer"},
    )
    assert load_corrections(tmp_path) == {"q1": {"answer": "C"}}


def test_apply_does_not_mutate_and_ignores_other_ids(tmp_path):
    _log(tmp_path, {"question_id": "q1", "field": "status", "new_value": "suspended"})
    original = {"id": "q1", "status": "active"}
    assert apply_corrections(original, tmp_path)["status"] == "suspended"
    assert original["status"] == "active"
    other = {"id": "q2", "status": "active"}
    assert apply_corrections(other, tmp_path) is other


def test_no_log_is_a_noop(tmp_path):
    question = {"id": "q1"}
    assert apply_corrections(question, tmp_path) is question


def test_plugin_matches_module_overlay(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "qb_tools", ENGINE_ROOT / "integrations" / "hermes" / "question-bank" / "tools.py"
    )
    tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools)
    _log(tmp_path, {"question_id": "q1", "field": "answer", "new_value": "C"},
         {"question_id": "q1", "field": "number", "new_value": 9})
    monkeypatch.setattr(tools, "_bank_root", lambda: tmp_path)
    question = {"id": "q1", "answer": "A", "number": 1}
    assert tools._apply_corrections(question) == apply_corrections(question, tmp_path)


@requires_bank
def test_real_log_entries_yield_valid_questions():
    registered = load_registered_tags(MODULE_ROOT / "docs" / "tags.md")
    for qid in load_corrections(MODULE_ROOT):
        path = MODULE_ROOT / "questions" / f"{qid}.json"
        fixed = apply_corrections(json.loads(path.read_text(encoding="utf-8")), MODULE_ROOT)
        assert not validate_question(fixed, path, registered).errors, qid


@requires_bank
def test_enade_2014_13_has_all_numerals():
    fixed = apply_corrections(
        json.loads((MODULE_ROOT / "questions" / "enade-2014-13.json").read_text(encoding="utf-8")),
        MODULE_ROOT,
    )
    text = " ".join(b["content"] for b in fixed["stem"] if b["type"] == "text")
    for numeral in ("I.", "II.", "III.", "IV."):
        assert f"\n{numeral} " in text


def test_correction_triggers_reindex_only_for_fixed_question(tmp_path):
    from question_search import ledger

    questions = tmp_path / "questions"
    questions.mkdir()
    for qid in ("q1", "q2"):
        (questions / f"{qid}.json").write_text(json.dumps({"id": qid}), encoding="utf-8")
    ledger_path = tmp_path / "ledger.json"
    first = ledger.reconcile(questions, ledger_path)
    ledger.save_ledger(
        {"questions": {i["question_id"]: {"hash": i["hash"]} for i in first["to_index"]}},
        ledger_path,
    )
    assert ledger.reconcile(questions, ledger_path)["to_index"] == []
    _log(tmp_path, {"question_id": "q1", "field": "answer", "new_value": "B"})
    again = ledger.reconcile(questions, ledger_path)
    assert [i["question_id"] for i in again["to_index"]] == ["q1"]


@requires_bank
def test_enade_2017_9_removes_leaked_pdf_operators_and_keeps_figure():
    fixed = apply_corrections(
        json.loads((MODULE_ROOT / "questions" / "enade-2017-9.json").read_text(encoding="utf-8")),
        MODULE_ROOT,
    )
    assert fixed["stem"][0]["content"].startswith("Uma árvore AVL")
    assert "Tm a DT Na ND" not in fixed["stem"][0]["content"]
    assert fixed["stem"][1]["src"] == "assets/enade-2017-q09-stem-figure-1.png"
    assert fixed["answer"] == "A"
