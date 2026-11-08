# question-bank

<p align="center">
  <img src="docs/banner.png" width="360" alt="question-bank">
</p>

## Overview

`question-bank` is a self-contained POSCOMP and ENADE Computer Science
question-bank module. It stores one question per JSON file and provides
validation, curation promotion, semantic retrieval, and a read-only MCP server.
Semantic retrieval embeds question text through OpenRouter and stores vectors
in this module's dedicated Qdrant instance.

The module owns its bank and retrieval state. It does not share a Qdrant
container, collection, volume, or ledger with other modules.

## Layout (engine vs bank)

This repo is the **engine**: code, tests, integrations, and profiles only.
No question text, assets, or user data live here. The **bank** (questions,
assets, corrections, answer logs, raw PDFs, reports) lives outside, resolved
by `question_bank.paths.resolve_bank_root()`:

1. `QUESTION_BANK_ROOT` if set, else
2. `$XDG_DATA_HOME/question-bank` (default `~/.local/share/question-bank`).

The bank directory holds `questions/`, `assets/`, `corrections/log.jsonl`,
`data/users/`, `reports/`, `docs/tags.md`, `data/raw/`, and owner-only
extraction scripts. Never commit bank data into this repo; `.gitignore`
guards the usual paths.

## Status

Implemented and migrated into `hermes-modules`. The bank contains 1,375
POSCOMP questions and 176 ENADE Computer Science questions from the 2005,
2008, 2011, 2014, 2017, and 2021 editions. The ENADE records comprise 160
objective and 16 discursive questions; 167 are active and 9 are suspended
after source review. One 2014 record retains a truncated stem, and eight 2017
records retain OCR errors. Official voids are excluded (2005 Q70, 2011 Q13,
and 2021 Q29/Q33). The report import is recorded in
`reports/enade-cc-import.json`. The live Qdrant collection and indexing ledger
contain all 1,551 bank records, with zero pending indexing. The PDF-driven
adapter reproduces all 176 ENADE records directly from the pinned sources;
per-year acceptance tests prohibit report replay and verify rejection
inventories and deterministic crop hashes.

## Data Contract

- **Question bank:** `questions/*.json` is the versioned POSCOMP and ENADE
  corpus. Each file is one question and is the source of truth for searchable
  content, including official answer keys and discursive rubrics.
- **Optional answer log:** `data/users/<user>/answers.jsonl` may contain local answer events
  consumed by the MCP statistics tool. Set `QUESTION_BANK_USER` to select the user (default: `marcos`).
  It is ignored by Git and is not required for retrieval.
- **State:** the content-hash indexing ledger is stored at
  `~/.local/share/question-bank/ledger.json` by default. Set
  `QUESTION_BANK_STATE` to relocate its parent directory.
- **Vector database:** the module's Docker Compose service exposes Qdrant only
  on loopback: HTTP at `127.0.0.1:6343` and gRPC at `127.0.0.1:6344`. Its data
  lives in the external Docker volume `question-bank-qdrant-data`.
- **Search payloads:** Qdrant stores deterministic question point IDs plus
  question metadata and flattened searchable text. Answer keys and rubrics are
  excluded from embedded text.

## Configuration

Configuration is read only from environment variables; no `.env` file is read
by the module. `OPENROUTER_API_KEY` is **optional**: without it, `query` uses
keyword (BM25) search over the question files and `index` is a no-op. With a
key and a running Qdrant, `query` ranks by meaning and falls back to keywords
if either is down. `--mode semantic|lexical` forces one engine.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Optional. OpenRouter credential for semantic embeddings. |
| `QDRANT_URL` | `http://127.0.0.1:6343` | Dedicated question-bank Qdrant HTTP endpoint. |
| `QUESTION_BANK_ROOT` | module root | Root containing `questions/` and optional `contexts/`. |
| `QUESTION_BANK_STATE` | `~/.local/share/question-bank` | Parent directory for `ledger.json`. |
| `QUESTION_BANK_COLLECTION` | `questions` | Qdrant collection name. |
| `EMBEDDING_BASE_URL` | OpenRouter API URL | Embeddings API base URL. |
| `EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Embedding model. |
| `EMBEDDING_DIM` | `1536` | Embedding vector dimension. |
| `EMBED_BATCH_SIZE` | `64` | Maximum texts submitted per embedding request. |

`.env.example` is a non-secret reference file only. Export the required values
through the environment used to run the command.

## Usage

```bash
cd ~/question-bank
uv sync --locked

# Start the isolated vector database (create its external volume once if needed).
docker volume create question-bank-qdrant-data
docker compose -f docker/docker-compose.yml up -d

export OPENROUTER_API_KEY="..."
uv run question-search index
uv run question-search query "distributed systems consistency" --top-k 10
uv run question-search status

# Re-audit and import the pinned ENADE report fixtures idempotently.
uv run python scripts/import-enade-reports.py --dry-run
uv run python scripts/import-enade-reports.py
uv run python scripts/promote-curation.py --exam enade --update

# Verify the PDF-driven ENADE adapter without writing bank content.
uv run python scripts/adapters/enade-cc-pdf.py --dry-run --report /tmp/enade-cc-runtime.json

# Run one edition's source-backed oracle (2005, 2008, 2011, 2014, 2017, or 2021).
uv run python -m pytest 'tests/test-enade-adapter.py::test_generic_year_normalization_matches_all_audited_editions[2014]' -q

# Run validation coverage and the complete automated suite.
uv run python -m pytest tests/test-validate.py -q
uv run --extra web pytest tests/ -q

# Serve the read-only MCP interface over stdio.
uv run question-bank-mcp
```

## Hermes Study practice

`integrations/hermes/question-bank/` is the Study-profile native plugin. It
registers the read-only `search-questions`, `get-question`, and `get-stats`
tools plus the `question-practice` skill. Practice retrieval omits answer keys
and rubrics until the learner attempts the question; solution retrieval keeps
them. Image blocks receive absolute local paths for Hermes vision.

The agent-side recorder at
`integrations/hermes/question-bank/skills/question-practice/scripts/record-answer.py`
appends graded attempts to `data/users/<user>/answers.jsonl` (default user `marcos`). It never modifies question
content and rejects duplicate `(question_id, session_id)` attempts. See
`integrations/hermes/README.md` for activation and the compatibility contract.

The validator and promotion workflow are provided by `question_bank.validate`
and `scripts/promote-curation.py`; see `docs/` for schema and curation details.
