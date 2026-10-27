"""Unit and integration tests for the question-bank web module."""

from __future__ import annotations

import json
from pathlib import Path
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

import pytest
from starlette.testclient import TestClient

from question_bank import answers
from web.server import create_app


@pytest.fixture
def web_bank(tmp_path):
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir(parents=True)
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True)

    # Asset fixture
    (assets_dir / "diagram.png").write_bytes(b"dummy png content")

    # Fixture questions
    q1 = {
        "id": "poscomp-2024-01",
        "exam": "poscomp",
        "year": 2024,
        "number": 1,
        "type": "mc",
        "status": "active",
        "stem": "What is SQL?",
        "options": ["A database language", "A browser", "An OS"],
        "answer": "A",
        "rubric": "Option A is the official definition.",
        "tags": ["databases", "sql"],
    }
    q2 = {
        "id": "poscomp-2024-02",
        "exam": "poscomp",
        "year": 2024,
        "number": 2,
        "type": "mc",
        "status": "suspended",
        "stem": "A suspended question about networks.",
        "options": ["LAN", "WAN"],
        "answer": "A",
        "tags": ["networks"],
    }
    q3 = {
        "id": "enade-2021-d1",
        "exam": "enade",
        "year": 2021,
        "number": 1,
        "type": "discursive",
        "status": "active",
        "stem": "Explain transaction isolation.",
        "answer": "Official explanation",
        "rubric": ["1 point for ACID", "2 points for isolation levels"],
        "tags": ["databases", "concurrency"],
    }
    for q in (q1, q2, q3):
        (questions_dir / f"{q['id']}.json").write_text(json.dumps(q), encoding="utf-8")

    return tmp_path, (q1, q2, q3)


def test_users_endpoints_and_traversal_rejection(web_bank):
    root, _ = web_bank
    app = create_app(root)
    client = TestClient(app)

    # Initially empty users
    res = client.get("/api/users")
    assert res.status_code == 200
    assert res.json() == {"users": []}

    # Create user
    res = client.post("/api/users", json={"name": "alice"})
    assert res.status_code == 201
    assert res.json() == {"name": "alice"}

    # Listed
    res = client.get("/api/users")
    assert res.status_code == 200
    assert res.json() == {"users": ["alice"]}

    # Reject traversal / invalid names on creation
    for bad in ("../escape", "Alice", "", "-bad", "a" * 33):
        res = client.post("/api/users", json={"name": bad})
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_user"

    # Reject traversal / invalid names in /api/u/{user}/ endpoints
    res = client.get("/api/u/../escape/stats")
    assert res.status_code in (400, 404)

    res = client.get("/api/u/UPPERCASE/stats")
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_user"

    # Unknown user returns 404
    res = client.get("/api/u/nonexistent/stats")
    assert res.status_code == 404
    assert res.json()["error"] == "user_not_found"


def test_question_endpoint_hides_answer(web_bank):
    root, (q1, _, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)

    # List questions
    res = client.get("/api/questions")
    assert res.status_code == 200
    data = res.json()
    # q2 is suspended, so default active only returns q1 and q3
    assert {q["id"] for q in data} == {q1["id"], q3["id"]}

    # With status=all
    res_all = client.get("/api/questions?status=all")
    assert res_all.status_code == 200
    assert len(res_all.json()) == 3

    # Filter by exam
    res_exam = client.get("/api/questions?exam=poscomp")
    assert res_exam.status_code == 200
    assert [q["id"] for q in res_exam.json()] == [q1["id"]]

    # Single question hides answer and rubric
    res_q1 = client.get(f"/api/questions/{q1['id']}")
    assert res_q1.status_code == 200
    safe_q1 = res_q1.json()
    assert "answer" not in safe_q1
    assert "rubric" not in safe_q1
    assert safe_q1["stem"] == q1["stem"]

    res_q3 = client.get(f"/api/questions/{q3['id']}")
    assert res_q3.status_code == 200
    safe_q3 = res_q3.json()
    assert "answer" not in safe_q3
    assert "rubric" not in safe_q3

    # Traversal or nonexistent
    assert client.get("/api/questions/../nonexistent").status_code == 404
    assert client.get("/api/questions/missing-id").status_code == 404


def test_session_creation(web_bank):
    root, (q1, q2, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)
    answers.create_user(root, "bob")

    # Session with active only
    res = client.post("/api/u/bob/sessions", json={"count": 5})
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert set(data["question_ids"]) == {q1["id"], q3["id"]}

    # Session including suspended
    res_susp = client.post("/api/u/bob/sessions", json={"count": 5, "include_suspended": True})
    assert res_susp.status_code == 200
    assert q2["id"] in res_susp.json()["question_ids"]

    # Session with tag filter
    res_tag = client.post("/api/u/bob/sessions", json={"tag": "concurrency"})
    assert res_tag.status_code == 200
    assert res_tag.json()["question_ids"] == [q3["id"]]


def test_answer_grading_correct_wrong_duplicate(web_bank):
    root, (q1, _, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)
    answers.create_user(root, "student")

    # Create session
    sess_res = client.post("/api/u/student/sessions", json={"count": 2})
    session_id = sess_res.json()["session_id"]

    # Multiple-choice correct
    ans_correct = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q1["id"],
            "session_id": session_id,
            "given_answer": "A",
            "time_spent": 10,
        },
    )
    assert ans_correct.status_code == 200
    body = ans_correct.json()
    assert body["is_correct"] is True
    assert body["correct_answer"] == "A"
    assert "record" in body
    assert body["record"]["time_spent"] == 10

    # Duplicate attempt in same session -> 409
    dup = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q1["id"],
            "session_id": session_id,
            "given_answer": "A",
        },
    )
    assert dup.status_code == 409
    assert dup.json()["error"] == "already_recorded"

    # New session: wrong answer
    ans_wrong = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q1["id"],
            "session_id": "sess-2",
            "given_answer": "C",
        },
    )
    assert ans_wrong.status_code == 200
    assert ans_wrong.json()["is_correct"] is False
    assert ans_wrong.json()["correct_answer"] == "A"

    # Discursive self-grading
    disc_correct = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q3["id"],
            "session_id": "sess-3",
            "given_answer": "Student essay",
            "self_grade": "correct",
        },
    )
    assert disc_correct.status_code == 200
    assert disc_correct.json()["is_correct"] is True
    assert disc_correct.json()["rubric"] == q3["rubric"]

    disc_partial = client.post(
        "/api/u/student/answer",
        json={
            "question_id": q3["id"],
            "session_id": "sess-4",
            "given_answer": "Student essay",
            "self_grade": "partial",
        },
    )
    assert disc_partial.status_code == 200
    assert disc_partial.json()["is_correct"] is False

    # Resume session records
    sess1_records = client.get(f"/api/u/student/session/{session_id}")
    assert sess1_records.status_code == 200
    assert len(sess1_records.json()) == 1
    assert sess1_records.json()[0]["question_id"] == q1["id"]


def test_stats_ordering_and_activity(web_bank):
    root, (q1, _, q3) = web_bank
    app = create_app(root)
    client = TestClient(app)
    answers.create_user(root, "statsuser")

    # student answers q1 (tags: databases, sql) correctly
    client.post(
        "/api/u/statsuser/answer",
        json={"question_id": q1["id"], "session_id": "s1", "given_answer": "A"},
    )
    # student answers q1 again in another session wrongly
    client.post(
        "/api/u/statsuser/answer",
        json={"question_id": q1["id"], "session_id": "s2", "given_answer": "B"},
    )
    # student answers q3 (tags: databases, concurrency) wrongly
    client.post(
        "/api/u/statsuser/answer",
        json={"question_id": q3["id"], "session_id": "s3", "given_answer": "essay", "self_grade": "wrong"},
    )

    res = client.get("/api/u/statsuser/stats")
    assert res.status_code == 200
    stats = res.json()

    assert stats["total"] == 3
    assert stats["correct"] == 1
    assert stats["accuracy"] == round(1 / 3, 4)

    # Stats group by topic (the second tag level), worst accuracy first.
    # concurrency: 0/1 = 0.0 accuracy
    # sql: 1/2 = 0.5 accuracy
    by_tag = stats["by_tag"]
    tags_in_order = [t["tag"] for t in by_tag]
    assert tags_in_order == ["concurrency", "sql"]

    # Check labels
    assert by_tag[0]["label"] == "Concurrency"
    assert by_tag[1]["label"] == "Sql"

    # Check activity array has 182 days
    activity = stats["activity"]
    assert len(activity) == 182
    assert activity[-1]["count"] == 3


def test_search_503_when_qdrant_unreachable(web_bank, monkeypatch):
    root, _ = web_bank
    app = create_app(root)
    client = TestClient(app)

    # Empty query returns empty list
    empty_res = client.get("/api/search?q=")
    assert empty_res.status_code == 200
    assert empty_res.json() == []

    # Search with qdrant unreachable returns 503
    res = client.get("/api/search?q=relational+databases")
    assert res.status_code == 503
    data = res.json()
    assert data["error"] == "search_unavailable"
    assert "message" in data


def test_security_headers_and_assets(web_bank):
    root, _ = web_bank
    app = create_app(root)
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"

    # Asset serving
    asset_res = client.get("/assets/diagram.png")
    assert asset_res.status_code == 200
    assert asset_res.content == b"dummy png content"

    # Asset traversal protection
    traversal_res = client.get("/assets/../../etc/passwd")
    assert traversal_res.status_code in (404, 400)
