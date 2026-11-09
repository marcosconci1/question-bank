# Contributing

Thanks for your interest in question-bank. This page explains how to set
up the project and what a good contribution looks like.

## Setup

```bash
git clone https://github.com/marcosconci1/question-bank
cd question-bank
uv sync --locked
uv run python -m pytest tests -q
```

The suite is offline: PDF extraction tests use a dependency-injected
fake model client, and no test talks to a network endpoint.

## How to work

1. Open an issue first for anything that changes behavior.
2. Branch from `main`, named by the work: `feat/short-name`,
   `fix/short-name`, or `docs/short-name`.
3. Commit messages follow
   [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
4. Run the test suite before you open a pull request. A change that
   breaks tests will not merge.
5. Keep pull requests small. One behavior per pull request.

## Boundaries the code must keep

* The bank is append-only through `question-bank ingest`. Nothing else
  writes into the questions directory.
* Every ingested question carries source, page, and adapter provenance.
  A change that drops provenance does not merge.
* Validation failures quarantine with a reason; nothing is dropped
  silently.
* No telemetry, no hosted component, no network call beyond the
  configured extraction and embedding endpoints.
* Document changes in `docs/` in the same pull request as the code
  change they describe.
