"""Tests for the generic adapter around the existing concurso parser."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from question_bank.concurso import extract_questions_from_pdf
from question_bank.ingest.board_adapter import BoardPdfAdapter
from question_bank.ingest.manifest import Source, load_manifest

# Sibling test files use dashed names, which Python cannot import directly;
# pytest still registers them, so reuse the shared fixture through importlib.
test_concurso = importlib.import_module("test-concurso")
_make_pdf = test_concurso._make_pdf
FGV_PAGES = test_concurso.FGV_PAGES


def test_board_adapter_preserves_existing_extractor_records(tmp_path: Path, monkeypatch):
    pdf = _make_pdf(tmp_path, "board.pdf", FGV_PAGES)
    extracted = extract_questions_from_pdf(pdf, "fgv")
    assert len(extracted) == 1

    # Keep answer-key I/O outside this adapter test; extraction remains the
    # real concurso.py implementation and its candidate fields are compared.
    monkeypatch.setattr(
        "question_bank.ingest.board_adapter.parse_gabarito_pdf",
        lambda _path, _banca: {"fixture": {1: "A"}},
    )
    monkeypatch.setattr(
        "question_bank.ingest.board_adapter.match_gabarito_section",
        lambda *_args: {1: "A"},
    )
    source = Source(
        id="fixture-board",
        kind="pdf-board",
        path=pdf,
        exam="fgv",
        year=2024,
        options={
            "banca": "fgv",
            "organ": "TRF1",
            "role": "Técnico Judiciário TI",
            "caderno": "Tipo 1",
            "gabarito_path": "answers.pdf",
            "prova_url": "https://example.org/prova.pdf",
            "prova_sha256": "a" * 64,
            "gabarito_url": "https://example.org/gabarito.pdf",
            "gabarito_sha256": "b" * 64,
        },
    )

    candidates = list(BoardPdfAdapter().read(source))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["number"] == extracted[0].number
    assert candidate["stem"] == extracted[0].stem
    assert candidate["options"] == extracted[0].options
    assert candidate["answer"] == "A"
    assert candidate["exam"] == "fgv"
    assert candidate["provenance"]["round_trip_verified"] is True


def test_manifest_rejects_pdf_board_without_board_metadata(tmp_path: Path):
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "id": "incomplete-board",
                    "kind": "pdf-board",
                    "path": "board.pdf",
                    "exam": "fgv",
                    "year": 2024,
                    "options": {"banca": "fgv", "organ": "TRF1"},
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires board metadata.*role.*caderno"):
        load_manifest(manifest)
