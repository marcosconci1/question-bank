# Installation

question-bank is a local Python tool. It stores the bank (question
files, assets, reports) in a data directory outside the repo and keeps
the engine in a normal Python package.

## Install

```bash
git clone https://github.com/marcosconci1/question-bank
cd question-bank
uv sync --locked
```

This installs two commands into the project environment:

- `question-bank`: ingestion and diagnostics (`ingest`, `doctor`, `diagnose`)
- `question-search`: retrieval (`index`, `query`, `status`)

There is also an MCP server (`question-bank-mcp`) for coding agents, a
read-only Hermes Agent plugin under `integrations/hermes/`, and an
optional web UI under `web/`.

## Where the bank lives

The default bank root is `$XDG_DATA_HOME/question-bank`, which falls
back to `~/.local/share/question-bank`. Point `QUESTION_BANK_ROOT` at
any directory to relocate it. The ingestion guide (`ingestion.md`)
explains the layout: `questions/` for records, `reports/` for the
manifest, quarantine, and the event journal.

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
  to choose the extraction model (default `openai/gpt-4o-mini`).

Environment variables live in a `.env` file you create yourself; the
engine never writes one for you and never ships one.
