# Tasks: add-concurso-ti-ingestion

## 1. OpenSpec and Schema/Validator Extension
- [x] 1.1 Create OpenSpec change `openspec/changes/add-concurso-ti-ingestion/` (`proposal.md`, `design.md`, `tasks.md`, `specs/question-ingestion/spec.md`) and validate with `openspec validate add-concurso-ti-ingestion --strict`.
- [x] 1.2 Register granular data-structures and indexing subtopic tags in `docs/tags.md`.
- [x] 1.3 Extend `src/question_bank/validate.py` and `scripts/promote-curation.py` to support `exam` in `{"fgv", "iades", "cesgranrio", "fcpc"}`, year range `1990-2030`, 4 or 5 MC options, and required concurso `provenance` validation without changing POSCOMP or ENADE verdicts.
- [x] 1.4 Add validator unit tests in `tests/test-validate.py`.

## 2. Concurso Extraction, Classification, and Verification Engine
- [x] 2.1 Implement `src/question_bank/concurso.py` with PDF text extraction, question and option splitter (4 or 5 options), gabarito parser (by caderno/type, definitive vs preliminary, annulment handling), cross-caderno/role deduplication, rule-based classifier, round-trip verifier, quarantine writer, and idempotent importer.
- [x] 2.2 Create `tests/test-concurso.py` with synthetic PDF fixtures testing question splitting, option parsing, gabarito parsing, annulments, deduplication, classifier rules, round-trip verification, quarantine routing, validator integration, and idempotence (offline, no network required).

## 3. Official PDF Discovery, Fetching, and Ingestion
- [x] 3.1 Discover and download official `prova` and `gabarito` PDFs across FGV, IADES, CESGRANRIO, and FCPC into `data/raw/concurso/<banca>/<year>/` with polite rate-limiting and descriptive User-Agent.
- [x] 3.2 Record all downloaded source metadata and SHA-256 digests in `reports/concurso-sources.json` and document all considered exams and seed probes in `reports/concurso-discovery.md`.
- [x] 3.3 Run the ingestion pipeline to populate `questions/` and `reports/concurso-quarantine.jsonl`.

## 4. Verification and Documentation
- [x] 4.1 Verify full bank validation (`validate_bank`), keyless `question-search` queries (`arvore B`, `tabela hash encadeamento`), and full pytest suite (`uv run python -m pytest tests -q`).
- [x] 4.2 Document concurso schema, provenance, ID rules, and ingestion workflow in `docs/concurso.md`, `docs/schema.md`, `docs/ingestion.md`, and `README.md`.
