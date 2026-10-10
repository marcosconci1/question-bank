# question-bank

## Overview

`question-bank` is a self-contained POSCOMP question-bank module. It stores one
question per JSON file and provides validation, curation promotion, semantic
retrieval, and a read-only MCP server. Semantic retrieval embeds question text
through OpenRouter and stores vectors in this module's dedicated Qdrant
instance.

The module owns its bank and retrieval state. It does not share a Qdrant
container, collection, volume, or ledger with other modules.

## Status

Implemented and migrated into `hermes-modules`. The repository includes 1,306
curated POSCOMP question files, validation and promotion scripts, the
`question-search` CLI, and the `question-bank-mcp` server.

## Data Contract

- **Question bank:** `questions/*.json` is the versioned POSCOMP corpus. Each
  file is one question and is the source of truth for searchable content.
- **Optional answer log:** `data/answers.jsonl` may contain local answer events
  consumed by the MCP statistics tool. It is ignored by Git and is not required
  for retrieval.
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
by the module. `OPENROUTER_API_KEY` is required for indexing and querying.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | OpenRouter credential for embeddings. |
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
cd modules/question-bank
uv sync

# Start the isolated vector database (create its external volume once if needed).
docker volume create question-bank-qdrant-data
docker compose -f docker/docker-compose.yml up -d

export OPENROUTER_API_KEY="..."
uv run question-search index
uv run question-search query "distributed systems consistency" --top-k 10
uv run question-search status

# Run validation coverage and the complete automated suite.
uv run python -m pytest tests/test-validate.py -q
./.venv/bin/python -m pytest tests/ -q

# Serve the read-only MCP interface over stdio.
uv run question-bank-mcp
```

The validator and promotion workflow are provided by `question_bank.validate`
and `scripts/promote-curation.py`; see `docs/` for schema and curation details.
