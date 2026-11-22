"""Command-line interface for question-bank (also exposed as ``qb``)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from question_bank import answers
from question_bank.doctor import build_diagnose_bundle, print_doctor, run_doctor
from question_bank.ingest.manifest import Source
from question_bank.ingest.pipeline import run_ingest, run_sources
from question_bank.ingest.profiles import build_source_from_profile, load_profile
from question_bank.journal import append_event
from question_bank.mcp_server import _calculate_stats, create_server
from question_bank.paths import resolve_bank_root
from question_bank.tag_registry import bundled_tags, resolve_tags
from question_bank.validate import validate_bank

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


def _cmd_init(target: Path, *, with_example: bool) -> int:
    root = target.expanduser().resolve()
    created: list[str] = []
    for subdir in ("questions", "assets", "corrections", "reports", "docs"):
        directory = root / subdir
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(f"{subdir}/")

    tags_dest = root / "docs" / "tags.md"
    if not tags_dest.exists():
        tags_dest.write_bytes(bundled_tags().read_bytes())
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

    tags_path = resolve_tags(root)
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_csv_options(csv_path: Path) -> dict[str, Any]:
    options: dict[str, Any] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = [col.strip() for col in next(reader, [])]
    except OSError:
        return options
    header_set = set(header)
    if "options" not in header_set:
        if all(col in header_set for col in ("A", "B", "C", "D", "E")):
            options["options_columns"] = ["A", "B", "C", "D", "E"]
        elif all(col in header_set for col in ("A", "B", "C", "D")):
            options["options_columns"] = ["A", "B", "C", "D"]
    if not any(col in header_set for col in ("knowledge_area", "area", "subarea")):
        for candidate in ("tags", "tag", "topic"):
            if candidate in header_set:
                options["tags_columns"] = [candidate]
                break
    return options


def _cmd_import(root: Path, args: argparse.Namespace) -> int:
    targets: list[str] = list(args.target)
    mode_hint: str | None = None
    if len(targets) == 2 and targets[0].lower() in {"pdf", "csv", "json"}:
        mode_hint = targets[0].lower()
        file_path = Path(targets[1]).expanduser().resolve()
    elif len(targets) == 1:
        file_path = Path(targets[0]).expanduser().resolve()
    else:
        print("usage: qb import [pdf|csv|json] <file> [options]", file=sys.stderr)
        return 2

    if not file_path.is_file():
        print(f"Import file not found: {file_path}", file=sys.stderr)
        return 2

    year = args.year if args.year is not None else datetime.now(timezone.utc).year
    extra_options: dict[str, Any] = {}
    for name in (
        "agency", "role", "booklet", "answer_key_kind", "booklet_url",
        "booklet_sha256", "answer_key_url", "answer_key_sha256",
    ):
        value = getattr(args, name)
        if value:
            extra_options[name] = value
    if args.answer_key:
        answer_key_path = args.answer_key.expanduser().resolve()
        extra_options["answer_key_path"] = str(answer_key_path)
        if answer_key_path.is_file() and "answer_key_sha256" not in extra_options:
            extra_options["answer_key_sha256"] = _sha256_file(answer_key_path)

    if args.profile:
        try:
            profile = load_profile(args.profile)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if profile.kind == "pdf-board" and "booklet_sha256" not in extra_options:
            extra_options["booklet_sha256"] = _sha256_file(file_path)
        source = build_source_from_profile(
            profile,
            file_path,
            year=year,
            exam=args.exam,
            extra_options=extra_options,
        )
    else:
        suffix = file_path.suffix.lower()
        kind = mode_hint
        if kind is None:
            if suffix == ".csv":
                kind = "csv"
            elif suffix in {".json", ".jsonl"}:
                kind = "json"
            elif suffix == ".pdf":
                kind = "pdf"
        if kind == "pdf":
            kind = "pdf-llm"
        if kind not in {"csv", "json", "pdf-llm"}:
            print(f"Unsupported import file type: {file_path.name} (pass --profile or use .csv/.json/.jsonl)", file=sys.stderr)
            return 2
        options = _detect_csv_options(file_path) if kind == "csv" else {}
        options.update(extra_options)
        exam_slug = (args.exam or file_path.stem).strip().lower()
        source = Source(
            id=f"import-{file_path.stem}",
            kind=kind,
            path=file_path,
            exam=exam_slug,
            year=year,
            options=options,
        )

    append_event(root, "import_start", "started", source_id=source.id, kind=source.kind, dry_run=args.dry_run)
    try:
        summary = run_sources(
            [source],
            dry_run=args.dry_run,
            bank_root=root,
            quarantine_path=args.rejects,
        )
    except Exception as exc:
        append_event(root, "import_finish", "failed", error_type=type(exc).__name__)
        print(f"question-bank import failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    append_event(root, "import_finish", "ok", counts=summary.as_dict())
    if args.json:
        print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"ingested: {summary.ingested}, skipped: {summary.skipped}, quarantined: {summary.quarantined}")
    return 0


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

    import_cmd = commands.add_parser(
        "import",
        help="import questions directly from CSV, JSON/JSONL, or PDF (with --profile)",
    )
    import_cmd.add_argument("target", nargs="+", help="file path (or 'pdf <file>')")
    import_cmd.add_argument("--profile", help="TOML import profile name (e.g. fgv, poscomp) or path")
    import_cmd.add_argument("--exam", help="exam slug override")
    import_cmd.add_argument("--year", type=int, help="exam year (defaults to current year)")
    import_cmd.add_argument("--answer-key", type=Path, help="answer-key PDF path for board profiles")
    import_cmd.add_argument("--agency", help="hiring agency for board profiles")
    import_cmd.add_argument("--role", help="role metadata for board profiles")
    import_cmd.add_argument("--booklet", help="booklet label for board profiles")
    import_cmd.add_argument("--answer-key-kind", choices=("final", "preliminary"), help="answer-key status")
    import_cmd.add_argument("--booklet-url", help="official exam booklet URL")
    import_cmd.add_argument("--booklet-sha256", help="exam booklet SHA-256 digest")
    import_cmd.add_argument("--answer-key-url", help="official answer-key URL")
    import_cmd.add_argument("--answer-key-sha256", help="answer-key SHA-256 digest")
    import_cmd.add_argument("--rejects", type=Path, help="write rejected candidates to this JSONL path")
    import_cmd.add_argument("--dry-run", action="store_true", help="validate without writing questions or rejects")
    import_cmd.add_argument("--json", action="store_true", help="print the summary as JSON")

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
    if args.command == "import":
        return _cmd_import(root, args)
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
        summary = run_ingest(args.manifest, args.source, dry_run=args.dry_run, bank_root=root)
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
