"""Flatten question content blocks and options into text for embedding and payload."""
import json
from pathlib import Path
from typing import Any


def flatten_block(block: Any) -> str:
    """Extract embeddable text from a single content block or string."""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        b_type = block.get("type")
        if b_type == "text":
            return block.get("content", "")
        if b_type == "image":
            return block.get("alt", "")
    return ""


def flatten_blocks(blocks: Any) -> str:
    """Flatten a list of content blocks or single string into newline-joined text."""
    if isinstance(blocks, str):
        return blocks.strip()
    if isinstance(blocks, list):
        items = []
        for b in blocks:
            text = flatten_block(b)
            if text and text.strip():
                items.append(text.strip())
        return "\n".join(items)
    return ""


def extract_context_first_text(context_data: Any) -> str:
    """Extract the first text block from a parsed context structure."""
    if isinstance(context_data, str):
        return context_data.strip()
    if isinstance(context_data, list):
        for b in context_data:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("content", "").strip()
            if isinstance(b, str) and b.strip():
                return b.strip()
    elif isinstance(context_data, dict):
        for key in ("body", "blocks", "stem", "content", "text"):
            if key in context_data:
                val = context_data[key]
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, list):
                    for b in val:
                        if isinstance(b, dict) and b.get("type") == "text":
                            return b.get("content", "").strip()
                        if isinstance(b, str) and b.strip():
                            return b.strip()
    return ""


def load_context_text(context_ref: str, contexts_dir: Path | None = None) -> str:
    """Load context JSON and extract its first text block."""
    if not context_ref:
        return ""
    if contexts_dir is None:
        from . import config
        contexts_dir = config.CONTEXTS_DIR
    if not contexts_dir.exists():
        return ""

    candidates = [
        contexts_dir / f"{context_ref}.json",
        contexts_dir / context_ref,
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                return extract_context_first_text(data)
            except Exception:
                pass
    return ""


def flatten_options(options: list[Any], question_type: str = "mc") -> list[str]:
    """Format MC options as 'A. ...', 'B. ...' preserving block content order."""
    if question_type != "mc" or not options:
        return []
    formatted = []
    for idx, opt in enumerate(options):
        letter = chr(ord("A") + idx)
        if isinstance(opt, str):
            opt_text = opt.strip()
        elif isinstance(opt, list):
            opt_text = flatten_blocks(opt)
        else:
            opt_text = str(opt).strip()
        formatted.append(f"{letter}. {opt_text}")
    return formatted


def flatten_question(question: dict[str, Any], contexts_dir: Path | None = None) -> str:
    """Produce the text to be embedded from question data.
    
    Rules:
    - Context reference contributes the context file's first text block.
    - Stem content blocks are flattened with text blocks joined by newline,
      LaTeX kept verbatim, image blocks contributing their alt text.
    - Option texts are appended (numbered A., B., ...).
    - Bare-string stems (v1 shorthand) are treated as a single text block.
    - Answer keys, rubrics, and tags are NEVER embedded.
    """
    parts: list[str] = []

    # Context (if referenced)
    context_ref = question.get("context")
    if context_ref:
        ctx_text = load_context_text(context_ref, contexts_dir=contexts_dir)
        if ctx_text:
            parts.append(ctx_text)

    # Stem
    stem = question.get("stem")
    if isinstance(stem, str):
        if stem.strip():
            parts.append(stem.strip())
    elif isinstance(stem, list):
        stem_text = flatten_blocks(stem)
        if stem_text:
            parts.append(stem_text)

    # Options (MC only)
    q_type = question.get("type", "mc")
    options = question.get("options")
    if q_type == "mc" and options:
        opt_lines = flatten_options(options, question_type=q_type)
        if opt_lines:
            parts.extend(opt_lines)

    return "\n".join(parts)


def build_payload(question: dict[str, Any], text: str) -> dict[str, Any]:
    """Build Qdrant point payload from question data and flattened text.
    
    Payload fields: question_id, exam, year, number, type, status, tags, source, answer, text.
    """
    year = question.get("year")
    try:
        year_int = int(year) if year is not None else None
    except (ValueError, TypeError):
        year_int = None

    number = question.get("number")
    try:
        number_int = int(number) if number is not None else None
    except (ValueError, TypeError):
        number_int = None

    q_id = question.get("id") or ""
    return {
        "question_id": str(q_id),
        "exam": str(question.get("exam", "")).lower(),
        "year": year_int,
        "number": number_int,
        "type": str(question.get("type", "mc")),
        "status": str(question.get("status") or "active"),
        "tags": list(question.get("tags") or []),
        "source": str(question.get("source", "")),
        "answer": question.get("answer"),
        "text": text,
    }
