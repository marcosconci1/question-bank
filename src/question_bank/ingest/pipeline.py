"""Validation and persistence for adapter-produced candidates."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from question_bank.paths import resolve_bank_root
from question_bank.validate import load_registered_tags, validate_question

from .csv_adapter import CsvAdapter
from .board_adapter import BoardPdfAdapter
from .manifest import Source, load_manifest


@dataclass(frozen=True)
class IngestSummary:
    ingested: int = 0
    skipped: int = 0
    quarantined: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"ingested": self.ingested, "skipped": self.skipped, "quarantined": self.quarantined}


def run_ingest(
    manifest_path: Path | None = None,
    source_id: str | None = None,
    *,
    dry_run: bool = False,
    bank_root: Path | None = None,
    tags_path: Path | None = None,
    adapters: dict[str, Any] | None = None,
) -> IngestSummary:
    """Run selected pending sources, validating before every question write."""

    root = Path(bank_root).resolve() if bank_root is not None else resolve_bank_root()
    manifest_file = Path(manifest_path).expanduser().resolve() if manifest_path else root / "reports" / "sources.json"
    questions_dir = root / "questions"
    quarantine_path = root / "reports" / "ingest-quarantine.jsonl"
    registry_path = Path(tags_path) if tags_path else Path(__file__).resolve().parents[3] / "docs" / "tags.md"
    registered_tags = load_registered_tags(registry_path)
    sources = load_manifest(manifest_file)
    if source_id is not None:
        selected = [source for source in sources if source.id == source_id]
        if not selected:
            raise ValueError(f"unknown source id: {source_id}")
        sources = selected

    adapter_map = {"csv": CsvAdapter(), "pdf-board": BoardPdfAdapter(), **(adapters or {})}
    ingested = skipped = quarantined = 0
    seen: set[str] = set()
    rejected: list[dict[str, Any]] = []
    for source in sources:
        adapter = adapter_map.get(source.kind)
        if adapter is None:
            raise ValueError(f"no adapter registered for source kind: {source.kind}")
        for candidate in adapter.read(source):
            if "_ingest_error" in candidate:
                rejected.append({"source_id": source.id, "reason": candidate["_ingest_error"], "candidate": candidate})
                quarantined += 1
                continue
            qid = candidate.get("id")
            if not isinstance(qid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", qid):
                rejected.append({"source_id": source.id, "reason": "invalid_id", "candidate": candidate})
                quarantined += 1
                continue
            target = questions_dir / f"{qid}.json"
            if qid in seen or target.exists():
                skipped += 1
                continue
            seen.add(qid)
            result = validate_question(candidate, target, registered_tags)
            if result.errors:
                rejected.append(
                    {
                        "source_id": source.id,
                        "candidate_id": qid,
                        "reason": "validator_error",
                        "codes": sorted({issue.code for issue in result.errors}),
                        "messages": [issue.message for issue in result.errors],
                    }
                )
                quarantined += 1
                continue
            if not dry_run:
                questions_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ingested += 1

    if rejected and not dry_run:
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("a", encoding="utf-8") as handle:
            for record in rejected:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return IngestSummary(ingested, skipped, quarantined)
