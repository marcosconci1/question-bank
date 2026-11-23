# Installation

question-bank is a local Python tool. It stores the bank (question
files, assets, reports) in a data directory outside the repo and keeps
the engine in a normal Python package.

## Install

From a local checkout:

```bash
git clone https://github.com/marcosconci1/question-bank
cd question-bank
uv sync --locked              # core: CSV/JSON import, lexical search, MCP
uv sync --locked --all-extras # include PDF import, Qdrant semantic search, and web UI
```

Or install the CLI globally as a `uv` tool:

```bash
uv tool install git+https://github.com/marcosconci1/question-bank
# with optional extras:
uv tool install "question-search[all] @ git+https://github.com/marcosconci1/question-bank"
```

Optional extras in `pyproject.toml`:

- `import` (`pymupdf`): PDF ingestion (`pdf-board` and `pdf-llm` adapters).
- `semantic` (`qdrant-client`): Qdrant vector indexing and semantic search.
- `web` (`starlette`, `uvicorn`): optional local web UI under `web/`.
- `all`: installs all optional extras together.

This installs the project commands into the environment:

- `qb` (alias for `question-bank`): `init`, `import`, `ingest`, `validate`, `search`, `stats`, `mcp`, `doctor`, `diagnose`
- `question-search`: retrieval (`index`, `query`, `status`)
- `question-bank-mcp`: read-only stdio MCP server (`search-questions`, `get-question`, `list-topics`, `get-stats`)

Agent integrations live under `integrations/` (`hermes/`, `claude/`, `codex/`), and an optional web UI lives under `web/`.

## Where the bank lives

The default bank root is `$XDG_DATA_HOME/question-bank`, which falls
back to `~/.local/share/question-bank`. Point `QUESTION_BANK_ROOT` at
any directory to relocate it. The ingestion guide (`ingestion.md`)
explains the layout: `questions/` for records, `reports/` for the
manifest, quarantine, and the event journal.

`qb init` copies the default tag registry to the bank's `docs/tags.md`.
Ingest, validation, doctor, and MCP topic listing use that file when it
exists and use the packaged registry otherwise.

## First run

```bash
uv run question-bank doctor
```

Doctor checks the bank root, the questions and reports directories, the
manifest (if present), the tags registry, and the journal, and prints
one OK/WARN/FAIL line per check. On a fresh install with an empty bank
root it reports what is missing; create the directories by running your
first ingest.

## Requirements

- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
- Nothing else is required for CSV ingestion and keyword search.
- Optional: an OpenRouter API key for the LLM PDF adapter and for
  semantic search (`OPENROUTER_API_KEY`). Keyword search works with no
  key.
- Optional: `QDRANT_URL`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, and
  `EMBEDDING_DIM` to enable semantic search; `QUESTION_EXTRACT_MODEL`
  to choose the extraction model (default `openai/gpt-4o-mini`). The
  remaining search settings are `QUESTION_BANK_STATE` (where the index
  ledger lives), `QUESTION_BANK_COLLECTION` (Qdrant collection name),
  and `EMBED_BATCH_SIZE` (texts per embedding request); see
  `.env.example` for all of them with defaults.

Environment variables live in a `.env` file you create yourself; the
engine never writes one for you and never ships one.
