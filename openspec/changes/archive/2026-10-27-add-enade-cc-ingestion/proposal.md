# Proposal: add-enade-cc-ingestion

## Why

The bank covers POSCOMP only. `docs/ingestion.md` v2 lists source #2 as
ENADE Ciência da Computação (Mendeley dataset w9hdbnrk85), status
"planned", and `docs/kickoff.md` names the ENADE import as the next
ingestion task. Source authorization in the canonical project thread
(1551118716580663308): "Both, A then B" — A (POSCOMP 2025) merged as
ca62d26 + d26bfe7; this change is step B.

## Source verification (done before this proposal)

- **Mendeley Data dataset w9hdbnrk85** ("Repositório de Questões do ENADE
  - Bacharelado em Ciência da Computação (2005 até 2021)", DOI
  10.17632/w9hdbnrk85.1, published 2024-10-29): public API reachable,
  `data_licence` = **CC BY 4.0** (verified via
  `https://data.mendeley.com/public-api/datasets/w9hdbnrk85`). Contains the
  6 complete exam PDFs (2005, 2008, 2011, 2014, 2017, 2021) plus
  per-question PNG captures. No answer keys or response standards.
- **geacc/enade GitHub mirror** (MIT-licensed repo of official INEP exam
  documents): README maps prefix `b` = Ciência da Computação **bacharelado**
  (`l` licenciatura, `e` engenharia, `s` sistemas de informação). Provides
  per-edition `prova` + `gabarito` + `padrao` (response standard) PDFs.
- **Course-mapping proof**: SHA-256 of every `b`-prefixed prova (and the
  unprefixed 2011 set) equals the hash Mendeley publishes for that edition's
  CS-bacharelado prova — the mirror files are byte-identical to the CC BY
  4.0 dataset's exams, and 2011 is confirmed as Ciência da Computação.
- **Edition coverage**: ENADE assessed Ciência da Computação in 2005, 2008,
  2011, 2014, 2017 and 2021 (triennial; 2020 postponed to 2021). The two
  sources agree; no other edition exists for this degree.

## What changes

- **Fetcher** `scripts/fetch-enade-cc.py`: downloads the 18 PDFs from
  geacc/enade into `data/raw/enade-cc/<year>/`, verifies each against the
  Mendeley-published SHA-256 pinned in code, writes `provenance.json` per
  edition (source URLs, hashes, licenses, retrieval date). Idempotent.
- **Adapter** `scripts/adapters/enade-cc-pdf.py`: parses prova/gabarito/
  padrao PDFs for the 6 editions and normalizes onto schema v2. Handles the
  three historical layouts (2005/2008 joint COMPUTACAO booklets with
  per-course ranges, 2011 combined booklet, 2014+ single-course booklets),
  the 2017 broken font encoding via Tesseract OCR (same fallback pattern as
  the POSCOMP 2025 adapter), and officially voided items as rejections.
- **Validator extension** (`src/question_bank/validate.py`): accept
  `exam: "enade"` with its schema-v2 fields (`component`, `course`,
  `context` reference existence) and `type: "discursive"` (rubric required,
  options/answer forbidden), exactly as `docs/schema.md` already specifies.
  POSCOMP behavior unchanged.
- **Import**: CE (componente especifico) questions for all 6 editions as
  `enade-<year>-<NN>.json` (objective) and `enade-<year>-d<N>.json`
  (discursive), plus `contexts/` records when several questions share one
  statement and `assets/` figures as image blocks.
- **Curation**: validator + `promote-curation.py` run over the enlarged
  bank; reindex the module Qdrant.

## Scope decisions

- **Componente Especifico only.** The Formacao Geral component is the same
  exam for every Brazilian degree, carries no CS content, and no existing
  registry tag applies to it ("use existing tags only" constraint). FG items
  are parsed, counted, and reported as `out-of-scope-component` rejections —
  never silently dropped. The schema's `component` field records
  `specific` on every imported record.
- **Other degrees in joint booklets are rejected with
  `out-of-scope-degree`** (2005 SI/EC ranges, 2008 EC/SI ranges, 2011
  LIC/EC/SI ranges): the approved scope is the CS bacharelado corpus only.
- **Ids for discursive questions** use `enade-<year>-d<N>` because 2011+
  editions number discursive questions in a separate sequence that would
  collide with objective numbers; `number` keeps the printed number. 2005
  and 2008 discursive questions already carry unique continuous numbers.

## What does NOT change

- Schema v2, the answer/rubric contracts, the tag registry, and every
  existing question file. Tags are assigned only from `docs/tags.md`.
- The validator's POSCOMP rules and the promotion pass semantics.
- No cross-module imports; the adapter copies the POSCOMP 2025 adapter
  pattern (pure normalize, writer separate, run report with rejection
  taxonomy).

## Acceptance

- Every extracted item accounted for: imported, `voided`,
  `out-of-scope-component`, or `out-of-scope-degree`.
- Bank validation clean; promotion activates valid records and suspends
  incomplete ones with reasons.
- `question-search` returns ENADE records for CS queries; full test suite
  passes.
