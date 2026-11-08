"""CSV source adapter with explicit, configurable column mappings."""

from __future__ import annotations

import ast
import csv
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from .manifest import Source


def _slugify(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


class CsvAdapter:
    """Convert a CSV's rows to candidate records without writing bank files."""

    def read(self, source: Source) -> Iterable[dict[str, Any]]:
        options = source.options
        id_column = options.get("id_column", "id")
        stem_column = options.get("stem_column", "stem")
        answer_column = options.get("answer_column", "answer")
        number_column = options.get("number_column", "number")
        options_columns = options.get("options_columns")
        options_column = options.get("options_column", "options")
        tags_columns = options.get("tags_columns", ["knowledge_area", "area", "subarea"])
        if options_columns is not None and (
            not isinstance(options_columns, list)
            or not all(isinstance(column, str) for column in options_columns)
        ):
            raise ValueError("options_columns must be a list of column names")
        if not isinstance(tags_columns, list) or not all(isinstance(c, str) for c in tags_columns):
            raise ValueError("tags_columns must be a list of column names")

        with source.path.open(newline="", encoding="utf-8") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                raw_id = (row.get(id_column) or "").strip()
                raw_stem = (row.get(stem_column) or "").strip()
                try:
                    number = int(row[number_column])
                    row_options = self._options(row, options_columns, options_column)
                except (KeyError, TypeError, ValueError, SyntaxError) as exc:
                    yield {"_ingest_error": f"csv_row_invalid:{row_number}:{type(exc).__name__}"}
                    continue
                prefix = str(options.get("id_prefix", f"{source.exam}-"))
                qid = raw_id if options.get("id_is_canonical", False) else f"{prefix}{raw_id}"
                if not raw_id:
                    yield {"_ingest_error": f"csv_row_missing_id:{row_number}"}
                    continue
                tags = [
                    slug
                    for column in tags_columns
                    if (value := (row.get(column) or "").strip())
                    if (slug := _slugify(value))
                ]
                answer = (row.get(answer_column) or "").strip().upper()
                source_text = str(
                    options.get("source_template", "{EXAM} {year}, question {number}")
                ).format(exam=source.exam, EXAM=source.exam.upper(), year=source.year, number=number)
                candidate: dict[str, Any] = {
                    "id": qid,
                    "type": options.get("type", "mc"),
                    "exam": source.exam,
                    "year": source.year,
                    "number": number,
                    "stem": raw_stem,
                    "options": row_options,
                    "answer": answer,
                    "source": source_text,
                    "tags": tags,
                    "status": options.get("status", "active"),
                    "provenance": {"source_id": source.id, "source_path": source.path.name, "row": row_number},
                }
                if not raw_stem:
                    candidate["_ingest_error"] = f"csv_row_missing_stem:{row_number}"
                yield candidate

    @staticmethod
    def _options(
        row: dict[str, str], options_columns: list[str] | None, options_column: str
    ) -> list[str]:
        if options_columns is not None:
            return [(row.get(column) or "").strip() for column in options_columns]
        raw = (row.get(options_column) or "").strip()
        if not raw:
            return []
        parsed = ast.literal_eval(raw)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("options must be a list of strings")
        cleaned = []
        for option in parsed:
            option = option.strip()
            if len(option) > 3 and option[0].lower() in "abcde" and option[1:3] == ") ":
                option = option[3:]
            cleaned.append(option)
        return cleaned
