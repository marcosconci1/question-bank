"""Command-line interface for question-bank ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from question_bank.ingest.pipeline import run_ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="question-bank")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="ingest configured question sources")
    ingest.add_argument("--manifest", type=Path, help="sources.json manifest (defaults to bank reports/sources.json)")
    ingest.add_argument("--source", help="run only this manifest source id")
    ingest.add_argument("--dry-run", action="store_true", help="validate without writing questions or quarantine")
    ingest.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)

    try:
        summary = run_ingest(args.manifest, args.source, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"question-bank ingest: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"ingested: {summary.ingested}, skipped: {summary.skipped}, quarantined: {summary.quarantined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
