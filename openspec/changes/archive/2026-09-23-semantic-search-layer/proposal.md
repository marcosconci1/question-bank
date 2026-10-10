# Proposal: semantic-search-layer

## Why

Marcos wants the AI agent to find questions by nuance in free natural
language ("questions where you read code and pick the output"), which the
206-tag registry cannot express. The kickoff parked the vector DB with one
revisit condition — a consumer needing semantics over structure — and the
AI agent is that consumer. Design approved in the project thread
(2026-09-23): `docs/semantic-search.md`, schema v2 content blocks
(`docs/schema.md`), isolation ruling (modularization = first principle).

## What changes

Adds a retrieval-only semantic search layer over the question bank:

- **Own Qdrant container** `question-bank-qdrant` (this repo's `docker/`,
  own external volume, loopback-only, ports assigned per `~/PORTS.md` —
  NEVER library-query's 6333/6334, per the isolation decision).
- **Indexer** `question-search index`: one point per question (no
  chunking), embeddings via OpenRouter `openai/text-embedding-3-small`
  (1536d), content-hash ledger skipping unchanged files, derived and
  rebuildable.
- **Querier** `question-search "<free format>"` with payload filters
  (status, exam, year range, tags) applied inside Qdrant vector search.
- **CLI** with `index`, `query`, `status` commands, `--json` output.

## What does NOT change

- The bank JSON files remain the only source of truth; the index is
  derived and never edits the bank.
- Tags stay payload metadata — never embedded.
- Answer keys and rubrics are never embedded.
- No query expansion (parked until measured register gaps).
- No LLM answer generation — retrieval only.

## Isolation guarantee (first principle)

Zero runtime coupling with library-query: separate container, volume,
ports, state dir (`~/.local/share/question-bank/`), and `.env`. No code
imports from library-query — patterns are copied, not imported. Test: one
project down/decommissioned/reindexed ⇒ the other does not notice.
