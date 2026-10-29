"""Keyless keyword search: BM25 over flattened question text.

Needs no API key, no vector store, and no index. It reads the question files
(with the corrections overlay applied) on every call; 1.5k questions take well
under a second. Tag/exam/year/status filters match the semantic path.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from question_bank.corrections import load_corrections

from . import config, flatten

K1, B = 1.5, 0.75
STEM_LEN = 6
TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a o as os um uma de do da dos das e em no na nos nas por para com que se ao aos "
    "ou mais como sua seu suas seus eh sao foi ser the of and to in is are for on with".split()
)


def fold(text: str) -> str:
    """Lowercase and strip accents."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(ch) != "Mn"
    )


def tokenize(text: str) -> list[str]:
    """Accent-folded tokens, stopwords removed, long words cut to a shared prefix."""
    return [
        token[:STEM_LEN]
        for token in TOKEN.findall(fold(text))
        if token not in STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


def _load(root: Path) -> list[dict[str, Any]]:
    fixes = load_corrections(root)
    questions = []
    for path in sorted((root / "questions").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            questions.append({**data, **fixes.get(str(data.get("id")), {})})
    return questions


def search(
    query: str,
    limit: int = 10,
    status: str | None = "active",
    exam: str | None = None,
    year_range: tuple[int, int] | None = None,
    tags: list[str] | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Rank questions by BM25. Filters define the candidate set; ties keep bank order."""

    root = root or config.BANK_ROOT
    wanted = {t.strip() for t in tags or [] if t.strip()}
    candidates = []
    for q in _load(root):
        if status and status.lower() != "all" and (q.get("status") or "active") != status:
            continue
        if exam and str(q.get("exam", "")).lower() != exam.lower():
            continue
        if year_range and not (isinstance(q.get("year"), int) and year_range[0] <= q["year"] <= year_range[1]):
            continue
        if wanted and not wanted & set(q.get("tags") or []):
            continue
        text = flatten.flatten_question(q, contexts_dir=root / "contexts")
        # Tag slugs are words too ("arvores-e-suas-generalizacoes"), so they help recall.
        tokens = tokenize(text) + tokenize(" ".join(q.get("tags") or []).replace("-", " "))
        candidates.append((q, text, Counter(tokens), len(tokens)))

    terms = list(dict.fromkeys(tokenize(query)))
    average = (sum(c[3] for c in candidates) / len(candidates)) if candidates else 1.0
    scored = []
    for position, (q, text, counts, length) in enumerate(candidates):
        score = 0.0
        for term in terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            containing = sum(1 for c in candidates if term in c[2])
            idf = math.log(1 + (len(candidates) - containing + 0.5) / (containing + 0.5))
            score += idf * frequency * (K1 + 1) / (frequency + K1 * (1 - B + B * length / average))
        scored.append((score, position, q, text))

    # Without tag filters, a question that shares no term with the query is not a result.
    if not wanted:
        scored = [row for row in scored if row[0] > 0]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [
        {
            "id": q.get("id", ""),
            "exam": str(q.get("exam", "")).lower(),
            "year": q.get("year"),
            "number": q.get("number"),
            "type": q.get("type", "mc"),
            "status": q.get("status") or "active",
            "score": round(score, 4),
            "preview": text[:160].replace("\n", " ").strip(),
            "tags": list(q.get("tags") or []),
            "engine": "lexical",
        }
        for score, _, q, text in scored[:limit]
    ]
