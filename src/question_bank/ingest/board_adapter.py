"""Adapter from concurso board PDFs to generic ingestion candidates."""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from question_bank.concurso import (
    ANNULLED,
    classify_question,
    extract_questions_from_pdf,
    match_gabarito_section,
    parse_gabarito_pdf,
)

from .manifest import Source


def _slug(value: str) -> str:
    """Create a stable ASCII component for candidate IDs."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in folded if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "geral"


class BoardPdfAdapter:
    """Wrap the established concurso parser and classifier for generic ingestion.

    Board-specific metadata lives in the source's ``options`` object. If an
    answer-key PDF is configured, it is parsed and matched to this booklet
    using concurso.py's existing functions. Candidates still pass through the
    generic pipeline's normal validator and persistence path.
    """

    def read(self, source: Source) -> Iterable[dict[str, Any]]:
        options = source.options
        banca = str(options.get("banca", source.exam)).strip().lower()
        organ = str(options.get("organ", "")).strip()
        role = str(options.get("role", "")).strip()
        caderno = str(options.get("caderno", "")).strip()
        if banca not in {"fgv", "iades", "cesgranrio", "fcpc"}:
            raise ValueError(f"unsupported banca: {banca!r}")
        if not all((organ, role, caderno)):
            raise ValueError("pdf-board source requires banca, organ, role, and caderno metadata")

        answer_path_value = options.get("gabarito_path", options.get("answer_key_path"))
        answer_map: dict[int, str] | None = None
        if answer_path_value:
            answer_path = (source.path.parent / str(answer_path_value)).resolve()
            sections = parse_gabarito_pdf(answer_path, banca)
            answer_map = match_gabarito_section(sections, banca, role, caderno, organ)

        answer_kind = str(options.get("gabarito_kind", "definitivo")).strip().lower()
        if answer_kind not in {"definitivo", "preliminar"}:
            raise ValueError("gabarito_kind must be 'definitivo' or 'preliminar'")
        prova_url = str(options.get("prova_url", ""))
        prova_sha256 = str(options.get("prova_sha256", ""))
        gabarito_url = str(options.get("gabarito_url", ""))
        gabarito_sha256 = str(options.get("gabarito_sha256", ""))
        gabarito_source_kind = str(options.get("gabarito_source_kind", answer_kind))

        for extracted in extract_questions_from_pdf(source.path, banca):
            tags, matched_rules = classify_question(extracted.stem, extracted.options)
            qid = (
                f"{banca}-{source.year}-{_slug(organ)}-{_slug(role)}-"
                f"{_slug(caderno)}-{extracted.number:03d}"
            )
            lookup_number = (
                extracted.gabarito_number
                if extracted.gabarito_number is not None
                else extracted.number
            )
            error: str | None = None
            if extracted.quarantine_reason:
                error = extracted.quarantine_reason
            elif not extracted.round_trip_ok:
                error = "round_trip_mismatch"
            elif not tags:
                error = "out_of_scope_topic"
            elif answer_map is None or lookup_number not in answer_map:
                error = "missing_answer_key"
            else:
                answer = answer_map[lookup_number]
                if answer == ANNULLED:
                    error = "annulled_in_official_key"
                elif answer not in ("ABCD" if len(extracted.options) == 4 else "ABCDE"):
                    error = f"answer_out_of_range_{answer}"
            if error:
                yield {"_ingest_error": error, "id": qid}
                continue

            answer = answer_map[lookup_number]  # type: ignore[index]
            status = "suspended" if answer_kind == "preliminar" else "active"
            provenance: dict[str, Any] = {
                "banca": banca,
                "organ": organ,
                "role": role,
                "roles": [role],
                "year": source.year,
                "caderno": caderno,
                "cadernos": [caderno],
                "gabarito_kind": answer_kind,
                "round_trip_verified": True,
                "matched_rules": matched_rules,
                "prova_url": prova_url,
                "prova_sha256": prova_sha256,
                "gabarito_url": gabarito_url,
                "gabarito_sha256": gabarito_sha256,
                "sources": [
                    {"kind": "prova", "url": prova_url, "sha256": prova_sha256},
                    {
                        "kind": gabarito_source_kind,
                        "url": gabarito_url,
                        "sha256": gabarito_sha256,
                    },
                ],
            }
            candidate: dict[str, Any] = {
                "id": qid,
                "type": "mc",
                "exam": banca,
                "year": source.year,
                "number": extracted.number,
                "stem": extracted.stem,
                "options": extracted.options,
                "answer": answer,
                "source": (
                    f"{banca.upper()} — {organ.upper()} {source.year} "
                    f"({role}, {caderno}, Q{extracted.number})"
                ),
                "tags": tags,
                "status": status,
                "provenance": provenance,
            }
            if status == "suspended":
                candidate["status_reason"] = "preliminary_answer_key"
            yield candidate
