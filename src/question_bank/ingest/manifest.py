"""Loading and validation for generic ingestion manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BOARD_FORMATS = frozenset({"fgv", "iades", "cesgranrio", "fcpc"})
_BOARD_OPTION_ALIASES = {
    "banca": "board",
    "organ": "agency",
    "caderno": "booklet",
    "prova_url": "booklet_url",
    "prova_sha256": "booklet_sha256",
    "gabarito_path": "answer_key_path",
    "gabarito_kind": "answer_key_kind",
    "gabarito_url": "answer_key_url",
    "gabarito_sha256": "answer_key_sha256",
    "gabarito_source_kind": "answer_key_source_kind",
}


def normalize_board_options(options: dict[str, Any]) -> dict[str, Any]:
    """Accept legacy board options, giving the English keys precedence."""
    normalized = options.copy()
    for legacy, current in _BOARD_OPTION_ALIASES.items():
        if legacy in normalized:
            normalized.setdefault(current, normalized.pop(legacy))
    kind = normalized.get("answer_key_kind")
    if isinstance(kind, str):
        kind = kind.strip().lower()
        normalized["answer_key_kind"] = {"definitivo": "final", "preliminar": "preliminary"}.get(kind, kind)
    return normalized


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
        if kind not in {"csv", "json", "pdf-board", "pdf-llm"}:
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
            options = normalize_board_options(options)
            missing = [
                field
                for field in ("board", "agency", "role", "booklet")
                if not isinstance(options.get(field), str) or not options[field].strip()
            ]
            if missing:
                raise ValueError(
                    f"source {source_id} requires board metadata: {', '.join(missing)}"
                )
            if options["board"].strip().lower() not in BOARD_FORMATS:
                raise ValueError(f"source {source_id} has unsupported board: {options['board']!r}")
        resolved_path = (manifest_path.parent / source_path).resolve()
        sources.append(Source(source_id, kind, resolved_path, exam.strip().lower(), year, options))
    return sources
