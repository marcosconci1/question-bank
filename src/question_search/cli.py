"""CLI interface for question-search: index, query, status commands."""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config, embed, errors, flatten, ledger, store


def parse_year_range(raw: str) -> tuple[int, int]:
    """Parse '2015-2024' or '2020' into (min_year, max_year)."""
    raw = raw.strip()
    if "-" in raw:
        parts = raw.split("-", 1)
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            raise errors.InvalidArgsError(f"Invalid year range '{raw}'. Expected format: YYYY-YYYY or YYYY")
    else:
        try:
            y = int(raw)
            return y, y
        except ValueError:
            raise errors.InvalidArgsError(f"Invalid year '{raw}'. Expected format: YYYY-YYYY or YYYY")


def cmd_index(args: argparse.Namespace) -> int:
    """Index or re-index questions into Qdrant."""
    q_dir = config.QUESTIONS_DIR
    if not q_dir.exists() or not any(q_dir.glob("*.json")):
        raise errors.EmptyBankError(f"Question bank directory {q_dir} is empty or missing")

    store.ensure_collection()

    if getattr(args, "rebuild", False) and config.LEDGER_PATH.exists():
        try:
            config.LEDGER_PATH.unlink()
        except Exception:
            pass

    plan = ledger.reconcile(q_dir, config.LEDGER_PATH)
    to_index = plan["to_index"]
    deleted = plan["deleted"]
    unchanged = plan["unchanged"]
    state_ledger = plan["ledger"]

    # Handle deleted
    deleted_pids = [d["point_id"] for d in deleted if d.get("point_id") is not None]
    if deleted_pids:
        store.delete_points(deleted_pids)
        for d in deleted:
            ledger.record_deleted(state_ledger, d["question_id"])

    # Handle new and changed
    total_to_index = len(to_index)
    if total_to_index > 0:
        # Load questions and build payloads
        prepared: list[tuple[dict[str, Any], Path, str, str]] = []
        for item in to_index:
            p: Path = item["path"]
            try:
                q_data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                raise errors.QuestionSearchError("invalid_question_file", f"Failed to parse {p}: {exc}") from exc
            qid = q_data.get("id") or item["question_id"]
            text = flatten.flatten_question(q_data, contexts_dir=config.CONTEXTS_DIR)
            prepared.append((q_data, p, qid, text))

        # Embed in batches
        texts = [p[3] for p in prepared]
        vectors = embed.embed(texts)

        # Build points and update ledger
        points_to_upsert: list[tuple[int, list[float], dict[str, Any]]] = []
        for (q_data, p, qid, text), vec, item in zip(prepared, vectors, to_index):
            pid = store.make_point_id(qid)
            payload = flatten.build_payload(q_data, text)
            points_to_upsert.append((pid, vec, payload))

            try:
                rel_path = str(p.relative_to(config.BANK_ROOT))
            except ValueError:
                rel_path = str(p)

            ledger.record_indexed(
                state_ledger,
                question_id=qid,
                path_rel=rel_path,
                content_hash=item["hash"],
                point_id=pid,
            )

        store.upsert_points(points_to_upsert)

    # Save ledger
    ledger.save_ledger(state_ledger, config.LEDGER_PATH)

    summary = {
        "total_bank": len(unchanged) + total_to_index,
        "indexed": total_to_index,
        "skipped": len(unchanged),
        "deleted": len(deleted),
        "collection": config.COLLECTION,
    }

    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(
            f"Indexed {summary['indexed']} questions "
            f"({summary['skipped']} unchanged, {summary['deleted']} deleted). "
            f"Total in bank: {summary['total_bank']}."
        )

    return errors.EXIT_OK


def cmd_query(args: argparse.Namespace) -> int:
    """Execute filtered semantic search over the question bank."""
    query_text = (args.query or "").strip()
    if not query_text:
        raise errors.InvalidArgsError("Query text cannot be empty")

    year_range = parse_year_range(args.years) if args.years else None
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    # Embed query text
    query_vectors = embed.embed([query_text])
    if not query_vectors:
        raise errors.EmbeddingApiError("Received empty embedding vector for query")

    results = store.search_questions(
        query_vector=query_vectors[0],
        limit=args.top_k,
        status=args.status,
        exam=args.exam,
        year_range=year_range,
        tags=tags,
    )

    if getattr(args, "json", False):
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if not results:
            print("No questions found matching query and filters.")
        else:
            for i, r in enumerate(results, 1):
                exam_label = (r.get("exam") or "").upper()
                year_label = r.get("year") or ""
                num_label = f"#{r.get('number')}" if r.get("number") else ""
                tags_str = ", ".join(r.get("tags") or [])
                print(f"{i}. [{r['id']}] {exam_label} {year_label} {num_label} (score: {r['score']:.4f})")
                if tags_str:
                    print(f"   Tags: {tags_str}")
                print(f"   Preview: {r['preview']}")
                if i < len(results):
                    print()

    return errors.EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    """Show store and ledger indexing status."""
    q_dir = config.QUESTIONS_DIR
    bank_count = len(list(q_dir.glob("*.json"))) if q_dir.is_dir() else 0
    state_ledger = ledger.load_ledger(config.LEDGER_PATH)
    indexed_count = len(state_ledger.get("questions", {}))

    qdrant_points = store.count_points()
    pending = max(0, bank_count - indexed_count)

    info = {
        "qdrant_url": config.QDRANT_URL,
        "collection": config.COLLECTION,
        "qdrant_points": qdrant_points,
        "ledger_path": str(config.LEDGER_PATH),
        "ledger_indexed": indexed_count,
        "bank_questions_on_disk": bank_count,
        "pending_indexing": pending,
    }

    if getattr(args, "json", False):
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print("Question Bank Semantic Search Status:")
        print(f"  Qdrant URL:      {info['qdrant_url']}")
        print(f"  Collection:      {info['collection']}")
        print(f"  Qdrant Points:   {info['qdrant_points']}")
        print(f"  Ledger Path:     {info['ledger_path']}")
        print(f"  Ledger Indexed:  {info['ledger_indexed']}")
        print(f"  Bank on Disk:    {info['bank_questions_on_disk']}")
        print(f"  Pending Index:   {info['pending_indexing']}")

    return errors.EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="question-search",
        description="Semantic search and retrieval layer for question-bank.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # index subcommand
    p_index = subparsers.add_parser("index", help="Index question files into vector store")
    p_index.add_argument("--rebuild", action="store_true", help="Rebuild entire index from scratch")
    p_index.add_argument("--json", action="store_true", help="Output results in JSON format")

    # query subcommand
    p_query = subparsers.add_parser("query", help="Semantic query with deterministic filters")
    p_query.add_argument("query", type=str, help="Free-format natural language query")
    p_query.add_argument("--top-k", type=int, default=10, help="Number of results to return (default: 10)")
    p_query.add_argument("--tags", type=str, default=None, help="Comma-separated tags (match-any)")
    p_query.add_argument("--exam", type=str, default=None, help="Exam filter (e.g. poscomp, enade)")
    p_query.add_argument("--years", type=str, default=None, help="Year range (e.g. 2015-2024 or 2020)")
    p_query.add_argument("--status", type=str, default="active", help="Question status (default: active, or 'all')")
    p_query.add_argument("--json", action="store_true", help="Output results in JSON format")

    # status subcommand
    p_status = subparsers.add_parser("status", help="Show index and vector store status")
    p_status.add_argument("--json", action="store_true", help="Output results in JSON format")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for question-search CLI."""
    if argv is None:
        argv = sys.argv[1:]

    # Ergonomic shortcut: if first arg is not a known command/flag, treat as `query`
    if argv and argv[0] not in ("index", "query", "status", "-h", "--help"):
        argv = ["query"] + argv

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        return errors.EXIT_INVALID_ARGS if code != 0 else errors.EXIT_OK

    if not args.command:
        parser.print_help()
        return errors.EXIT_INVALID_ARGS

    try:
        if args.command == "index":
            return cmd_index(args)
        elif args.command == "query":
            return cmd_query(args)
        elif args.command == "status":
            return cmd_status(args)
        else:
            raise errors.InvalidArgsError(f"Unknown command: {args.command}")
    except BaseException as exc:
        return errors.report(exc)


if __name__ == "__main__":
    sys.exit(main())
