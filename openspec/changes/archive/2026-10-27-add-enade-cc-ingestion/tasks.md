# Tasks: add-enade-cc-ingestion

## 1. Fetcher and provenance
- [x] 1.1 `scripts/fetch-enade-cc.py` downloads the 18 PDFs (6 editions x
  prova/gabarito/padrao) from geacc/enade into `data/raw/enade-cc/<year>/`,
  verifies SHA-256 against the Mendeley-published pins, writes
  `provenance.json` per edition (source URLs, hashes, CC BY 4.0 dataset +
  MIT mirror + INEP attribution, retrieval date). Idempotent re-runs.
- [x] 1.2 Force-add raw sources to git (`data/` is gitignored; POSCOMP 2025
  precedent).

## 2. Validator extension
- [x] 2.1 Extend `src/question_bank/validate.py`: exam enum, discursive
  type rules, ENADE component/course/context checks, per-exam year ranges.
- [x] 2.2 Extend `tests/test-validate.py` for the new rules; regression-run
  the validator over the existing 1,375-file bank (verdicts unchanged).

## 3. Adapter
- [x] 3.1a Extend the option contract compatibly: preserve legacy string
  entries and accept ordered text/image content-block entries; add regression
  coverage for validation and search flattening.
- [x] 3.1b `scripts/adapters/enade-cc-pdf.py`: per-year layout configs,
  prova parser (markers, options, images, contexts), three gabarito parser
  families, padrao rubric parser, Tesseract OCR path for 2014 and 2017.
- [x] 3.1c Produce reproducible exact-page option/figure crops, retain reliable
  OCR text in reading order, and report source page, crop rectangle, option
  position, and output path. Suspend any item whose boundaries cannot be
  established from the source.
- [x] 3.2 Run report with full rejection taxonomy; zero unexplained items.
- [x] 3.3 Import all 6 editions into `questions/` (+ `contexts/`,
  `assets/`).

## 4. Curation and retrieval
- [x] 4.1 Full-bank validation: zero format errors.
- [x] 4.2 `promote-curation.py`: activate clean records, suspend incomplete
  ones with reasons; report the counts.
- [x] 4.3 Representative audit: objective + discursive samples per edition
  checked against the PDFs; exceptions documented.
- [x] 4.4 Reindex module Qdrant (127.0.0.1:6343); live semantic queries
  return ENADE records.

## 5. Tests and docs
- [x] 5.1 Full module test suite passes.
- [x] 5.2 Update `README.md` (counts, ENADE usage) and
  `docs/ingestion.md` source table (source 2 -> done).
- [x] 5.3 Archive this change on completion.

## Current extraction audit

### Official answer-key, rubric, and inventory audit (2026-10-14)

- [x] Parsed all six official `gabarito.pdf` files against pinned objective
  manifests. No expected objective answer keys are missing; official voids
  are 2011 Q13 and 2021 Q29/Q33.
- [x] Audited all 17 discursive manifest entries against the official
  `padrao.pdf` files. Sixteen have answer rubrics; 2005 Q70 is explicitly
  marked `anulada` on page 4 and is a voided rejection, not a rubric record.
- [x] Corrected the expected non-void import inventory from 177 to 176 and
  added 2005 Q70 to the adapter's voided-discursive manifest.
- [x] Saved source PDF SHA-256 values, per-edition key/rubric counts,
  missing-item counts, and the corrected inventory to
  `reports/enade-cc-source-audit.json`. Bank records remain unwritten.
- [x] Visually mapped the six 2017 headings absent from native text:
  Q14 p19, Q15 p20, Q24-Q25 p25, Q34 p32, and Q35 p33. The source PDF hash
  and page mapping are recorded in `reports/enade-cc-extraction-progress.json`;
  crops remain pending.

### Bounded 2014 milestone (2026-10-14)

- [x] A report-driven targeted mode maps native-text question headings to
  source pages without OCR-scanning unrelated pages.
- [x] Q9, Q16, Q24, Q27 and Q35 produce 5 image-backed schema-v2 records in
  `reports/enade-cc-2014-targeted.json`; their 25 ordered A-E option crops
  and Q9/Q35 stem figures have deterministic asset names and page plus
  normalized-bounds provenance.
- [x] Reliable OCR stem text is retained; Q24's directly readable SQL option
  text is retained. Official answer keys and registered tag rules or
  explicit overrides supply answers and tags; no choice text is inferred.
- [x] The report accounts for 5 extracted and 22 pending 2014 objective
  questions. It sets `bank_records_written` and `import_ready` to false.
- [x] Targeted batch for Q10-Q15 (pages 13-15) uses page-bounded OCR for
  stems, 30 ordered A-E source crops, and a full Q13 tree crop. Its
  machine-readable report records expected=6, parsed=6, suspended=0, source
  pages, normalized crop bounds, dimensions, and SHA-256 evidence. No question
  records were written.
- [x] Consolidated 2014 coverage is 11/27 objective items (Q9-Q16, Q24,
  Q27, Q35); the import guard remains false. The report records 11 parsed
  and 16 pending.
- [x] Targeted Q17-Q23 batch (pages 17-20) records seven parsed items,
  official answers A/E/A/E/B/E/D, registered tags, 35 ordered option crops,
  and four figure crops with normalized bounds, dimensions, and SHA-256
  evidence. All 39 crops rerendered to their recorded hashes. The consolidated
  report reconciles 18/27 items and keeps imports guarded.
- [x] Resolve and audit the remaining 2014 items: Q25-Q26 and Q28-Q34. Do
  not fill missing text or boundaries by inference. All nine mapped items are
  parsed with ordered source crops, official keys, registered tags, and
  page/bounds/hash provenance; the consolidated report records 27/27 parsed,
  zero suspended, and keeps bank writes/import readiness false.
- [x] Extend the bounded approach to native-text page mapping for the other
  unresolved items, without OCR: 2005 Q59 p22; 2008 Q14 p8, Q18 p9, Q25 p12,
  Q38 p15; 2011 Q10 p9; and 2021 Q14 p23, Q35 p43.
- [x] Map 21 of 27 unresolved 2017 headings to pages using the native text
  layer: Q9 p16, Q10-Q11 p17, Q12 p18, Q13 p19, Q16 p20, Q17-Q18 p21,
  Q19 p22, Q20-Q21 p23, Q22-Q23 p24, Q26-Q27 p26, Q28-Q29 p27, Q30 p28,
  Q31 p29, Q32 p30, and Q33 p31.
- [x] Create visually verified crops for all mapped 2017 Q9-Q35 targets,
  including the six headings absent from native text. Extract searchable
  stems, ordered A-E options, official answers, and registered tags into a
  report-only fixture with deterministic page/bounds/hash provenance.
- [x] Extract the eight mapped non-2017 targets (2005 Q59; 2008 Q14, Q18,
  Q25, Q38; 2011 Q10; 2021 Q14, Q35) into bounded report fixtures with exact
  A-E order, official keys, registered tags, source-page crops, crop hashes,
  and per-edition coverage. Keep question writes and import readiness false.
- [x] Complete the ENADE 2005 source report with all 28 objective items and
  the nonvoid discursive Q55 rubric; retain the existing Q59 fixture, exclude
  officially annulled Q70, and verify native-text prompts, registered tags,
  official answers, targeted image crops, page/bounds/hash provenance, and
  the three pinned PDF hashes. Keep question writes and import readiness false.
- [x] Complete the report-only ENADE 2008 source fixture with all 27 objective
  and 3 discursive records. Integrate Q14/Q18/Q25/Q38 without duplicates;
  verify native-text stems/options, official keys/rubrics, registry tags,
  source hashes, page provenance, ordered A-E options, and deterministic
  figure crops. Keep question writes and import readiness false.
- [x] Complete the report-only ENADE 2011 source fixture with 26 eligible
  objectives and all 3 discursive records. Confirm official Q13 is annulled
  and absent, verify targeted Q10 is valid, retain official keys/rubrics,
  registered tags, source PDF hashes, exact A-E order, and replayable source
  crops. Keep question writes and import readiness false.
- [x] Complete the report-only ENADE 2014 source fixture with all 27 targeted
  objectives and 3 official discursive records. Reconcile objective keys,
  discursive prompts/rubrics, registered tags, source PDF hashes, page
  provenance, ordered image blocks, and reproducible source crops. Verify 30
  unique eligible records, no voids or gaps, and keep question writes and
  import readiness false.

The earlier cached full run emitted 115 items against the corrected 176-item
expectation; that cached count remains unaudited. Report-only full-source
fixtures now exist for all six editions and reconcile 160 eligible objectives
plus 16 nonvoid discursive records. Officially annulled Q13 (2011), Q29/Q33
(2021), and discursive Q70 (2005) are excluded. A later guarded report import
added all 176 question files; curation and the live Qdrant index are tracked
separately below. The candidate implementation replayed report JSON instead of extracting
question content from the PDFs. Tasks 3.1b and 3.1c remain open until the
PDF-driven adapter and crop replay pass all-six-edition acceptance tests.
Live indexing (4.4) and change archival (5.3) remain open.

- [x] Complete the report-only ENADE 2017 and 2021 full-source fixtures. The
  2017 report integrates all 27 targeted objectives once and includes all
  three official discursive prompts and rubrics. The 2021 inventory is taken
  from the source audit (27 objective entries, void Q29/Q33, three discursive
  entries): 25 objectives plus three discursive records. Both reports retain
  pinned source hashes and replayable page/bounds/hash crop evidence; the six
  edition reports reconcile to 176 unique eligible IDs. These report-only
  fixtures remain immutable inputs to the separate importer.

### Continuation curation review (2026-10-14)

- Source review is complete. The bank contains 176 ENADE records: 167 active
  and 9 suspended. One 2014 record retains a truncated stem; eight 2017 records
  retain OCR errors. Their existing curation reasons remain unchanged.
- Qdrant remains at 1,375 points with 176 ENADE records pending. Live indexing
  is pending secure embedding credentials.

### Source-backed review of the remaining suspended records (2026-10-14)

- Reviewed the 32 remaining suspended records against their pinned official
  `prova.pdf` and `gabarito.pdf` or `padrao.pdf`, verifying report-to-bank
  content matches, objective option order and keys, discursive rubrics, and
  recorded crop hashes. Evidence is in
  `reports/enade-cc-suspended-review.json`.
- Promoted 23 source-complete records. Kept `enade-2014-19` suspended because
  its imported stem remains truncated, and kept the eight 2017 records
  suspended because their imported stems contain unresolved OCR errors.
  Their curation reasons identify these source-quality issues.
- Final local bank accounting: 176 ENADE records, 167 active and 9
  suspended; active records have no incomplete-stem validation warning.
- This record review does not implement the generic PDF adapter. Task 3.1b
  remains unchecked and is an unmet delta for a separate focused coding task.

### PDF-driven completion and final verification (2026-10-27)

- All six edition-scoped oracle tests compare 176 records exactly with the
  audited fixtures while rejecting every runtime `reports/` read. They also
  verify configured rejection inventories, PDF provenance, and runtime crop
  hashes. The complete module suite passes: 98 tests.
- The adapter CLI dry-run emits 176 records with every edition complete and
  `import_ready: true`; question files and existing assets remain unchanged.
  The previously missing 2008 FG Q1 and other-degree Q59 scope rejections are
  included, and the import gate rejects incomplete or duplicate inventories.
- Full-bank validation reports 1,551 format-clean records. ENADE curation is
  167 active and 9 suspended with zero policy mismatches. Twelve representative
  objective/discursive samples across all editions pass source, key/rubric,
  content, and crop checks; the nine existing exceptions remain documented.
- Qdrant and the indexing ledger contain all 1,551 records with zero pending.
  Live CLI and Study-plugin semantic queries return ENADE records, and the
  answer-safe practice view keeps answers and rubrics out of pre-attempt reads.
