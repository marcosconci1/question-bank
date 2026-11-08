"""Command-line interface for question-bank ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from question_bank.doctor import build_diagnose_bundle, print_doctor, run_doctor
from question_bank.ingest.pipeline import run_ingest
from question_bank.journal import append_event
from question_bank.paths import resolve_bank_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="question-bank")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="ingest configured question sources")
    ingest.add_argument("--manifest", type=Path, help="sources.json manifest (defaults to bank reports/sources.json)")
    ingest.add_argument("--source", help="run only this manifest source id")
    ingest.add_argument("--dry-run", action="store_true", help="validate without writing questions or quarantine")
    ingest.add_argument("--json", action="store_true", help="print the summary as JSON")
    commands.add_parser("doctor", help="check local question-bank configuration and storage")
    diagnose = commands.add_parser("diagnose", help="write a redacted local diagnostic bundle")
    diagnose.add_argument("--output", type=Path, help="write JSON to this file instead of stdout")
    diagnose.add_argument("--last", type=int, default=50, help="number of recent journal events to include")
    args = parser.parse_args(argv)

    root = resolve_bank_root()
    if args.command == "doctor":
        results, status = run_doctor(root)
        print_doctor(results)
        return status
    if args.command == "diagnose":
        bundle = build_diagnose_bundle(root, last_events=max(0, args.last))
        rendered = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.expanduser().write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0

    append_event(root, "ingest_start", "started", source_id=args.source or "all", dry_run=args.dry_run)
    try:
        summary = run_ingest(args.manifest, args.source, dry_run=args.dry_run)
    except Exception as exc:
        append_event(root, "ingest_finish", "failed", error_type=type(exc).__name__)
        print(f"question-bank ingest failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    append_event(root, "ingest_finish", "ok", counts=summary.as_dict())
    if args.json:
        print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"ingested: {summary.ingested}, skipped: {summary.skipped}, quarantined: {summary.quarantined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
