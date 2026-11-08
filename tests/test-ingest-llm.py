"""Offline coverage for generic text-layer PDF question extraction."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from question_bank.ingest.llm_adapter import PdfLlmAdapter
from question_bank.ingest.manifest import Source

test_concurso = importlib.import_module("test-concurso")
_make_pdf = test_concurso._make_pdf
FGV_PAGES = test_concurso.FGV_PAGES


class FakeLlm:
    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _source(pdf: Path, *, options: dict | None = None) -> Source:
    return Source(
        id="fixture-llm",
        kind="pdf-llm",
        path=pdf,
        exam="poscomp",
        year=2024,
        options=options or {},
    )


VALID_RESPONSE = json.dumps(
    [
        {
            "number": 1,
            "stem": "Considere a questão apresentada sobre uma estrutura de dados.",
            "options": {"A": "Alternativa correta", "B": "Alternativa incorreta"},
            "answer": "A",
        }
    ]
)


def test_llm_adapter_returns_candidate_with_provenance(tmp_path: Path):
    pdf = _make_pdf(tmp_path, "llm.pdf", FGV_PAGES)
    fake = FakeLlm(VALID_RESPONSE)
    adapter = PdfLlmAdapter(fake, model="test/model")

    candidates = list(adapter.read(_source(pdf)))

    assert len(fake.prompts) == 1
    assert "poscomp, year 2024" in fake.prompts[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["number"] == 1
    assert candidate["answer"] == "A"
    assert candidate["provenance"] == {
        "source_id": "fixture-llm",
        "adapter": "pdf-llm",
        "model": "test/model",
        "page_range": [1, 2],
    }
    assert adapter.page_accounting == [
        {"page": 1, "status": "yielded-candidate"},
        {"page": 2, "status": "yielded-candidate"},
    ]


def test_malformed_json_gets_one_repair_call_then_succeeds(tmp_path: Path):
    pdf = _make_pdf(tmp_path, "repair.pdf", FGV_PAGES)
    fake = FakeLlm("not JSON", VALID_RESPONSE)
    adapter = PdfLlmAdapter(fake)

    candidates = list(adapter.read(_source(pdf)))

    assert len(candidates) == 1
    assert len(fake.prompts) == 2
    assert "Validator error: invalid_json:" in fake.prompts[1]
    assert "Previous response:\nnot JSON" in fake.prompts[1]


def test_garbage_after_repair_quarantines_batch_and_accounts_pages(tmp_path: Path):
    pdf = _make_pdf(tmp_path, "garbage.pdf", FGV_PAGES)
    fake = FakeLlm("not JSON", "still not JSON")
    adapter = PdfLlmAdapter(fake)

    records = list(adapter.read(_source(pdf)))

    assert len(fake.prompts) == 2
    assert len(records) == 1
    assert records[0]["_ingest_error"].startswith("pdf_llm_invalid_batch:repair_failed:")
    assert records[0]["page_range"] == [1, 2]
    assert [item["status"] for item in adapter.page_accounting] == ["quarantined", "quarantined"]
    assert all(item["reason"].startswith("repair_failed:") for item in adapter.page_accounting)


def test_empty_page_text_is_skipped_without_llm_call(tmp_path: Path):
    pdf = _make_pdf(tmp_path, "blank.pdf", ["", "   \n\t"])
    fake = FakeLlm()
    adapter = PdfLlmAdapter(fake)

    assert list(adapter.read(_source(pdf))) == []
    assert fake.prompts == []
    assert adapter.page_accounting == [
        {"page": 1, "status": "empty"},
        {"page": 2, "status": "empty"},
    ]
