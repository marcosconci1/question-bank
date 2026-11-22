"""Command-line interface for question-bank (also exposed as ``qb``)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from question_bank import answers
from question_bank.doctor import build_diagnose_bundle, print_doctor, run_doctor
from question_bank.ingest.pipeline import run_ingest
from question_bank.journal import append_event
from question_bank.mcp_server import _calculate_stats, create_server
from question_bank.paths import resolve_bank_root
from question_bank.validate import validate_bank

_BUNDLED_TAGS = Path(__file__).resolve().parents[2] / "docs" / "tags.md"

_EXAMPLE_CSV = (
    "id,number,stem,A,B,C,D,E,answer,topic\n"
    "2025-1,1,"
    "\"Which data structure offers O(1) average-time key lookup using a hash function?\","
    "\"Linked list\",\"Hash table\",\"Binary search tree\",\"Stack\",\"Priority queue\",B,tabelas-hash\n"
)

_EXAMPLE_MANIFEST = [
    {
        "id": "sample-2025",
        "kind": "csv",
        "path": "example.csv",
        "exam": "sample",
        "year": 2025,
        "options": {
            "id_column": "id",
            "number_column": "number",
            "stem_column": "stem",
            "options_columns": ["A", "B", "C", "D", "E"],
            "answer_column": "answer",
            "tags_columns": ["topic"],
            "source_template": "Sample Exam {year}",
        },
    }
]


def _resolve_tags_path(root: Path) -> Path:
    bank_tags = root / "docs" / "tags.md"
    return bank_tags if bank_tags.is_file() else _BUNDLED_TAGS


def _cmd_init(target: Path, *, with_example: bool) -> int:
    root = target.expanduser().resolve()
    created: list[str] = []
    for subdir in ("questions", "assets", "corrections", "reports", "docs"):
        directory = root / subdir
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(f"{subdir}/")

    tags_dest = root / "docs" / "tags.md"
    if not tags_dest.exists() and _BUNDLED_TAGS.is_file():
        shutil.copy2(_BUNDLED_TAGS, tags_dest)
        created.append("docs/tags.md")

    if with_example:
        example_csv = root / "reports" / "example.csv"
        if not example_csv.exists():
            example_csv.write_text(_EXAMPLE_CSV, encoding="utf-8")
            created.append("reports/example.csv")
        manifest_path = root / "reports" / "sources.json"
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(_EXAMPLE_MANIFEST, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            created.append("reports/sources.json")

    if created:
        print(f"Initialized question bank at {root}: {', '.join(created)}")
    else:
        print(f"Question bank already initialized at {root}")
    return 0


def _cmd_validate(root: Path, *, as_json: bool) -> int:
    questions_dir = root / "questions"
    if not questions_dir.is_dir():
        msg = f"Questions directory not found: {questions_dir}"
        if as_json:
            print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        else:
            print(msg, file=sys.stderr)
        return 1

    tags_path = _resolve_tags_path(root)
    result = validate_bank(questions_dir, tags_path)
    error_entries = [
        {
            "file": item.path.name,
            "errors": [{"code": issue.code, "message": issue.message} for issue in item.errors],
        }
        for item in result.errors
    ]
    payload = {
        "ok": not error_entries,
        "total": len(result.questions),
        "errors": len(error_entries),
        "warnings": len(result.warnings),
        "details": error_entries,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"Validated {payload['total']} questions: "
            f"{payload['errors']} with errors, {payload['warnings']} with warnings"
        )
        for entry in error_entries[:20]:
            codes = ", ".join(err["code"] for err in entry["errors"])
            print(f"  ERROR {entry['file']}: {codes}")
    return 0 if payload["ok"] else 1


def _cmd_search(root: Path, search_args: list[str]) -> int:
    from question_search import cli as search_cli
    from question_search import config as search_config

    search_config.BANK_ROOT = root
    search_config.QUESTIONS_DIR = root / "questions"
    search_config.CONTEXTS_DIR = root / "contexts"
    return search_cli.main(search_args)


def _cmd_stats(root: Path, *, user: str | None, as_json: bool) -> int:
    answer_log = answers.answers_path(root, user)
    stats = _calculate_stats(answer_log)
    questions_dir = root / "questions"
    bank_questions = sum(1 for _ in questions_dir.glob("*.json")) if questions_dir.is_dir() else 0
    payload = {"bank_questions": bank_questions, **stats}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        overall = stats["overall"]
        print(f"Bank questions: {bank_questions}")
        print(
            f"Attempts: {overall['total']} "
            f"({overall['correct']} correct, {overall['incorrect']} incorrect, "
            f"accuracy {overall['accuracy'] * 100:.1f}%)"
        )
        if stats["note"]:
            print(f"Note: {stats['note']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="question-bank")
    commands = parser.add_subparsers(dest="command", required=True)

    init_cmd = commands.add_parser("init", help="initialize an empty local question bank")
    init_cmd.add_argument("--path", type=Path, help="target bank directory (defaults to resolved bank root)")
    init_cmd.add_argument(
        "--with-example",
        action="store_true",
        help="include a starter CSV and sources.json manifest",
    )

    ingest = commands.add_parser("ingest", help="ingest configured question sources")
    ingest.add_argument("--manifest", type=Path, help="sources.json manifest (defaults to bank reports/sources.json)")
    ingest.add_argument("--source", help="run only this manifest source id")
    ingest.add_argument("--dry-run", action="store_true", help="validate without writing questions or quarantine")
    ingest.add_argument("--json", action="store_true", help="print the summary as JSON")

    validate_cmd = commands.add_parser("validate", help="validate all question JSON records in the bank")
    validate_cmd.add_argument("--json", action="store_true", help="print the validation report as JSON")

    search_cmd = commands.add_parser("search", help="search the bank (forwards arguments to question-search)")
    search_cmd.add_argument("search_args", nargs=argparse.REMAINDER, help="arguments for question-search")

    stats_cmd = commands.add_parser("stats", help="show bank count and practice accuracy statistics")
    stats_cmd.add_argument("--user", help="user profile name (defaults to QUESTION_BANK_USER)")
    stats_cmd.add_argument("--json", action="store_true", help="print stats as JSON")

    commands.add_parser("mcp", help="run the read-only stdio MCP server")
    commands.add_parser("doctor", help="check local question-bank configuration and storage")

    diagnose = commands.add_parser("diagnose", help="write a redacted local diagnostic bundle")
    diagnose.add_argument("--output", type=Path, help="write JSON to this file instead of stdout")
    diagnose.add_argument("--last", type=int, default=50, help="number of recent journal events to include")

    args = parser.parse_args(argv)

    root = resolve_bank_root()
    if args.command == "init":
        return _cmd_init(args.path or root, with_example=args.with_example)
    if args.command == "validate":
        return _cmd_validate(root, as_json=args.json)
    if args.command == "search":
        return _cmd_search(root, list(args.search_args))
    if args.command == "stats":
        return _cmd_stats(root, user=args.user, as_json=args.json)
    if args.command == "mcp":
        create_server(root).run(transport="stdio")
        return 0
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
