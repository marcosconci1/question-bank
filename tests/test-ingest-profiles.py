"""Tests for JsonAdapter, declarative TOML profiles, and qb import."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from question_bank.cli import main
from question_bank.ingest.profiles import EXAMPLES_DIR, list_profiles, load_profile

pymupdf = pytest.importorskip("pymupdf")


def _make_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(36, 36, 559, 806), text, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def test_builtin_toml_profiles_load_cleanly():
    names = list_profiles()
    assert {"fgv", "iades", "cesgranrio", "fcpc", "poscomp", "enade"} <= set(names)
    for name in names:
        profile = load_profile(name, profiles_dir=EXAMPLES_DIR)
        assert profile.name == name
        assert profile.kind in {"csv", "json", "pdf-board", "pdf-llm"}
        assert profile.exam
        if profile.kind == "pdf-board":
            assert profile.options == {"board": profile.exam, "answer_key_kind": "final"}


def test_qb_import_json_and_jsonl_with_dedupe_and_rejects(tmp_path, monkeypatch, capsys):
    bank = tmp_path / "bank"
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(bank))
    assert main(["init"]) == 0
    capsys.readouterr()

    records = [
        {
            "id": "custom-2025-1",
            "type": "mc",
            "number": 1,
            "stem": "Which index structure keeps sorted keys in balanced multiway leaf pages?",
            "options": ["Hash table", "B+ tree", "Bloom filter", "Stack", "Trie"],
            "answer": "B",
            "source": "Custom 2025",
            "tags": ["arvore-b-mais"],
        },
        {
            "id": "custom-2025-1",  # duplicate within same import
            "type": "mc",
            "number": 1,
            "stem": "Duplicate entry should be skipped.",
            "options": ["A", "B", "C", "D", "E"],
            "answer": "A",
            "source": "Custom 2025",
            "tags": ["arvore-b-mais"],
        },
        {
            "id": "custom-2025-bad",
            "type": "mc",
            "number": 2,
            "stem": "Missing options should land in rejects.",
            "options": ["Only one"],
            "answer": "A",
            "source": "Custom 2025",
            "tags": ["arvore-b-mais"],
        },
    ]
    src_json = tmp_path / "batch.json"
    src_json.write_text(json.dumps(records), encoding="utf-8")
    rejects = tmp_path / "rejects.jsonl"

    assert main(["import", str(src_json), "--exam", "custom", "--year", "2025", "--rejects", str(rejects), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"ingested": 1, "skipped": 1, "quarantined": 1}
    assert (bank / "questions" / "custom-2025-1.json").is_file()
    rejected_lines = [json.loads(line) for line in rejects.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rejected_lines) == 1
    assert rejected_lines[0]["candidate_id"] == "custom-2025-bad"

    # Re-importing the same file skips the already-present record.
    assert main(["import", str(src_json), "--exam", "custom", "--year", "2025", "--dry-run", "--json"]) == 0
    rerun = json.loads(capsys.readouterr().out)
    assert rerun == {"ingested": 0, "skipped": 2, "quarantined": 1}


def test_qb_import_csv_with_poscomp_profile(tmp_path, monkeypatch, capsys):
    bank = tmp_path / "bank"
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(bank))
    assert main(["init"]) == 0
    capsys.readouterr()

    fixture_csv = Path(__file__).resolve().parent / "fixtures" / "ingest-poscomp.csv"
    assert main(["import", str(fixture_csv), "--profile", "poscomp", "--year", "2024", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ingested"] > 0
    assert summary["quarantined"] == 0


@pytest.mark.parametrize(
    ("kind_args", "status", "stored_kind"),
    [([], "active", "definitivo"), (["--answer-key-kind", "preliminary"], "suspended", "preliminar")],
)
def test_qb_import_pdf_with_fgv_profile(tmp_path, monkeypatch, capsys, kind_args, status, stored_kind):
    import importlib

    test_concurso = importlib.import_module("test-concurso")
    bank = tmp_path / "bank"
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(bank))
    assert main(["init"]) == 0
    capsys.readouterr()

    booklet = test_concurso._make_pdf(tmp_path, "booklet.pdf", test_concurso.FGV_PAGES)
    answer_key = _make_pdf(
        tmp_path / "answer-key.pdf",
        ["GABARITO\nTécnico Judiciário TI - TIPO 1\n1\nA\n"],
    )
    booklet_url = "https://conhecimento.fgv.br/concursos/teste/booklet.pdf"
    answer_key_url = "https://conhecimento.fgv.br/concursos/teste/answer-key.pdf"
    rc = main(
        [
            "import",
            "pdf",
            str(booklet),
            "--profile",
            "fgv",
            "--year",
            "2024",
            "--agency",
            "TRF1",
            "--role",
            "Técnico Judiciário TI",
            "--booklet",
            "Tipo 1",
            "--answer-key",
            str(answer_key),
            "--booklet-url",
            booklet_url,
            "--answer-key-url",
            answer_key_url,
            *kind_args,
            "--json",
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"ingested": 1, "skipped": 0, "quarantined": 0}
    imported = bank / "questions" / "fgv-2024-trf1-tecnico-judiciario-ti-tipo-1-001.json"
    record = json.loads(imported.read_text(encoding="utf-8"))
    assert record["answer"] == "A"
    assert record["status"] == status
    if status == "suspended":
        assert record["status_reason"] == "preliminary_answer_key"
    provenance = record["provenance"]
    assert provenance["round_trip_verified"] is True
    assert provenance["gabarito_kind"] == stored_kind
    assert provenance["prova_url"] == booklet_url
    assert provenance["gabarito_url"] == answer_key_url
    assert provenance["prova_sha256"] == hashlib.sha256(booklet.read_bytes()).hexdigest()
    assert provenance["gabarito_sha256"] == hashlib.sha256(answer_key.read_bytes()).hexdigest()
