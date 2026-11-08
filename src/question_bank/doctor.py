"""Local health checks and redacted diagnostic bundle for question-bank."""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from question_bank.ingest.board_adapter import BoardPdfAdapter
from question_bank.ingest.csv_adapter import CsvAdapter
from question_bank.ingest.llm_adapter import DEFAULT_EXTRACT_MODEL, PdfLlmAdapter
from question_bank.ingest.manifest import load_manifest
from question_bank.paths import resolve_bank_root
from question_bank.validate import load_registered_tags

from .journal import append_event, journal_path, read_events

ADAPTERS = {"csv": CsvAdapter, "pdf-board": BoardPdfAdapter, "pdf-llm": PdfLlmAdapter}


def _result(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def _manifest(root: Path) -> tuple[list[Any], dict[str, str] | None]:
    path = root / "reports" / "sources.json"
    if not path.exists():
        return [], None
    try:
        sources = load_manifest(path)
    except (OSError, ValueError) as exc:
        return [], _result("sources manifest", "FAIL", f"manifest could not be parsed ({type(exc).__name__})")
    unsupported = sorted({source.kind for source in sources if source.kind not in ADAPTERS})
    if unsupported:
        return sources, _result("sources manifest", "FAIL", "unregistered source adapter kind")
    return sources, _result("sources manifest", "OK", f"parsed; {len(sources)} sources, adapters registered")


def run_doctor(bank_root: str | os.PathLike[str] | None = None) -> tuple[list[dict[str, str]], int]:
    root = Path(bank_root).expanduser().resolve() if bank_root is not None else resolve_bank_root()
    results: list[dict[str, str]] = []
    root_ok = root.is_dir() and os.access(root, os.R_OK | os.X_OK)
    results.append(_result("bank root", "OK" if root_ok else "FAIL",
                           "exists and readable" if root_ok else "missing or unreadable"))

    questions = root / "questions"
    try:
        count = sum(1 for path in questions.rglob("*") if path.is_file()) if questions.is_dir() else 0
    except OSError:
        count = 0
    q_ok = questions.is_dir() and os.access(questions, os.R_OK | os.X_OK)
    results.append(_result("questions directory", "OK" if q_ok else "FAIL",
                           f"readable; {count} files" if q_ok else "missing or unreadable; 0 files"))

    reports = root / "reports"
    try:
        if root_ok:
            reports.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".question-bank-doctor-", dir=reports, delete=True):
            pass
        reports_ok = True
    except OSError:
        reports_ok = False
    results.append(_result("reports directory", "OK" if reports_ok else "FAIL",
                           "writable" if reports_ok else "not writable"))

    sources, manifest_result = _manifest(root) if root_ok else ([], None)
    if manifest_result is None:
        manifest_result = _result("sources manifest", "WARN", "not present")
    results.append(manifest_result)

    tags_path = Path(__file__).resolve().parents[2] / "docs" / "tags.md"
    try:
        tags = load_registered_tags(tags_path)
        tags_ok = bool(tags)
    except (OSError, UnicodeError):
        tags = set()
        tags_ok = False
    results.append(_result("tags registry", "OK" if tags_ok else "FAIL",
                           f"loaded; {len(tags)} tags" if tags_ok else "could not load registered tags"))

    model = os.environ.get("QUESTION_EXTRACT_MODEL", DEFAULT_EXTRACT_MODEL)
    model_ok = isinstance(model, str) and bool(model.strip())
    results.append(_result("extract model", "OK" if model_ok else "FAIL",
                           "resolved from environment or default" if model_ok else "model is empty"))

    if any(source.kind == "pdf-llm" for source in sources):
        key_present = bool(os.environ.get("OPENROUTER_API_KEY"))
        results.append(_result("OpenRouter key", "OK" if key_present else "WARN",
                               "configured" if key_present else "missing; PDF LLM ingestion will not run"))

    jp = journal_path(root)
    try:
        journal_ok = reports_ok and (not jp.exists() or os.access(jp, os.W_OK))
    except OSError:
        journal_ok = False
    results.append(_result("journal", "OK" if journal_ok else "FAIL",
                           "writable" if journal_ok else "not writable"))

    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    outcome = "FAIL" if counts.get("FAIL") else "WARN" if counts.get("WARN") else "OK"
    if root_ok:
        try:
            for item in results:
                append_event(root, "doctor_snapshot", item["status"].lower(),
                             check=item["name"], message=item["message"])
        except OSError:
            # The journal result already describes the failed storage check.
            pass
    return results, 1 if outcome == "FAIL" else 0


def _version() -> str:
    try:
        return version("question-search")
    except PackageNotFoundError:
        return "unknown"


def _redact_paths(value: Any) -> Any:
    home = str(Path.home().resolve())
    if isinstance(value, str):
        value = value.replace(home, "~")
        return re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", value)
    if isinstance(value, list):
        return [_redact_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_paths(item) for key, item in value.items()}
    return value


def build_diagnose_bundle(
    bank_root: str | os.PathLike[str] | None = None,
    *,
    last_events: int = 50,
) -> dict[str, Any]:
    root = Path(bank_root).expanduser().resolve() if bank_root is not None else resolve_bank_root()
    doctor, _ = run_doctor(root)
    events = read_events(root, last_events)
    append_event(root, "diagnose_bundle", "created", event_count=len(events))
    events = read_events(root, last_events)
    ingest_summary = None
    for event in reversed(events):
        if event.get("action") == "ingest_finish" and isinstance(event.get("counts"), dict):
            ingest_summary = event["counts"]
            break
    bundle = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "versions": {"python": platform.python_version(), "package": _version()},
        "doctor": doctor,
        "journal_events": events,
        "ingest_summary": ingest_summary,
        "openrouter_api_key_present": bool(os.environ.get("OPENROUTER_API_KEY")),
    }
    return _redact_paths(bundle)


def print_doctor(results: list[dict[str, str]]) -> None:
    for item in results:
        print(f"{item['status']}: {item['name']} — {item['message']}")
    failed = sum(item["status"] == "FAIL" for item in results)
    warned = sum(item["status"] == "WARN" for item in results)
    overall = "FAIL" if failed else "WARN" if warned else "OK"
    print(f"Summary: {overall} ({failed} failed, {warned} warnings, {len(results)} checks)")
