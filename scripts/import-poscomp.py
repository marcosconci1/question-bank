#!/usr/bin/env python3
"""Import the POSCOMP-RAG dataset CSV into the question bank.

Reads data/poscomp-dataset.csv (Agents4Good/POSCOMP-RAG, CBIE 2025) and
emits one JSON file per question into questions/, with normalized exam
origin and content tags. Voided questions (officially annulled by the exam board) are
skipped and reported.

Usage:
    python3 scripts/import-poscomp.py [--csv data/poscomp-dataset.csv] [--dry-run]
"""

import argparse
import ast
import csv
import json
import sys
from pathlib import Path

VALID_KEYS = {"A", "B", "C", "D", "E"}


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("ç", "c").replace("ã", "a").replace("á", "a")
    text = text.replace("à", "a").replace("â", "a").replace("é", "e")
    text = text.replace("ê", "e").replace("í", "i").replace("ó", "o")
    text = text.replace("õ", "o").replace("ô", "o").replace("ú", "u")
    text = " ".join(text.split())
    out = []
    for ch in text:
        out.append(ch if ch.isalnum() else "-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def convert(csv_path: Path, out_dir: Path, dry_run: bool):
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    written = 0
    skipped = []
    seen_ids = set()
    subarea_tags = set()

    for r in rows:
        qid = (r.get("id") or "").strip()
        key = (r.get("key") or "").strip().upper()
        stem = (r.get("stem") or "").strip()
        try:
            options = ast.literal_eval(r["options"]) if r.get("options") else []
        except (ValueError, SyntaxError):
            skipped.append((qid, "options-unparseable"))
            continue

        if qid in seen_ids:
            skipped.append((qid, "duplicate-id"))
            continue
        if not qid or not stem or not options:
            skipped.append((qid, "empty-required-field"))
            continue
        if key == "ANULADA":  # Portuguese: officially voided/annulled
            skipped.append((qid, "voided"))
            continue
        if key not in VALID_KEYS:
            skipped.append((qid, f"bad-key:{key}"))
            continue

        # Normalize option strings: strip the "a) " prefixes into bare text,
        # keep list order as A-E.
        clean_options = []
        for opt in options:
            opt = opt.strip()
            # remove leading enumeration like "a) " or "e) "
            if len(opt) > 3 and opt[0] in "abcde" and opt[1:3] == ") ":
                opt = opt[3:]
            clean_options.append(opt)

        knowledge_area = (r.get("knowledge_area") or "").strip()
        area = (r.get("area") or "").strip()
        subarea = (r.get("subarea") or "").strip()

        # Content tags: the dataset's own hierarchy, slugged. Multiple tags
        # per question, per the kickoff decision.
        tags = [t for t in (
            slugify(knowledge_area),
            slugify(area),
            slugify(subarea),
        ) if t]
        if subarea:
            subarea_tags.add(f"{slugify(area)}::{slugify(subarea)}")

        question = {
            "id": f"poscomp-{qid}",
            "exam": "poscomp",
            "year": int(r["year"]),
            "number": int(r["number"]),
            "stem": stem,
            "options": clean_options,
            "answer": key,
            "source": f"POSCOMP {r['year']}, question {r['number']}",
            "tags": tags,
        }

        if not dry_run:
            out_path = out_dir / f"poscomp-{qid}.json"
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(question, f, ensure_ascii=False, indent=2)
                f.write("\n")
        written += 1
        seen_ids.add(qid)

    return written, skipped, subarea_tags


def main():
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=repo / "data" / "poscomp-dataset.csv")
    parser.add_argument("--out", type=Path, default=repo / "questions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    written, skipped, subarea_tags = convert(args.csv, args.out, args.dry_run)
    mode = "would write" if args.dry_run else "wrote"
    print(f"{mode} {written} questions from {args.csv.name}")
    print(f"skipped {len(skipped)}: ", end="")
    reasons = {}
    for _, reason in skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    print(", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    print(f"distinct subarea tags: {len(subarea_tags)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
