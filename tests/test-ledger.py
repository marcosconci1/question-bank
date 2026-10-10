"""Unit tests for content-hash ledger tracking."""
import json
from pathlib import Path
from question_search.ledger import (
    file_hash,
    load_ledger,
    reconcile,
    record_deleted,
    record_indexed,
    save_ledger,
)


def test_file_hash_deterministic(tmp_path):
    f = tmp_path / "sample.json"
    f.write_text('{"hello": "world"}', encoding="utf-8")
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2
    assert len(h1) == 64


def test_ledger_save_and_load(tmp_path):
    ledger_file = tmp_path / "ledger.json"
    data = {"version": 1, "questions": {"q1": {"path": "questions/q1.json", "hash": "abc", "point_id": 123}}}
    save_ledger(data, ledger_file)
    loaded = load_ledger(ledger_file)
    assert loaded == data


def test_ledger_reconcile_flow(tmp_path):
    qdir = tmp_path / "questions"
    qdir.mkdir()
    ledger_file = tmp_path / "ledger.json"

    # 1. Create two question files
    f1 = qdir / "q1.json"
    f1.write_text('{"id": "q1", "stem": "Pergunta 1"}', encoding="utf-8")
    f2 = qdir / "q2.json"
    f2.write_text('{"id": "q2", "stem": "Pergunta 2"}', encoding="utf-8")

    plan1 = reconcile(qdir, ledger_file)
    assert len(plan1["to_index"]) == 2
    assert len(plan1["unchanged"]) == 0
    assert len(plan1["deleted"]) == 0

    # 2. Record them in ledger and save
    state = plan1["ledger"]
    for item in plan1["to_index"]:
        record_indexed(
            state,
            question_id=item["question_id"],
            path_rel=f"questions/{item['question_id']}.json",
            content_hash=item["hash"],
            point_id=100,
        )
    save_ledger(state, ledger_file)

    # 3. Reconcile again: both should be unchanged
    plan2 = reconcile(qdir, ledger_file)
    assert len(plan2["to_index"]) == 0
    assert len(plan2["unchanged"]) == 2
    assert set(plan2["unchanged"]) == {"q1", "q2"}
    assert len(plan2["deleted"]) == 0

    # 4. Modify q1, delete q2, add q3
    f1.write_text('{"id": "q1", "stem": "Pergunta 1 MODIFICADA"}', encoding="utf-8")
    f2.unlink()
    f3 = qdir / "q3.json"
    f3.write_text('{"id": "q3", "stem": "Pergunta 3 NOVA"}', encoding="utf-8")

    plan3 = reconcile(qdir, ledger_file)
    to_idx_ids = {x["question_id"] for x in plan3["to_index"]}
    assert to_idx_ids == {"q1", "q3"}
    assert len(plan3["unchanged"]) == 0
    assert len(plan3["deleted"]) == 1
    assert plan3["deleted"][0]["question_id"] == "q2"
