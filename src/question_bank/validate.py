"""Validation for question-bank curation.

Structural errors block promotion.  Content-sanity findings are warnings so
the promotion pass can retain suspicious questions as suspended records.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("id", "type", "exam", "year", "number", "stem", "source", "tags")
POSCOMP_YEAR_RANGE = range(2002, 2026)
ENADE_YEARS = frozenset({2005, 2008, 2011, 2014, 2017, 2021})
# These warnings indicate incomplete question text and keep a question out of
# the active bank. Other warnings remain visible to curators but are advisory.
SUSPENDING_WARNING_CODES = frozenset({"short_stem", "stem_ends_mid_sentence"})
SOURCE_COMPLETE_ENADE_IDS = frozenset(
    {
        "enade-2005-43", "enade-2005-44", "enade-2005-47", "enade-2005-49",
        "enade-2005-50", "enade-2005-64", "enade-2005-66", "enade-2005-68",
        "enade-2008-11", "enade-2008-31", "enade-2008-33", "enade-2008-34",
        "enade-2008-36", "enade-2014-9", "enade-2014-10", "enade-2014-11",
        "enade-2014-14", "enade-2014-15", "enade-2014-17", "enade-2014-18",
        "enade-2014-20", "enade-2014-21", "enade-2014-22", "enade-2014-23",
        "enade-2014-24", "enade-2014-25", "enade-2014-26", "enade-2014-27",
        "enade-2014-29", "enade-2014-30", "enade-2014-31", "enade-2014-32",
        "enade-2014-33", "enade-2014-d4", "enade-2014-d5",
    }
)


@dataclass(frozen=True)
class ValidationIssue:
    """One curation finding for a question file."""

    code: str
    message: str
    severity: str


@dataclass
class QuestionValidation:
    """Validation findings for one parsed question."""

    path: Path
    question: dict[str, Any] | None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def format_clean(self) -> bool:
        return not self.errors


@dataclass
class BankValidation:
    """Validation findings for a complete question-bank directory."""

    questions: list[QuestionValidation]

    @property
    def errors(self) -> list[QuestionValidation]:
        return [question for question in self.questions if question.errors]

    @property
    def warnings(self) -> list[QuestionValidation]:
        return [question for question in self.questions if question.warnings]

    @property
    def format_clean(self) -> bool:
        return not self.errors


def load_registered_tags(tags_path: Path) -> set[str]:
    """Read tag slugs from the Registry section of ``docs/tags.md`` only."""

    registered: set[str] = set()
    in_registry = False
    for raw_line in tags_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "## Registry (seeded from POSCOMP's own hierarchy)" or line.startswith("## Registry"):
            in_registry = True
            continue
        if in_registry and line.startswith("## "):
            break
        if not in_registry or not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 3 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", parts[0]):
            registered.add(parts[0])
    return registered


def content_text(value: Any) -> str | None:
    """Return text represented by a schema-v2 content value, or ``None`` if invalid."""

    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, list) or not value:
        return None

    text_parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            return None
        block_type = block.get("type")
        if block_type == "text":
            content = block.get("content")
            if not isinstance(content, str) or not content.strip():
                return None
            text_parts.append(content.strip())
        elif block_type == "image":
            src = block.get("src")
            alt = block.get("alt")
            if not isinstance(src, str) or not src.strip() or not isinstance(alt, str) or not alt.strip():
                return None
            text_parts.append(alt.strip())
        else:
            return None
    return "\n".join(text_parts).strip()


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


def _ends_mid_sentence(stem: str) -> bool:
    stripped = stem.strip()
    stripped = re.sub(r'''[\]\)\}"'”’]+$''', "", stripped)
    return bool(stripped) and stripped[-1] not in ".?!…:;"


def _add(result: QuestionValidation, code: str, message: str, severity: str = "error") -> None:
    result.issues.append(ValidationIssue(code=code, message=message, severity=severity))


def validate_question(
    question: dict[str, Any],
    path: Path,
    registered_tags: set[str],
) -> QuestionValidation:
    """Validate one question against curation rules and schema-v2 content forms."""

    result = QuestionValidation(path=path, question=question)
    for name in REQUIRED_FIELDS:
        if name not in question:
            _add(result, "missing_required_field", f"missing required field: {name}")
            continue
        value = question[name]
        if isinstance(value, str) and not value.strip() or isinstance(value, (list, dict)) and not value:
            _add(result, "empty_required_field", f"required field is empty: {name}")

    question_id = question.get("id")
    if isinstance(question_id, str) and question_id.strip() and question_id != path.stem:
        _add(result, "id_filename_mismatch", "id does not match filename")

    exam = question.get("exam")
    if exam not in {"poscomp", "enade"}:
        _add(result, "invalid_exam", "exam must be 'poscomp' or 'enade'")

    year = question.get("year")
    valid_year = (
        isinstance(year, int)
        and not isinstance(year, bool)
        and (year in ENADE_YEARS if exam == "enade" else year in POSCOMP_YEAR_RANGE)
    )
    if not valid_year:
        allowed = "the supported ENADE editions" if exam == "enade" else "the POSCOMP 2002-2025 range"
        _add(result, "invalid_year", f"year must be an integer in {allowed}")

    number = question.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 100:
        _add(result, "invalid_number", "number must be an integer from 1 through 100")

    question_type = question.get("type")
    if question_type not in {"mc", "discursive"}:
        _add(result, "invalid_type", "type must be 'mc' or 'discursive'")

    stem = content_text(question.get("stem"))
    if stem is None:
        _add(result, "invalid_stem_content", "stem must be a non-empty string or schema-v2 block list")

    options = question.get("options")
    option_texts: list[str] = []
    if question_type == "mc":
        if "answer" not in question:
            _add(result, "missing_required_field", "missing required field: answer")
        if not isinstance(options, list) or len(options) != 5:
            _add(result, "invalid_option_count", "mc questions must have exactly 5 options")
        else:
            for index, option in enumerate(options):
                option_text = content_text(option)
                if option_text is None:
                    _add(result, "empty_option_text", f"option {index + 1} is empty or malformed")
                else:
                    option_texts.append(option_text)

        answer = question.get("answer")
        if not isinstance(answer, str) or not re.fullmatch(r"[A-E]", answer):
            _add(result, "invalid_answer", "mc answer must be one uppercase letter from A through E")
        elif isinstance(options, list) and len(options) == 5 and ord(answer) - ord("A") >= len(options):
            _add(result, "answer_out_of_range", "answer is outside the available option range")
        if "rubric" in question:
            _add(result, "forbidden_rubric", "mc questions must not include rubric")
    elif question_type == "discursive":
        if "options" in question:
            _add(result, "forbidden_options", "discursive questions must not include options")
        if "answer" in question:
            _add(result, "forbidden_answer", "discursive questions must not include answer")
        if content_text(question.get("rubric")) is None:
            _add(result, "invalid_rubric_content", "discursive rubric must be non-empty schema-v2 content")

    if exam == "enade":
        if question.get("component") not in {"general-education", "specific"}:
            _add(result, "invalid_component", "ENADE component must be 'general-education' or 'specific'")
        if question.get("course") != "computer-science":
            _add(result, "invalid_course", "ENADE course must be 'computer-science'")

    if "context" in question:
        context_id = question["context"]
        if not isinstance(context_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", context_id):
            _add(result, "invalid_context", "context must be a non-empty context id")
        else:
            context_path = path.parent.parent / "contexts" / f"{context_id}.json"
            if not context_path.is_file():
                _add(result, "missing_context", f"context file does not exist: contexts/{context_id}.json")

    tags = question.get("tags")
    if not isinstance(tags, list) or not tags:
        _add(result, "invalid_tags", "tags must be a non-empty list")
    else:
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip() or tag not in registered_tags:
                _add(result, "unregistered_tag", f"tag is not registered: {tag!r}")

    if stem:
        if len(stem) < 40:
            _add(result, "short_stem", "stem has fewer than 40 characters", "warning")
        reviewed_complete = is_source_reviewed_complete_enade(question, path)
        if _ends_mid_sentence(stem) and not reviewed_complete:
            _add(result, "stem_ends_mid_sentence", "stem appears to end mid-sentence", "warning")

    for left in range(len(option_texts)):
        for right in range(left + 1, len(option_texts)):
            similarity = SequenceMatcher(None, _normalise(option_texts[left]), _normalise(option_texts[right])).ratio()
            if similarity > 0.90:
                _add(
                    result,
                    "near_duplicate_options",
                    f"options {left + 1} and {right + 1} have normalized similarity {similarity:.2f}",
                    "warning",
                )

    return result


def is_source_reviewed_complete_enade(question: dict[str, Any], path: Path) -> bool:
    """Limit the source-review exception to the exact audited ENADE record."""

    question_id = question.get("id")
    if (
        question.get("exam") != "enade"
        or not isinstance(question_id, str)
        or question_id not in SOURCE_COMPLETE_ENADE_IDS
        or question_id != path.stem
    ):
        return False

    match = re.fullmatch(r"enade-(2005|2008|2011|2014|2017|2021)-(d[1-5]|\d{1,2})", question_id)
    if not match:
        return False
    year = int(match.group(1))
    suffix = match.group(2)
    number = int(suffix.removeprefix("d"))
    if question.get("year") != year or question.get("number") != number:
        return False

    if suffix.startswith("d"):
        return question.get("type") == "discursive" and content_text(question.get("rubric")) is not None

    options = question.get("options")
    return (
        question.get("type") == "mc"
        and isinstance(options, list)
        and len(options) == 5
        and question.get("answer") in set("ABCDE")
    )


def validate_bank(questions_dir: Path, tags_path: Path) -> BankValidation:
    """Validate all JSON questions, including duplicate identifiers across files."""

    registered_tags = load_registered_tags(tags_path)
    results: list[QuestionValidation] = []
    ids: dict[str, list[QuestionValidation]] = {}
    for path in sorted(questions_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result = QuestionValidation(path=path, question=None)
            _add(result, "invalid_json", f"could not parse JSON: {exc}")
            results.append(result)
            continue
        if not isinstance(data, dict):
            result = QuestionValidation(path=path, question=None)
            _add(result, "invalid_question_object", "question file must contain a JSON object")
            results.append(result)
            continue
        result = validate_question(data, path, registered_tags)
        results.append(result)
        question_id = data.get("id")
        if isinstance(question_id, str) and question_id.strip():
            ids.setdefault(question_id, []).append(result)

    for question_id, matching_results in ids.items():
        if len(matching_results) > 1:
            for result in matching_results:
                _add(result, "duplicate_id", f"duplicate id: {question_id}")
    return BankValidation(questions=results)


def issue_codes(issues: Iterable[ValidationIssue]) -> list[str]:
    """Return stable, de-duplicated machine-readable issue codes."""

    return sorted({issue.code for issue in issues})


def suspending_warning_codes(issues: Iterable[ValidationIssue]) -> list[str]:
    """Return warning codes that require a question to be suspended."""

    return sorted(
        {
            issue.code
            for issue in issues
            if issue.severity == "warning" and issue.code in SUSPENDING_WARNING_CODES
        }
    )
