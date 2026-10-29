"""Corrections overlay: audited fixes applied on top of generated question files.

``corrections/log.jsonl`` holds one JSON object per line:
``{question_id, field, new_value, old_value?, reason, source, date}``.
The question file stays untouched, so importers can regenerate it freely.
The last entry for a ``(question_id, field)`` pair wins.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROTECTED_FIELDS = {"id", "exam", "year", "number"}


def load_corrections(root: Path) -> dict[str, dict[str, Any]]:
    """Return ``{question_id: {field: new_value}}``. Bad lines are skipped."""

    log = root / "corrections" / "log.jsonl"
    result: dict[str, dict[str, Any]] = {}
    if not log.is_file():
        return result
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or "new_value" not in entry:
            continue
        qid, field = entry.get("question_id"), entry.get("field")
        if not isinstance(qid, str) or not isinstance(field, str):
            continue
        if field in PROTECTED_FIELDS or field == "new-question":
            continue
        result.setdefault(qid, {})[field] = entry["new_value"]
    return result


def apply_corrections(question: dict[str, Any], root: Path) -> dict[str, Any]:
    """Return ``question`` with the overlay applied (input is not mutated)."""

    fixes = load_corrections(root).get(str(question.get("id")), {})
    return {**question, **fixes} if fixes else question
