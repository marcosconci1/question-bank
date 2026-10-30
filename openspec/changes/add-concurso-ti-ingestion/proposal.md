# Proposal: add-concurso-ti-ingestion

## Why

The question bank currently covers only academic assessments (`poscomp` and `enade`). Public-service Information Technology competitive examinations (concursos públicos) from four examination boards (`fgv`, `iades`, `cesgranrio`, `fcpc`) are needed to support targeted study on data structures, indexing, and storage topics: B-trees (`arvore-b`), B+ trees (`arvore-b-mais`), balanced trees (`arvore-avl`, `arvore-rubro-negra`), hash tables (`tabelas-hash`, `hash-encadeamento`, `hash-enderecamento-aberto`), database indexes (`indices-banco-de-dados`), and related high-confidence data-structures and algorithms topics.

## Source policy

- **Official sources only**: Only official examination board and hiring organ PDF documents (`prova`, `gabarito`, `definitivo`) are permitted as question and answer-key sources:
  - FGV (`conhecimento.fgv.br/concursos/<slug>` and `conhecimento.fgv.br/sites/default/files/concursos/*.pdf`)
  - CESGRANRIO (`cesgranrio.org.br/concursos` and `concursos.cesgranrio.org.br/portal/avaliacoes/<id>`)
  - IADES (`iades.com.br/inscricao/upload/<n>/<file>.pdf`)
  - FCPC (`fcpc.org.br`)
- **Prohibited sources**: Third-party aggregators, paywalled sites, and scrapers (QConcursos, Gran Cursos, TecConcursos, EstudePlan, Certou, PCI Concursos) are strictly prohibited as sources of question text, options, or solution commentary.
- **Provenance and caching**: Raw PDFs are stored locally under `data/raw/concurso/<banca>/<year>/` (gitignored), and a committed manifest at `reports/concurso-sources.json` records every downloaded file's URL, SHA-256 digest, byte size, fetch timestamp, board (`banca`), hiring organ (`organ`), role (`role`), year, booklet (`caderno`), and document kind (`prova` | `gabarito` | `definitivo`). A discovery log at `reports/concurso-discovery.md` documents every examination considered, whether downloaded, and any skip reasons.

## What changes

- **Schema and Validator (`src/question_bank/validate.py`, `docs/schema.md`, `docs/concurso.md`)**:
  - Extend `exam` enum to accept `fgv`, `iades`, `cesgranrio`, and `fcpc` in addition to `poscomp` and `enade`.
  - Validate concurso year range (`1990-2030`) and allow 4 or 5 multiple-choice options (`A-D` or `A-E`) for concurso records while keeping `poscomp` and `enade` rules unchanged.
  - Require structured `provenance` on concurso records (`organ`, `role`/`roles`, `year` or `exam_date`, `caderno`, and official source URLs + SHA-256 digests).
  - Define a deterministic, collision-free identifier scheme `<exam>-<organ>-<year>-<role_or_caderno>-q<number>` and deduplicate identical questions across booklets/roles of the same examination into a single record listing all applicable roles and booklets in `provenance`.
- **Tag Registry (`docs/tags.md`)**:
  - Register granular subtopic slugs (`arvore-b`, `arvore-b-mais`, `arvore-avl`, `arvore-rubro-negra`, `hash-encadeamento`, `hash-enderecamento-aberto`, `indices-banco-de-dados`, `heap-fila-de-prioridade`) alongside existing hierarchy tags.
- **Concurso Ingestion Engine (`src/question_bank/concurso.py`, `scripts/ingest-concurso.py`)**:
  - PDF text-layer parser (PyMuPDF) for FGV, IADES, CESGRANRIO, and FCPC exam booklets and answer keys (`gabarito preliminar` and `gabarito definitivo`).
  - Explainable rule-based topic classifier for data structures, trees, hashing, database indexing, and algorithms.
  - Whitespace-normalized round-trip verification comparing re-rendered JSON records against extracted PDF source spans.
  - Quarantine routing (`reports/concurso-quarantine.jsonl`) for any candidate failing structural parsing or round-trip verification.
  - Answer-key status handling: annulled items are excluded; items backed only by a preliminary answer key are imported with `status: "suspended"` and `status_reason: "preliminary_answer_key"`; items meeting all four confidence gates with a definitive answer key enter with `status: "active"`.
- **Tests (`tests/test-concurso.py`, `tests/test-validate.py`)**:
  - Unit tests using synthetic in-memory/temporary PDF fixtures covering question splitting, 4- and 5-option parsing, gabarito parsing by booklet type, annulment exclusion, cross-caderno deduplication, classifier rules, round-trip verification, quarantine routing, validator rules, and idempotence.
