# Design: semantic-search-layer

## Decisions

1. **One point per question.** Each `questions/*.json` becomes exactly one
   Qdrant point. Deterministic 63-bit point id via uuid5 over
   `<question_id>:0` (same scheme as library-query, copied not imported).
2. **Embedded text** = stem blocks flattened (text blocks joined with
   newlines, LaTeX kept verbatim, image blocks contribute `alt`), then
   option texts (MC). Context reference contributes the context's first
   text block. Bare-string stems (v1 shorthand) flatten the same way.
3. **Payload per point**: `question_id, exam, year, number, type, status,
   tags, source, answer, text` (the flattened text, for previews). No
   rubric, no answer-key beyond the letter (payload only, never embedded).
4. **Ledger**: content-hash per question file at
   `~/.local/share/question-bank/ledger.json`; unchanged files skipped;
   deletions removed from the index; index rebuildable from scratch.
5. **Filters** (Qdrant `Filter`, must all match): `status` (default
   `active`), optional `exam`, optional year range
   (`year >= a AND year <= b`), optional tag match-any.
6. **Search**: single vector probe (expansion parked), cosine distance,
   `top_k` default 10. Output ranked: id, exam, year, number, score,
   preview (first ~160 chars of text), tags.
7. **Errors classified** (own `errors.py`): QdrantUnreachable,
   EmbeddingApiError, MissingApiKeyError, EmptyBankError — fail loudly,
   never partially index.
8. **Tooling**: uv (per VPS convention), Python 3.12, `qdrant-client`,
   `httpx`. CLI entry `question-search` via pyproject script.
9. **Ports**: build-time assignment from `~/PORTS.md`; defaults live in
   `.env.example` only.

## Migration / risk

- No migration: the bank format is untouched. The index is new-derived.
- Risks: embedding register gap (mitigation: parked expansion, measured
  later); Qdrant volume data loss (rebuildable by design).
