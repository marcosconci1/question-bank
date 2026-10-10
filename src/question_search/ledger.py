"""Content-hash ledger tracking question files, skipping unchanged, removing deleted."""
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import config


def file_hash(path: Path) -> str:
    """Compute hex SHA-256 digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_ledger(ledger_path: Path | None = None) -> dict[str, Any]:
    """Load the hash ledger from disk, or return empty structure."""
    path = ledger_path or config.LEDGER_PATH
    if not path.is_file():
        return {"version": 1, "questions": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "questions": {}}


def save_ledger(ledger: dict[str, Any], ledger_path: Path | None = None) -> None:
    """Save the ledger atomically."""
    path = ledger_path or config.LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_path, path)


def reconcile(
    questions_dir: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Compare disk state against the ledger to determine new, changed, unchanged, deleted items."""
    q_dir = questions_dir or config.QUESTIONS_DIR
    l_path = ledger_path or config.LEDGER_PATH
    ledger = load_ledger(l_path)
    stored_questions = ledger.get("questions", {})

    on_disk_files: dict[str, Path] = {}
    if q_dir.exists() and q_dir.is_dir():
        for p in q_dir.glob("*.json"):
            qid = p.stem
            on_disk_files[qid] = p

    to_index: list[dict[str, Any]] = []
    unchanged: list[str] = []
    deleted: list[dict[str, Any]] = []

    for qid, p in on_disk_files.items():
        curr_hash = file_hash(p)
        if qid in stored_questions:
            old_hash = stored_questions[qid].get("hash")
            if old_hash == curr_hash:
                unchanged.append(qid)
            else:
                to_index.append({
                    "question_id": qid,
                    "path": p,
                    "hash": curr_hash,
                    "is_new": False,
                    "old_hash": old_hash,
                })
        else:
            to_index.append({
                "question_id": qid,
                "path": p,
                "hash": curr_hash,
                "is_new": True,
                "old_hash": None,
            })

    for qid, entry in stored_questions.items():
        if qid not in on_disk_files:
            deleted.append({
                "question_id": qid,
                "point_id": entry.get("point_id"),
                "hash": entry.get("hash"),
            })

    return {
        "to_index": to_index,
        "unchanged": unchanged,
        "deleted": deleted,
        "total_on_disk": len(on_disk_files),
        "ledger": ledger,
    }


def record_indexed(
    ledger: dict[str, Any],
    question_id: str,
    path_rel: str,
    content_hash: str,
    point_id: int,
) -> None:
    """Record an indexed question in the ledger structure."""
    if "questions" not in ledger:
        ledger["questions"] = {}
    ledger["questions"][question_id] = {
        "path": path_rel,
        "hash": content_hash,
        "point_id": point_id,
    }


def record_deleted(ledger: dict[str, Any], question_id: str) -> None:
    """Remove a question from the ledger structure."""
    if "questions" in ledger and question_id in ledger["questions"]:
        del ledger["questions"][question_id]
