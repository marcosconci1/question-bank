#!/usr/bin/env python3
"""Deterministic, idempotent CLI for importing Brazilian public-sector IT exam questions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from question_bank.concurso import (  # noqa: E402
    ANNULLED,
    classify_question,
    deduplicate_records,
    extract_questions_from_pdf,
    fold_accents,
    match_gabarito_section,
    parse_gabarito_pdf,
)
from question_bank.validate import load_registered_tags, validate_question  # noqa: E402


def _slugify(text: str, max_tokens: int = 4) -> str:
    """Build a short kebab-case slug from role/organ/caderno text."""
    folded = fold_accents(text)
    # Remove parenthetical tipo/gabarito suffixes
    folded = re.sub(r"\((?:tipo|gabarito)\s*[^)]*\)", " ", folded)
    stopwords = {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "e",
        "para",
        "com",
        "area",
        "especialidade",
        "apoio",
        "especializado",
        "tecnologia",
        "informacao",
        "analista",
        "judiciario",
        "tecnico",
        "cientifico",
        "bancario",
        "planejamento",
        "pesquisa",
        "iii",
    }
    raw_tokens = re.findall(r"[a-z0-9]+", folded)
    filtered = [t for t in raw_tokens if t not in stopwords]
    if not filtered:
        filtered = raw_tokens[:max_tokens]
    else:
        # Prefix with level (analista/tecnico/auditor/agente) if present in raw_tokens
        prefix = [t for t in raw_tokens[:2] if t in ("analista", "tecnico", "auditor", "agente")]
        rest = [t for t in filtered if t not in prefix]
        filtered = (prefix + rest)[:max_tokens]
    return "-".join(filtered) or "geral"


def build_candidate_id(
    banca: str,
    year: int,
    organ: str,
    role: str,
    caderno: str,
    number: int,
) -> str:
    """Build a deterministic kebab-case ID for a candidate question."""
    organ_slug = re.sub(r"[^a-z0-9]+", "-", fold_accents(organ)).strip("-")
    role_slug = _slugify(role, max_tokens=3)
    cad_slug = re.sub(r"[^a-z0-9]+", "-", fold_accents(caderno)).strip("-")
    return f"{banca}-{year}-{organ_slug}-{role_slug}-{cad_slug}-{number:03d}"


def run_import(
    manifest_path: Path,
    questions_dir: Path,
    quarantine_path: Path,
    tags_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Process all manifest entries and return summary statistics."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registered_tags = load_registered_tags(tags_path)

    by_group: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for entry in manifest:
        key = (str(entry["banca"]).lower(), str(entry["organ"]).lower(), int(entry["year"]))
        by_group.setdefault(key, []).append(entry)

    raw_imported: list[dict[str, Any]] = []
    quarantine_records: list[dict[str, Any]] = []

    skipped_out_of_scope = 0
    skipped_by_banca: Counter[str] = Counter()
    provas_by_banca: Counter[str] = Counter()
    quarantine_reasons: Counter[str] = Counter()
    quarantine_by_banca: Counter[str] = Counter()

    for (banca, organ, year), entries in sorted(by_group.items()):
        provas = [e for e in entries if e["kind"] == "prova"]
        definitivos = [e for e in entries if e["kind"] == "definitivo"]
        preliminares = [e for e in entries if e["kind"] == "gabarito"]

        # Parse all gabarito sections for this group once
        def_sections: dict[str, tuple[dict[int, str], dict[str, Any]]] = {}
        for g in definitivos:
            g_path = REPO_ROOT / g["local_path"]
            parsed = parse_gabarito_pdf(g_path, banca)
            for sec_name, ans_map in parsed.items():
                if sec_name in def_sections:
                    merged = dict(def_sections[sec_name][0])
                    merged.update(ans_map)
                    def_sections[sec_name] = (merged, g)
                else:
                    def_sections[sec_name] = (ans_map, g)

        prel_sections: dict[str, tuple[dict[int, str], dict[str, Any]]] = {}
        for g in preliminares:
            g_path = REPO_ROOT / g["local_path"]
            parsed = parse_gabarito_pdf(g_path, banca)
            for sec_name, ans_map in parsed.items():
                if sec_name in prel_sections:
                    merged = dict(prel_sections[sec_name][0])
                    merged.update(ans_map)
                    prel_sections[sec_name] = (merged, g)
                else:
                    prel_sections[sec_name] = (ans_map, g)

        def_only_maps = {k: v[0] for k, v in def_sections.items()}
        prel_only_maps = {k: v[0] for k, v in prel_sections.items()}

        for prova in sorted(provas, key=lambda p: (p["role"], p["caderno"], p["local_path"])):
            provas_by_banca[banca] += 1
            p_path = REPO_ROOT / prova["local_path"]
            role = str(prova["role"])
            caderno = str(prova["caderno"])

            # Match definitive answer key first, fallback to preliminary
            ans_map = match_gabarito_section(def_only_maps, banca, role, caderno, organ)
            gabarito_kind = "definitivo"
            gab_entry: dict[str, Any] | None = definitivos[0] if definitivos else None
            if ans_map is not None:
                # Find which definitive entry provided ans_map
                for _sec_k, (m_dict, g_ent) in def_sections.items():
                    if m_dict == ans_map:
                        gab_entry = g_ent
                        break
            else:
                ans_map = match_gabarito_section(prel_only_maps, banca, role, caderno, organ)
                if ans_map is not None:
                    gabarito_kind = "preliminar"
                    gab_entry = preliminares[0] if preliminares else None
                    for _sec_k, (m_dict, g_ent) in prel_sections.items():
                        if m_dict == ans_map:
                            gab_entry = g_ent
                            break

            candidates = extract_questions_from_pdf(p_path, banca)
            for cand in candidates:
                tags, matched_rules = classify_question(cand.stem, cand.options)
                if not tags:
                    skipped_out_of_scope += 1
                    skipped_by_banca[banca] += 1
                    continue

                cand_id = build_candidate_id(banca, year, organ, role, caderno, cand.number)

                # Gate (a) and Gate (d): clean parse and round-trip text equality
                if cand.quarantine_reason is not None or not cand.round_trip_ok:
                    reason = cand.quarantine_reason or "round_trip_mismatch"
                    quarantine_reasons[reason] += 1
                    quarantine_by_banca[banca] += 1
                    quarantine_records.append(
                        {
                            "candidate_id": cand_id,
                            "banca": banca,
                            "organ": organ,
                            "role": role,
                            "year": year,
                            "caderno": caderno,
                            "number": cand.number,
                            "reason": reason,
                            "pdf": prova["local_path"],
                            "page": cand.page,
                            "tags": tags,
                            "matched_rules": matched_rules,
                        }
                    )
                    continue

                # Gate (b): answer key resolution and annulment check
                lookup_num = cand.gabarito_number if cand.gabarito_number is not None else cand.number
                if ans_map is None or lookup_num not in ans_map or gab_entry is None:
                    reason = "missing_answer_key"
                    quarantine_reasons[reason] += 1
                    quarantine_by_banca[banca] += 1
                    quarantine_records.append(
                        {
                            "candidate_id": cand_id,
                            "banca": banca,
                            "organ": organ,
                            "role": role,
                            "year": year,
                            "caderno": caderno,
                            "number": cand.number,
                            "reason": reason,
                            "pdf": prova["local_path"],
                            "page": cand.page,
                            "tags": tags,
                            "matched_rules": matched_rules,
                        }
                    )
                    continue

                answer = ans_map[lookup_num]
                if answer == ANNULLED:
                    reason = "annulled_in_official_key"
                    quarantine_reasons[reason] += 1
                    quarantine_by_banca[banca] += 1
                    quarantine_records.append(
                        {
                            "candidate_id": cand_id,
                            "banca": banca,
                            "organ": organ,
                            "role": role,
                            "year": year,
                            "caderno": caderno,
                            "number": cand.number,
                            "reason": reason,
                            "pdf": prova["local_path"],
                            "page": cand.page,
                            "tags": tags,
                            "matched_rules": matched_rules,
                        }
                    )
                    continue

                valid_letters = "ABCD"[: len(cand.options)] if len(cand.options) == 4 else "ABCDE"
                if answer not in valid_letters:
                    reason = f"answer_out_of_range_{answer}"
                    quarantine_reasons[reason] += 1
                    quarantine_by_banca[banca] += 1
                    quarantine_records.append(
                        {
                            "candidate_id": cand_id,
                            "banca": banca,
                            "organ": organ,
                            "role": role,
                            "year": year,
                            "caderno": caderno,
                            "number": cand.number,
                            "reason": reason,
                            "pdf": prova["local_path"],
                            "page": cand.page,
                            "tags": tags,
                            "matched_rules": matched_rules,
                        }
                    )
                    continue

                status = "active" if gabarito_kind == "definitivo" else "suspended"
                p_url = str(prova["url"]).replace(" ", "%20")
                g_url = str(gab_entry["url"]).replace(" ", "%20")
                sources_list = [
                    {
                        "kind": "prova",
                        "url": p_url,
                        "sha256": prova["sha256"],
                    },
                    {
                        "kind": gab_entry["kind"],
                        "url": g_url,
                        "sha256": gab_entry["sha256"],
                    },
                ]

                record: dict[str, Any] = {
                    "id": cand_id,
                    "type": "mc",
                    "exam": banca,
                    "year": year,
                    "number": cand.number,
                    "stem": cand.stem,
                    "options": cand.options,
                    "answer": answer,
                    "source": f"{banca.upper()} — {organ.upper()} {year} ({role}, {caderno}, Q{cand.number})",
                    "tags": tags,
                    "status": status,
                    "provenance": {
                        "banca": banca,
                        "organ": organ,
                        "role": role,
                        "roles": [role],
                        "year": year,
                        "caderno": caderno,
                        "cadernos": [caderno],
                        "gabarito_kind": gabarito_kind,
                        "round_trip_verified": True,
                        "matched_rules": matched_rules,
                        "prova_url": p_url,
                        "prova_sha256": prova["sha256"],
                        "gabarito_url": g_url,
                        "gabarito_sha256": gab_entry["sha256"],
                        "sources": sources_list,
                    },
                }
                if status == "suspended":
                    record["status_reason"] = "preliminary_answer_key"

                # Check validator warnings (e.g. near_duplicate_options or duplicate_options)
                val_res = validate_question(record, questions_dir / f"{cand_id}.json", registered_tags)
                if val_res.errors:
                    reason = f"validator_error_{val_res.errors[0].code}"
                    quarantine_reasons[reason] += 1
                    quarantine_by_banca[banca] += 1
                    quarantine_records.append(
                        {
                            "candidate_id": cand_id,
                            "banca": banca,
                            "organ": organ,
                            "role": role,
                            "year": year,
                            "caderno": caderno,
                            "number": cand.number,
                            "reason": reason,
                            "pdf": prova["local_path"],
                            "page": cand.page,
                            "tags": tags,
                            "matched_rules": matched_rules,
                        }
                    )
                    continue

                raw_imported.append(record)

    # Deduplicate identical questions across cadernos/roles of the same (banca, organ, year)
    deduped_records = deduplicate_records(raw_imported)

    # Sort quarantine records deterministically
    quarantine_records.sort(key=lambda r: (str(r["candidate_id"]), str(r["pdf"]), int(r["page"])))

    if not dry_run:
        questions_dir.mkdir(parents=True, exist_ok=True)
        # Remove any stale concurso question files if IDs changed
        written_names: set[str] = set()
        for rec in deduped_records:
            fname = f"{rec['id']}.json"
            written_names.add(fname)
            out_path = questions_dir / fname
            out_path.write_text(
                json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        for b_prefix in ("fgv-", "iades-", "cesgranrio-", "fcpc-"):
            for existing in questions_dir.glob(f"{b_prefix}*.json"):
                if existing.name not in written_names:
                    existing.unlink()

        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("w", encoding="utf-8") as fh:
            for q_rec in quarantine_records:
                fh.write(json.dumps(q_rec, ensure_ascii=False) + "\n")

    active_by_banca: Counter[str] = Counter()
    suspended_by_banca: Counter[str] = Counter()
    by_tag: Counter[str] = Counter()
    for rec in deduped_records:
        b = str(rec["exam"])
        if rec.get("status") == "active":
            active_by_banca[b] += 1
        else:
            suspended_by_banca[b] += 1
        for t in rec.get("tags") or []:
            by_tag[t] += 1

    return {
        "provas_by_banca": dict(sorted(provas_by_banca.items())),
        "raw_in_scope_matched": len(raw_imported),
        "deduped_imported_total": len(deduped_records),
        "active_by_banca": dict(sorted(active_by_banca.items())),
        "suspended_by_banca": dict(sorted(suspended_by_banca.items())),
        "by_tag": dict(sorted(by_tag.items())),
        "quarantined_total": len(quarantine_records),
        "quarantine_by_banca": dict(sorted(quarantine_by_banca.items())),
        "quarantine_reasons": dict(quarantine_reasons.most_common()),
        "skipped_out_of_scope_total": skipped_out_of_scope,
        "skipped_by_banca": dict(sorted(skipped_by_banca.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic importer for Brazilian public-sector IT exam PDFs."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "reports" / "concurso-sources.json",
        help="Path to concurso-sources.json manifest.",
    )
    parser.add_argument(
        "--questions-dir",
        type=Path,
        default=REPO_ROOT / "questions",
        help="Directory where question JSON files are written.",
    )
    parser.add_argument(
        "--quarantine-path",
        type=Path,
        default=REPO_ROOT / "reports" / "concurso-quarantine.jsonl",
        help="Path where quarantined candidate records are written.",
    )
    parser.add_argument(
        "--tags-path",
        type=Path,
        default=REPO_ROOT / "docs" / "tags.md",
        help="Path to docs/tags.md registry.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run extraction and validation without writing files.",
    )
    args = parser.parse_args(argv)

    summary = run_import(
        manifest_path=args.manifest,
        questions_dir=args.questions_dir,
        quarantine_path=args.quarantine_path,
        tags_path=args.tags_path,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
