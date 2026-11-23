"""Adapter from public-sector exam PDFs to generic ingestion candidates."""

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

from .manifest import BOARD_FORMATS, Source, normalize_board_options


def _slug(value: str) -> str:
    """Create a stable ASCII component for candidate IDs."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in folded if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "geral"


class BoardPdfAdapter:
    """Wrap the board PDF parser and classifier for generic ingestion.

    Board-specific metadata lives in the source's ``options`` object. If an
    answer-key PDF is configured, it is parsed and matched to this booklet
    by the board parser. Candidates still pass through the generic pipeline's
    normal validator and persistence path.
    """

    def read(self, source: Source) -> Iterable[dict[str, Any]]:
        options = normalize_board_options(source.options)
        board = str(options.get("board", source.exam)).strip().lower()
        agency = str(options.get("agency", "")).strip()
        role = str(options.get("role", "")).strip()
        booklet = str(options.get("booklet", "")).strip()
        if board not in BOARD_FORMATS:
            raise ValueError(f"unsupported board: {board!r}")
        if not all((agency, role, booklet)):
            raise ValueError("pdf-board source requires board, agency, role, and booklet metadata")

        answer_path_value = options.get("answer_key_path")
        answer_map: dict[int, str] | None = None
        if answer_path_value:
            answer_path = (source.path.parent / str(answer_path_value)).resolve()
            sections = parse_gabarito_pdf(answer_path, board)
            answer_map = match_gabarito_section(sections, board, role, booklet, agency)

        answer_key_kind = options.get("answer_key_kind", "final")
        if answer_key_kind not in ("final", "preliminary"):
            raise ValueError("answer_key_kind must be 'final' or 'preliminary'")
        is_preliminary = answer_key_kind == "preliminary"
        # The question bank's persisted provenance uses the legacy names and values.
        stored_key_kind = "preliminar" if is_preliminary else "definitivo"
        booklet_url = str(options.get("booklet_url", ""))
        booklet_sha256 = str(options.get("booklet_sha256", ""))
        answer_key_url = str(options.get("answer_key_url", ""))
        answer_key_sha256 = str(options.get("answer_key_sha256", ""))
        answer_key_source_kind = str(options.get("answer_key_source_kind", stored_key_kind))

        for extracted in extract_questions_from_pdf(source.path, board):
            tags, matched_rules = classify_question(extracted.stem, extracted.options)
            qid = (
                f"{board}-{source.year}-{_slug(agency)}-{_slug(role)}-"
                f"{_slug(booklet)}-{extracted.number:03d}"
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
            status = "suspended" if is_preliminary else "active"
            provenance: dict[str, Any] = {
                "banca": board,
                "organ": agency,
                "role": role,
                "roles": [role],
                "year": source.year,
                "caderno": booklet,
                "cadernos": [booklet],
                "gabarito_kind": stored_key_kind,
                "round_trip_verified": True,
                "matched_rules": matched_rules,
                "prova_url": booklet_url,
                "prova_sha256": booklet_sha256,
                "gabarito_url": answer_key_url,
                "gabarito_sha256": answer_key_sha256,
                "sources": [
                    {"kind": "prova", "url": booklet_url, "sha256": booklet_sha256},
                    {
                        "kind": answer_key_source_kind,
                        "url": answer_key_url,
                        "sha256": answer_key_sha256,
                    },
                ],
            }
            candidate: dict[str, Any] = {
                "id": qid,
                "type": "mc",
                "exam": board,
                "year": source.year,
                "number": extracted.number,
                "stem": extracted.stem,
                "options": extracted.options,
                "answer": answer,
                "source": (
                    f"{board.upper()} — {agency.upper()} {source.year} "
                    f"({role}, {booklet}, Q{extracted.number})"
                ),
                "tags": tags,
                "status": status,
                "provenance": provenance,
            }
            if status == "suspended":
                candidate["status_reason"] = "preliminary_answer_key"
            yield candidate
