"""Validation for question-bank curation.

Structural errors block promotion.  Content-sanity findings are warnings so
the promotion pass can retain suspicious questions as suspended records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable


REQUIRED_FIELDS = ("id", "type", "exam", "year", "number", "stem", "answer", "source", "tags")
POSCOMP_YEAR_RANGE = range(2002, 2026)
# These warnings indicate incomplete question text and keep a question out of
# the active bank. Other warnings remain visible to curators but are advisory.
SUSPENDING_WARNING_CODES = frozenset({"short_stem", "stem_ends_mid_sentence"})


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
        if isinstance(value, str) and not value.strip():
            _add(result, "empty_required_field", f"required field is empty: {name}")
        elif isinstance(value, (list, dict)) and not value:
            _add(result, "empty_required_field", f"required field is empty: {name}")

    question_id = question.get("id")
    if isinstance(question_id, str) and question_id.strip() and question_id != path.stem:
        _add(result, "id_filename_mismatch", "id does not match filename")

    year = question.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or year not in POSCOMP_YEAR_RANGE:
        _add(result, "invalid_year", "year must be an integer in the POSCOMP 2002-2025 range")

    number = question.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 100:
        _add(result, "invalid_number", "number must be an integer from 1 through 100")

    question_type = question.get("type")
    if question_type != "mc":
        _add(result, "invalid_type", "this promotion pass supports only type 'mc'")

    stem = content_text(question.get("stem"))
    if stem is None:
        _add(result, "invalid_stem_content", "stem must be a non-empty string or schema-v2 block list")

    options = question.get("options")
    option_texts: list[str] = []
    if question_type == "mc":
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
        if _ends_mid_sentence(stem):
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
