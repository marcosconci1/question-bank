# Semantic Search Layer — question-bank

DESIGN PHASE DRAFT (2026-09-23) — ingestion is parked for a while; this is
the next layer to sign off. Inspiration: graphify (free-format question in,
matching places out) and the `library-query` module (which already solves
this exact problem for the personal library).

## Why this layer exists

Tags answer "which topic is this question about" — 206 POSCOMP subareas,
flat, curated. They cannot answer:

- "questions where you read a code snippet and pick the correct output"
- "anything that tests the *interpretation* of a graph, not its construction"
- "questions similar to the one I got wrong yesterday"
- "questions about deadlock that require *identifying* it from a schedule"

Those are nuances of phrasing, intent, and shape that no tag vocabulary
will enumerate. The kickoff parked the vector DB with a revisit condition —
"a consumer exists that needs semantics over structure" — and that consumer
now exists: an AI agent (me) needs to select questions for Marcos in free
natural language. Unparked, deliberately.

## What is borrowed from library-query (almost everything)

The design is deliberately a sibling of `hermes-modules/modules/library-query`,
same patterns, different corpus:

| Component | library-query | question-bank search |
|---|---|---|
| Vector store | Qdrant in Docker (loopback 6333/6334, existing container) | own Qdrant container `question-bank-qdrant` — separate ports, volume, compose (see Isolation decision below) |
| Embeddings | OpenRouter `openai/text-embedding-3-small` (1536d), batched | same model, same batching rules |
| Ledger | content-hash based, skip unchanged, rebuildable index | same: question files are content-addressed; re-index skips unchanged |
| Chunking | page/section chunks with overlap | **one point per question** (a question is already the right granularity — no chunking) |
| Payload | metadata + text per chunk | question id + exam/year/number/tags/status + rendered plain-text stem |
| Retrieval | question in → ranked places out, best-score merge | question in → question ids + stems out, ranked |
| Query expansion | cue-gated colloquial→clinical probes, additive | **parked**: start verbatim-only, add expansion only if register gap shows up in real agent queries |

## What is different (the important part)

1. **Unit of indexing is the question, not the chunk.** A question file is
   1 text block plus options — small enough to embed whole. Each question
   becomes exactly one Qdrant point (deterministic id from the question id,
   same uuid5 scheme). This removes the whole chunk-alignment problem
   library-query has.

2. **What gets embedded** (and in what form): the stem blocks flattened to
   plain text (LaTeX kept as-is — embeddings handle it as vocabulary), plus
   option texts for MC. Image blocks contribute their `alt` text (that is
   what alt is for — greppable description). Context references contribute
   the context's first text block. **Tags are NOT embedded** — they are
   payload, filterable, so exact topic filtering stays deterministic and
   semantics handle the rest. Embedding tags would double-count them.

3. **Hybrid retrieval, both halves honest:**
   - vector search over the semantic query (the nuance part);
   - Qdrant payload filter on tags/exam/year/status (the deterministic
     part) — Qdrant filters apply *within* vector search, so "active only"
     and tag constraints are enforced by the store, not post-hoc.
   - status filter defaults to `active` + `suspended` excluded; the agent
     can widen deliberately.
   The answer log layer (measure) can later re-rank by "never answered
   right" without touching the index.

4. **Derived and rebuildable, per the parked-ideas rule.** The collection
   holds copies; the bank files remain the only source of truth. Delete
   the container volume, re-run index, same result. The ledger makes that
   incremental. Nothing in the bank format changes for this layer — the
   JSON stays greppable and primary.

5. **M:N with the practice loop.** The agent queries semantically to
   *compose sessions*; the runner still records answers the same way.
   Search never writes to the bank.

## Interface (what the AI consumer calls)

    question-search "free format natural language query"
      [--tags a,b] [--exam poscomp|enade] [--years 2015-2024]
      [--status active] [--top-k N] [--json]

Output: ranked question refs (id, exam/year/number, score, stem preview,
tags). Retrieval only — session composition and grading stay in the
runner; answering stays with the agent.

## Anti-scope (per kickoff, restated)

- No LLM answer generation over the corpus — retrieval only.
- No re-ranking model, no cross-encoder, no hybrid BM25 (1,306 points;
  Qdrant vector + payload filters is instant; revisit if the bank passes
  ~10k or queries prove ambiguous).
- No query expansion until measured register gaps exist.
- The index never edits the bank.

## Open decisions for sign-off

1. ~~Second collection in the existing library-qdrant container~~ →
   **resolved 2026-09-23 (Marcos): fully separate.** Own container, own
   volume, own ports, own state. See the Isolation decision section.
2. Re-index trigger: manual `question-search index` after ingestion/curation
   runs (library-query model) vs a hook. Recommendation: manual, explicit.
3. Embedding the answer key / rubric: no — search should find questions by
   what they ask, not what they reveal.

## Isolation decision (2026-09-23, Marcos): fully separate projects

The library-query container is library-query's. This project gets its OWN
Qdrant container, its own compose file, its own volume, its own ports, and
its own state directory. The projects share design patterns only — no
shared runtime, no shared storage, no cross-dependencies, ever.

- **Container**: `question-bank-qdrant` (own docker-compose.yml in this
  repo's `docker/`), loopback-only.
- **Ports**: different from library-query's 6333/6334 — assigned per
  `~/PORTS.md` at build time, recorded there.
- **Volume**: `question-bank-qdrant-data`, external, owned by this repo.
- **State**: `~/.local/share/question-bank/` (ledger), never library-query's
  state dir.
- **Config**: environment variables (`QDRANT_URL`, `OPENROUTER_API_KEY`).
  No shared configuration file and no cross-repo environment variables.
- **Code**: no imports from library-query. Borrowed *patterns* (ledger
  scheme, batching, error taxonomy), copied where needed, never imported.
  If a helper is genuinely reusable, it graduates to a shared library as
  an explicit decision — not by one repo reaching into the other.

If one project is down, decommissioned, or reindexed, the other does not
notice. That is the test this decision is held to.


## MCP SERVER LAYER (2026-09-23, approved by Marcos)

The consumer of the bank is ANY AGENT, not a program Marcos sits at. The
search capability is exposed as an **MCP server** (MCP = the standard
protocol AI agents use to call external tools; already used on this VPS by
ai-memory and other services). Any MCP-speaking agent — Hermes/Coddy,
Samantha, coding CLIs — connects and asks the bank for questions.

### Tools (read-only, exactly three)

- **`search-questions(objective, filters, limit)`** — the agent states the
  STUDENT'S OBJECTIVE in plain language ("studying for the databases part
  of POSCOMP", "very specific: deadlock detection from schedules", "all of
  sorting algorithms for Friday's class"). Returns **(0, n)** questions
  that BEST MATCH the objective, ranked by semantic search combined with
  tag filters. `limit` (default 10) is a CAP on the result count — never a
  shuffle, never random. Fewer honest matches beat padded lists.
- **`get-question(id)`** — the COMPLETE question object for one question:
  stem (question text) as content blocks, image paths, options, the
  **answer key** (`answer` letter for MC, `rubric` for discursive), exam,
  year, tags, status. NOTHING WITHHELD — the answer key is always included
  (Marcos ruling: LLMs already know these answers; hiding them is security
  theater with zero benefit).
- **`get-stats()`** — read-only aggregations over the append-only
  `data/answers.jsonl`: per-tag accuracy and error ranking, per-exam
  accuracy, and overall accuracy by week. An absent or empty log returns
  zero values with an explanatory note.

### Objective levels (how the two retrieval strengths combine)

The student always has an objective. There is NO random selection — every
retrieval is objective-driven and relevance-ranked (Marcos, 2026-09-23):

- **study for a class** -> broad semantic match, few tag constraints
- **study a specific topic** -> tighter tag filters + semantic match
- **study a verrry specific topic** -> nearly literal semantic query
  (the case tags alone could never serve — why the vector layer exists)

### Rulings folded into this design

- Answer key NOT hidden from agents (Marcos: LLMs already know these
  answers; omission has zero benefit). This overrules the earlier
  recommendation.
- No random tool. No shuffle. The objective drives retrieval; `limit`
  only caps the list size.
- Portuguese words from Marcos = missing English term; system-side
  vocabulary is English (answer key, stem, options).

### Implementation shape (design; implementation still gated)

The existing `question-search` CLI stays as the local/debug interface; the
MCP server wraps the same core (store.py + flatten.py), exposing the three
tools over stdio per MCP conventions. Isolation guarantee unchanged:
own container, ports, state; no shared runtime with any other project.
