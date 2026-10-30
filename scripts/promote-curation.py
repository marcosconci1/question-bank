#!/usr/bin/env python3
"""Promote format-clean questions and suspend incomplete-text exceptions."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from question_bank.validate import (
    CONCURSO_EXAMS,
    SOURCE_COMPLETE_ENADE_IDS,
    is_source_reviewed_complete_enade,
    is_verified_concurso_record,
    issue_codes,
    suspending_warning_codes,
    validate_bank,
)

JSON_STRING = r'"(?:\\.|[^"\\])*"'
CURATION_FIELDS = re.compile(
    rf',\r?\n[ \t]*"status"\s*:\s*{JSON_STRING}'
    rf'(?:,\r?\n[ \t]*"status_reason"\s*:\s*{JSON_STRING})?'
    r'(?=\r?\n[ \t]*})'
)
SOURCE_VERIFIED_ENADE_COMPLETION_IDS = SOURCE_COMPLETE_ENADE_IDS
SOURCE_INCOMPLETE_ENADE_REASONS = {
    "enade-2014-19": "source_stem_incomplete",
    "enade-2017-10": "source_stem_ocr_incomplete",
    "enade-2017-11": "source_stem_ocr_incomplete",
    "enade-2017-14": "source_stem_ocr_incomplete",
    "enade-2017-15": "source_stem_ocr_incomplete",
    "enade-2017-16": "source_stem_ocr_incomplete",
    "enade-2017-20": "source_stem_ocr_incomplete",
    "enade-2017-22": "source_stem_ocr_incomplete",
    "enade-2017-25": "source_stem_ocr_incomplete",
}


def curation_reasons(result) -> list[str]:
    """Return suspension warnings, excluding source-verified ENADE choice lead-ins.

    The review report records exact source PDF hashes, page evidence, and
    answer-key or rubric checks for each allowlisted record. For objective
    records, the official page and all five alternatives complete the prompt;
    for discursive records, the official prompt and rubric are both present.
    """

    reasons = suspending_warning_codes(result.warnings)
    question = result.question
    if question.get("exam") in CONCURSO_EXAMS:
        provenance = question.get("provenance") or {}
        question_path = getattr(result, "path", Path(f"{question.get('id')}.json"))
        if is_verified_concurso_record(question, question_path):
            reasons = [reason for reason in reasons if reason != "stem_ends_mid_sentence"]
        if (
            provenance.get("gabarito_kind") == "preliminar"
            or question.get("status_reason") == "preliminary_answer_key"
        ) and "preliminary_answer_key" not in reasons:
            reasons.append("preliminary_answer_key")
        return reasons
    if question.get("exam") != "enade":
        return reasons
    question_id = question.get("id")
    if question_id in SOURCE_INCOMPLETE_ENADE_REASONS:
        specific_reason = SOURCE_INCOMPLETE_ENADE_REASONS[question_id]
        return [specific_reason if reason == "stem_ends_mid_sentence" else reason for reason in reasons] or [specific_reason]
    if question_id not in SOURCE_VERIFIED_ENADE_COMPLETION_IDS:
        return reasons
    question_path = getattr(result, "path", Path(f"{question_id}.json"))
    if not is_source_reviewed_complete_enade(question, question_path):
        return reasons
    if question.get("type") == "discursive":
        rubric = question.get("rubric")
        has_rubric = bool(rubric.strip()) if isinstance(rubric, str) else bool(rubric)
        if has_rubric and not question.get("options") and not question.get("answer"):
            return [reason for reason in reasons if reason != "stem_ends_mid_sentence"]
        return reasons
    if question.get("type") != "mc" or len(question.get("options", [])) != 5 or not question.get("answer"):
        return reasons
    return [reason for reason in reasons if reason != "stem_ends_mid_sentence"]


def append_status(raw: str, status: str, reason: str | None) -> str:
    """Append curation fields without reserializing or reordering existing JSON."""

    if '"status"' in raw or '"status_reason"' in raw:
        raise ValueError("one-shot promotion requires question files without curation fields")
    closing_index = raw.rfind("}")
    if closing_index < 0:
        raise ValueError("question JSON has no closing object")
    newline = "\r\n" if "\r\n" in raw else "\n"
    indent = "  "
    for line in raw.splitlines():
        stripped = line.lstrip(" \t")
        if stripped.startswith('"'):
            indent = line[: len(line) - len(stripped)]
            break
    before = raw[:closing_index].rstrip(" \t\r\n")
    after = raw[closing_index:]
    fields = [f'{indent}"status": {json.dumps(status, ensure_ascii=False)}']
    if reason:
        fields.append(f'{indent}"status_reason": {json.dumps(reason, ensure_ascii=False)}')
    return before + "," + newline + ("," + newline).join(fields) + newline + after


def remove_curation_fields(raw: str) -> str:
    """Remove the final curation fields while leaving all question content intact."""

    match = CURATION_FIELDS.search(raw)
    if match:
        return raw[: match.start()] + raw[match.end() :]
    if '"status"' in raw or '"status_reason"' in raw:
        raise ValueError("existing curation fields are not in the supported trailing format")
    return raw


def atomic_write(path: Path, content: str) -> None:
    """Replace one question only after its complete updated contents are durable."""

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, path.stat().st_mode)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=REPO_ROOT / "questions")
    parser.add_argument("--tags", type=Path, default=REPO_ROOT / "docs" / "tags.md")
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite existing curation fields using the current suspension policy",
    )
    parser.add_argument(
        "--exam",
        help="promote only records from this exam while validating the full bank",
    )
    args = parser.parse_args()

    report = validate_bank(args.questions, args.tags)
    if not report.format_clean:
        payload = {
            "error": "format_validation_failed",
            "files": [
                {"path": str(result.path), "issues": issue_codes(result.errors)}
                for result in report.errors
            ],
        }
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1

    questions = report.questions
    if args.exam:
        questions = [result for result in questions if result.question.get("exam") == args.exam]

    active = 0
    suspended = 0
    for result in questions:
        with result.path.open(encoding="utf-8", newline="") as handle:
            raw = handle.read()
        base = remove_curation_fields(raw) if args.update else raw
        reasons = curation_reasons(result)
        if reasons:
            updated = append_status(base, "suspended", ";".join(reasons))
            suspended += 1
        else:
            updated = append_status(base, "active", None)
            active += 1
        if updated != raw:
            atomic_write(result.path, updated)
    print(json.dumps({"total": len(questions), "active": active, "suspended": suspended}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
