# Tasks: semantic-search-layer

## 1. Infrastructure
- [x] 1.1 Create `docker/docker-compose.yml` for `question-bank-qdrant` (external volume `question-bank-qdrant-data`, loopback-only, ports from `~/PORTS.md` not 6333/6334)
- [x] 1.2 Create `.env.example` (`QDRANT_URL`, `OPENROUTER_API_KEY`, `QUESTION_BANK_STATE` optional) and add `.env` to `.gitignore`
- [x] 1.3 Assign ports in `~/PORTS.md` and record them

## 2. Core indexer
- [x] 2.1 `src/question_search/config.py` — env-driven config
- [x] 2.2 `src/question_search/errors.py` — classified errors
- [x] 2.3 `src/question_search/flatten.py` — content blocks → embedded text (stems, options, alt, context first block; v1 string shorthand)
- [x] 2.4 `src/question_search/ledger.py` — content-hash ledger (add/skip/remove)
- [x] 2.5 `src/question_search/store.py` — Qdrant ensure-collection, deterministic point ids, upsert/delete, filtered vector query
- [x] 2.6 `src/question_search/embed.py` — OpenRouter embeddings with bounded batching

## 3. CLI
- [x] 3.1 `src/question_search/cli.py` — `index`, `query`, `status` commands with `--json`, `--top-k`, `--tags`, `--exam`, `--years`, `--status`
- [x] 3.2 pyproject with `question-search` entry point; `uv pip install -e .`

## 4. Tests and gates
- [x] 4.1 Unit tests: flatten (all block permutations + v1 shorthand), ledger skip/remove, payload shape
- [x] 4.2 Integration test: index a 5-question fixture bank, query returns ranked refs, filters exclude correctly
- [x] 4.3 Isolation test: run with library-query container stopped
- [x] 4.4 Full bank dry run: index 1,306, spot-check 5 nuance queries

## 5. Docs
- [x] 5.1 README section: commands, data contract, isolation guarantee
- [x] 5.2 Update `docs/semantic-search.md` status → implemented
