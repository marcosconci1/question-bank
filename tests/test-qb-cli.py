"""Tests for the umbrella question-bank / qb CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path

from question_bank.cli import main


def test_init_ingest_validate_search_stats_end_to_end(tmp_path, monkeypatch, capsys):
    bank = tmp_path / "my-bank"
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(bank))
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    assert main(["init", "--with-example"]) == 0
    assert (bank / "questions").is_dir()
    tags_path = bank / "docs" / "tags.md"
    repo_tags = Path(__file__).resolve().parents[1] / "docs" / "tags.md"
    assert tags_path.read_bytes() == repo_tags.read_bytes()
    assert (bank / "reports" / "example.csv").is_file()
    assert (bank / "reports" / "sources.json").is_file()

    # Re-running init is idempotent and does not overwrite existing files.
    sentinel = (bank / "reports" / "example.csv").read_text(encoding="utf-8")
    assert main(["init", "--with-example"]) == 0
    assert (bank / "reports" / "example.csv").read_text(encoding="utf-8") == sentinel
    capsys.readouterr()

    # Banks without a local registry use the bundled default.
    tags_path.unlink()
    assert main(["ingest", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ingested": 1, "skipped": 0, "quarantined": 0}

    # A bank-local registry can define a tag absent from the default.
    tags_path.write_text("## Registry\n\nlocal-hash | Local Hash Functions | topic\n", encoding="utf-8")
    (bank / "reports" / "example.csv").write_text(
        sentinel.replace("tabelas-hash", "local-hash"), encoding="utf-8"
    )
    assert main(["ingest", "--json"]) == 0
    ingest_summary = json.loads(capsys.readouterr().out)
    assert ingest_summary == {"ingested": 1, "skipped": 0, "quarantined": 0}

    assert main(["validate", "--json"]) == 0
    val_report = json.loads(capsys.readouterr().out)
    assert val_report["ok"] is True
    assert val_report["total"] == 1
    assert val_report["errors"] == 0

    assert main(["search", "query", "hash function", "--mode", "lexical", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert len(hits) == 1
    assert hits[0]["id"] == "sample-2025-1"

    assert main(["stats", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["bank_questions"] == 1
    assert stats["overall"]["total"] == 0

    assert main(["doctor"]) == 0
    doctor_report = capsys.readouterr().out
    assert "loaded; 1 tags" in doctor_report
    assert "Summary: OK" in doctor_report


def test_validate_returns_nonzero_on_invalid_question(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))
    assert main(["init"]) == 0
    (tmp_path / "questions" / "broken.json").write_text(json.dumps({"id": "broken"}), encoding="utf-8")
    capsys.readouterr()

    assert main(["validate", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["errors"] == 1
    assert report["details"][0]["file"] == "broken.json"
