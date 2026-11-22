"""JSON and JSONL source adapter for structured question imports."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .manifest import Source


class JsonAdapter:
    """Read a JSON array, single JSON object, or JSONL file into candidate records."""

    def read(self, source: Source) -> Iterable[dict[str, Any]]:
        try:
            raw_text = source.path.read_text(encoding="utf-8")
        except OSError as exc:
            yield {"_ingest_error": f"json_read_error:{type(exc).__name__}"}
            return

        if source.path.suffix.lower() == ".jsonl":
            records = self._iter_jsonl(raw_text)
        else:
            records = self._iter_json(raw_text)

        for index, item in records:
            if isinstance(item, dict) and "_ingest_error" in item:
                yield item
                continue
            if not isinstance(item, dict):
                yield {"_ingest_error": f"json_record_not_object:{index}"}
                continue
            candidate = dict(item)
            if not candidate.get("exam"):
                candidate["exam"] = source.exam
            if "year" not in candidate or candidate["year"] is None:
                candidate["year"] = source.year
            if "status" not in candidate:
                candidate["status"] = source.options.get("status", "active")
            if "provenance" not in candidate:
                candidate["provenance"] = {
                    "source_id": source.id,
                    "source_path": source.path.name,
                    "index": index,
                }
            yield candidate

    @staticmethod
    def _iter_json(raw_text: str) -> Iterable[tuple[int, Any]]:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            yield (1, {"_ingest_error": f"json_parse_error:{exc.lineno}:{exc.colno}"})
            return
        if isinstance(parsed, list):
            for index, item in enumerate(parsed, start=1):
                yield (index, item)
        elif isinstance(parsed, dict):
            yield (1, parsed)
        else:
            yield (1, {"_ingest_error": "json_root_must_be_array_or_object"})

    @staticmethod
    def _iter_jsonl(raw_text: str) -> Iterable[tuple[int, Any]]:
        for lineno, line in enumerate(raw_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield (lineno, json.loads(stripped))
            except json.JSONDecodeError as exc:
                yield (lineno, {"_ingest_error": f"jsonl_parse_error:{lineno}:{exc.colno}"})
