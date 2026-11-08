import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from question_bank.cli import main
from question_bank.doctor import build_diagnose_bundle
from question_bank.journal import append_event, journal_path, trim_lines


def test_journal_retention_trims_old_and_oversized_entries():
    now = datetime.now(timezone.utc)
    old = {"ts": (now - timedelta(days=31)).isoformat(), "action": "old", "outcome": "ok"}
    fresh = {"ts": now.isoformat(), "action": "fresh", "outcome": "ok", "detail": "x" * 80}
    lines = [json.dumps(old), json.dumps(fresh)]

    assert trim_lines(lines, now=now, max_age_days=30) == [lines[1]]
    assert trim_lines(lines[1:], now=now, max_bytes=40) == []


def test_journal_scrubs_secrets_before_writing(tmp_path):
    append_event(tmp_path, "test", "ok", note="sk-or-v1-abcdefghijklmnopqrstuv", api_key="private-value",
                 authorization="Bearer super-secret-token")

    on_disk = journal_path(tmp_path).read_text(encoding="utf-8")
    assert "sk-or-v1-abcdefghijklmnopqrstuv" not in on_disk
    assert "private-value" not in on_disk
    assert "super-secret-token" not in on_disk
    event = json.loads(on_disk)
    assert event["api_key"] == "[REDACTED]"


def test_doctor_happy_path(tmp_path, monkeypatch, capsys):
    (tmp_path / "questions").mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "sources.json").write_text("[]", encoding="utf-8")
    (tmp_path / "questions" / "one.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path))

    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "OK: bank root" in output
    assert "1 files" in output
    assert "Summary: OK" in output


def test_doctor_fails_for_missing_bank_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QUESTION_BANK_ROOT", str(tmp_path / "missing"))

    assert main(["doctor"]) == 1
    assert "FAIL: bank root" in capsys.readouterr().out
    assert not (tmp_path / "missing").exists()


def test_diagnose_bundle_has_no_home_path_or_key_values(tmp_path, monkeypatch):
    root = tmp_path / "bank"
    (root / "questions").mkdir(parents=True)
    (root / "reports").mkdir()
    append_event(root, "ingest_finish", "ok", counts={"ingested": 2, "skipped": 1, "quarantined": 0},
                 debug="Bearer diagnose-secret-token sk-abcdefghijklmnopqrst")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-very-private-key-value")

    bundle = build_diagnose_bundle(root, last_events=10)
    rendered = json.dumps(bundle)

    assert str(Path.home()) not in rendered
    assert "diagnose-secret-token" not in rendered
    assert "sk-abcdefghijklmnopqrst" not in rendered
    assert "very-private-key-value" not in rendered
    assert bundle["openrouter_api_key_present"] is True
    assert bundle["ingest_summary"] == {"ingested": 2, "skipped": 1, "quarantined": 0}
