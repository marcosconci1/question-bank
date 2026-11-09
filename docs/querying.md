# Querying

`question-search` reads the bank and returns ranked questions. It never
writes to the bank; the index it builds lives next to the bank root as
a ledger plus a vector store.

## Build the index

```bash
uv run question-search index            # index pending questions
uv run question-search index --rebuild  # wipe and rebuild
uv run question-search status           # show mode, bank count, pending
```

## Search

```bash
uv run question-search query "hash tables collision handling"
```

Each hit shows the question id, a title with exam and year, the score,
the question's tags, and a text preview. Filters narrow the search:

```bash
uv run question-search query "hash tables" --exam poscomp --years 2015-2024
uv run question-search query "graphs" --tags algoritmos-e-estrutura-de-dados --top-k 5
uv run question-search query "normalization" --status all
uv run question-search query "indexes" --json
```

## Search modes

`--mode` chooses the strategy:

- `auto` (default): semantic search when an API key and vector store
  are available, keyword search otherwise.
- `semantic`: embedding-based retrieval through the configured
  embedding endpoint and Qdrant. Needs the optional environment
  variables from the installation guide.
- `lexical`: local keyword scoring with no API key and no network. It
  always works.

## What the results are

A hit is a location: the question id to open in `questions/`, plus the
tags and preview to judge it by. The tool ranks; you read the question.

## Requirements

- The bank must exist (`question-bank ingest` creates it).
- Keyword search has no prerequisites. Semantic search needs
  `OPENROUTER_API_KEY`, a Qdrant instance (`QDRANT_URL`), and the
  embedding settings (`EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`,
  `EMBEDDING_DIM`).
