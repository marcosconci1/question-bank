"""Loading and validation for generic ingestion manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Source:
    """One source declaration; ``options`` holds adapter-specific settings."""

    id: str
    kind: str
    path: Path
    exam: str
    year: int
    options: dict[str, Any]


def load_manifest(path: Path) -> list[Source]:
    """Load a JSON list manifest, resolving source paths beside the manifest.

    CSV defaults: ``id_column=id``, ``stem_column=stem``,
    ``options_column=options`` (a Python or JSON list),
    ``answer_column=answer``, ``number_column=number``,
    ``type=mc``, ``status=active``, and ``id_prefix={exam}-``. Set
    ``options_columns`` to an ordered list of separate option columns instead.
    ``tags_columns`` may list columns that are slugged and combined. The
    default source text is ``{EXAM} {year}, question {number}``; all column
    names and templates can be overridden in ``options``.
    """

    manifest_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load manifest: {exc}") from exc
    if not isinstance(raw, list):
        raise ValueError("manifest must be a JSON array")

    seen: set[str] = set()
    sources: list[Source] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest entry {index} must be an object")
        source_id = entry.get("id")
        kind = entry.get("kind")
        source_path = entry.get("path")
        exam = entry.get("exam")
        year = entry.get("year")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"manifest entry {index} requires a non-empty id")
        source_id = source_id.strip()
        if source_id in seen:
            raise ValueError(f"duplicate source id: {source_id}")
        seen.add(source_id)
        if kind not in {"csv", "pdf-board", "pdf-llm"}:
            raise ValueError(f"unknown source kind for {source_id}: {kind!r}")
        if not isinstance(source_path, str) or not source_path.strip():
            raise ValueError(f"source {source_id} requires a non-empty path")
        if not isinstance(exam, str) or not exam.strip():
            raise ValueError(f"source {source_id} requires a non-empty exam")
        if not isinstance(year, int) or isinstance(year, bool):
            raise ValueError(f"source {source_id} year must be an integer")
        options = entry.get("options", {})
        if not isinstance(options, dict):
            raise ValueError(f"source {source_id} options must be an object")
        if kind == "pdf-board":
            missing = [
                field
                for field in ("banca", "organ", "role", "caderno")
                if not isinstance(options.get(field), str) or not options[field].strip()
            ]
            if missing:
                raise ValueError(
                    f"source {source_id} requires board metadata: {', '.join(missing)}"
                )
            if options["banca"].strip().lower() not in {"fgv", "iades", "cesgranrio", "fcpc"}:
                raise ValueError(f"source {source_id} has unsupported banca: {options['banca']!r}")
        resolved_path = (manifest_path.parent / source_path).resolve()
        sources.append(Source(source_id, kind, resolved_path, exam.strip().lower(), year, options))
    return sources
