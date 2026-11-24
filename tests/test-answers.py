"""Unit tests for question_bank.answers module."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from question_bank import answers


def test_validate_user_accepts_valid_names():
    for name in ("default", "legacy_student", "alice", "user_123", "bob-smith", "u", "a" * 32):
        assert answers.validate_user(name) == name


def test_validate_user_rejects_invalid_names():
    for name in ("../x", "A", "", "user/name", "-invalid", "_invalid", "a" * 33, None, 123):
        with pytest.raises(ValueError):
            answers.validate_user(name)


def test_current_user_default_and_env(monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    assert answers.current_user() == "default"

    monkeypatch.setenv("QUESTION_BANK_USER", "student1")
    assert answers.current_user() == "student1"

    monkeypatch.setenv("QUESTION_BANK_USER", "../escape")
    with pytest.raises(ValueError):
        answers.current_user()


def test_answers_path(tmp_path, monkeypatch):
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    assert answers.answers_path(tmp_path) == tmp_path / "data" / "users" / "default" / "answers.jsonl"
    assert answers.answers_path(tmp_path, "alice") == tmp_path / "data" / "users" / "alice" / "answers.jsonl"

    with pytest.raises(ValueError):
        answers.answers_path(tmp_path, "../hack")


def test_list_and_create_users(tmp_path):
    assert answers.list_users(tmp_path) == []

    u1 = answers.create_user(tmp_path, "bob")
    assert u1.is_dir()
    assert answers.list_users(tmp_path) == ["bob"]

    # Idempotent
    answers.create_user(tmp_path, "bob")
    assert answers.list_users(tmp_path) == ["bob"]

    answers.create_user(tmp_path, "alice")
    assert answers.list_users(tmp_path) == ["alice", "bob"]

    # Invalid names rejected
    with pytest.raises(ValueError):
        answers.create_user(tmp_path, "../invalid")


def test_record_answer_and_duplicate_rejection(tmp_path):
    qdir = tmp_path / "questions"
    qdir.mkdir(parents=True)
    question = {
        "id": "poscomp-2024-01",
        "exam": "poscomp",
        "year": 2024,
        "tags": ["databases", "sql"],
        "answer": "B",
    }
    (qdir / "poscomp-2024-01.json").write_text(json.dumps(question), encoding="utf-8")

    req = {
        "question_id": "poscomp-2024-01",
        "session_id": "sess-1",
        "given_answer": "B",
        "is_correct": True,
        "time_spent": 15,
    }

    rec = answers.record_answer(tmp_path, "alice", req)
    assert rec["question_id"] == "poscomp-2024-01"
    assert rec["session_id"] == "sess-1"
    assert rec["exam"] == "poscomp"
    assert rec["year"] == 2024
    assert rec["tags"] == ["databases", "sql"]
    assert rec["time_spent"] == 15
    assert rec["is_correct"] is True

    user_answers_file = tmp_path / "data" / "users" / "alice" / "answers.jsonl"
    assert user_answers_file.is_file()

    read_back = answers.read_answers(user_answers_file)
    assert len(read_back) == 1
    assert read_back[0]["id"] == rec["id"]

    # Duplicate rejection
    with pytest.raises(ValueError, match="already recorded"):
        answers.record_answer(tmp_path, "alice", req)

    # Different session allows recording the same question
    req2 = dict(req, session_id="sess-2")
    rec2 = answers.record_answer(tmp_path, "alice", req2)
    assert rec2["session_id"] == "sess-2"

    read_back2 = answers.read_answers(user_answers_file)
    assert len(read_back2) == 2


def test_default_write_leaves_existing_user_history_untouched(tmp_path, monkeypatch):
    qdir = tmp_path / "questions"
    qdir.mkdir()
    (qdir / "q1.json").write_text(json.dumps({"id": "q1"}), encoding="utf-8")
    old_log = tmp_path / "data" / "users" / "legacy_student" / "answers.jsonl"
    old_log.parent.mkdir(parents=True)
    old_bytes = b'{"id":"historical"}\n'
    old_log.write_bytes(old_bytes)
    monkeypatch.delenv("QUESTION_BANK_USER", raising=False)
    request = {"question_id": "q1", "session_id": "s1", "given_answer": "A", "is_correct": True}

    answers.record_answer(tmp_path, answers.current_user(), request)
    assert (tmp_path / "data" / "users" / "default" / "answers.jsonl").is_file()
    assert old_log.read_bytes() == old_bytes

    monkeypatch.setenv("QUESTION_BANK_USER", "legacy_student")
    answers.record_answer(tmp_path, answers.current_user(), {**request, "session_id": "s2"})
    assert len(answers.read_answers(old_log)) == 2


def test_invalid_default_user_rejected_without_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("QUESTION_BANK_USER", "../escape")
    with pytest.raises(ValueError):
        answers.answers_path(tmp_path)
    assert not (tmp_path / "data").exists()


def test_read_answers_skips_bad_lines(tmp_path):
    answers_file = tmp_path / "data" / "users" / "bob" / "answers.jsonl"
    answers_file.parent.mkdir(parents=True)
    answers_file.write_text(
        '{"id": "1", "is_correct": true}\n'
        'invalid json\n'
        '\n'
        '42\n'
        '{"id": "2", "is_correct": false}\n',
        encoding="utf-8",
    )

    records = answers.read_answers(answers_file)
    assert len(records) == 2
    assert records[0]["id"] == "1"
    assert records[1]["id"] == "2"

    assert answers.read_answers(tmp_path / "nonexistent.jsonl") == []
