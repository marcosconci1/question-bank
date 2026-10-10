# Ingestion Plan (v2 — modular, reuse-first)

DESIGN PHASE DRAFT — rewritten after sign-off feedback (2026-09-23):
ingestion must be modularized and must NOT reinvent wheels. Existing
datasets and parsers already exist for nearly every source; our code is
glue, not parsing engines.

## Pipeline architecture (four decoupled layers)

    SOURCE FETCHER -> PARSER (borrowed) -> NORMALIZER (ours) -> VALIDATOR

Each layer is pluggable and independently replaceable. A new source = a
new fetcher + adapter pair; the parser is picked off the shelf.

1. **Source fetchers** — download/cache raw sources (dataset CSVs, PDFs).
   Dumb and idempotent: fetch, cache under `data/raw/<source>/`, report
   what changed. One small script per source family.
2. **Parsers (borrowed)** — turn raw sources into structured intermediates
   (JSON with question text, options, key, images). NEVER written by us
   where a dataset or parser exists. Only parsed output reaches our code.
3. **Normalizers (the only code we own)** — map each source's intermediate
   onto the bank schema (`docs/schema.md`). One adapter module per source
   (`scripts/adapters/<source>.py`), sharing a common interface.
4. **Validator** — one shared gate before a question enters the bank
   (schema conformance, answer-in-range, tag registry check). Same rules
   for every source; this is where quirks die, not in adapters.

The bank never sees a source quirk: by the time a question file is
written, it is source-agnostic. Adapter contracts are the only
source-specific code in the repo.

## Sources (v2 status)

| # | Source | What we reuse | We write | Status |
|---|--------|---------------|----------|--------|
| 1 | POSCOMP (POSCOMP-RAG dataset, Zenodo/HF) | peer-reviewed CSV, 1,340 rows | normalizer only | done (PoC) |
| 2 | ENADE CC (Mendeley dataset w9hdbnrk85) | all editions 2005-2021, full PDFs + per-question captures | fetcher + normalizer | planned |
| 3 | ENADE other tech courses | same dataset family / INEP PDFs | fetcher + normalizer | later |
| 4 | PDF-only gaps | INEP PDFs via existing engines (see below) | config, not code | later |
| 5 | POSCOMP pre-2016 / image questions | awesome-poscomp PDFs + MinerU/Docling | config, not code | later, only if the bank feels incomplete |

### Key reuse decisions (researched 2026-09-23, kill-first)

- **The v1 plan for source 2 was hand-written PDF parsing. That is dead.**
  A Mendeley dataset (w9hdbnrk85) already collects every ENADE Computer
  Science edition (2005-2021) with full exam PDFs. We fetch a dataset
  instead of parsing INEP PDFs from scratch. PDF parsing becomes the
  fallback, not the plan.
- **When PDFs must be parsed**, use an existing engine: MinerU (best
  published accuracy on exam papers in OmniDocBench; AGPL - fine for a
  private bank) or Docling (MIT, typed document objects). Both handle
  layout, tables, formulas, and image extraction. We write zero
  OCR/layout code.
- **Precedent for the INEP PDF family**: caue-paiva/ENEM_PDF_PARSER
  already parses INEM (same INEP exam + gabarito layout family) into
  JSON including images, with the answer key joined. If a dataset route
  fails for a specific edition, adapting that parser is the fallback -
  borrowed code, not ours.
- **Licensing check done**: POSCOMP-RAG (CC BY), Mendeley (CC BY 4.0),
  Docling (MIT), MinerU (AGPL-3.0). All usable; the bank is private.

## Adapter contract (the modularity guarantee)

Every normalizer module implements the same interface and nothing else:

    normalize(source_record) -> NormalizedQuestion | Rejection

- `NormalizedQuestion` matches `docs/schema.md` exactly, including the
  `status: candidate` default from data-model.md (everything enters as
  candidate).
- `Rejection` carries a machine-readable reason (`voided`, `parse-error`,
  `duplicate`, `missing-answer-key`) and lands in the run report, never
  in the bank.
- Adapters are pure: no filesystem writes, no network. Fetchers fetch,
  adapters map, the writer writes. Each layer is testable in isolation.
- Context blocks (ENADE case texts) are emitted by adapters as separate
  `contexts/*.json` records with stable ids; the schema just references
  them.

## Cross-source rules (unchanged from v1)

- Ids namespaced by exam (`poscomp-...`, `enade-...`) - collisions
  impossible by construction.
- Tag collisions merge in `docs/tags.md` via aliases, never by editing
  question files.
- Importers are rerunnable/idempotent; manual fixes go through the
  `corrections/` overlay (data-model.md), applied post-import.
- Every import produces a machine-readable run report: counts in, counts
  out, rejection taxonomy (report the reject taxonomy, not just
  pass/fail).
