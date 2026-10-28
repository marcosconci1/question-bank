# Design: add-enade-cc-ingestion

## Verified edition layouts

All facts below were verified against the actual PDFs (geacc/enade mirror,
byte-identical to Mendeley w9hdbnrk85 per SHA-256).

| Year | Booklet | Formacao Geral (excluded) | CE common to CC | CE CC-only | Voided (CC scope) |
|------|---------|---------------------------|-----------------|-------------------|-------------------|
| 2005 | joint COMPUTACAO | obj 1-7, disc 8-10 | obj 41-54, disc 55 (CC+EC) | obj 56-69, disc 70 | disc 70 (officially annulled) |
| 2008 | joint COMPUTACAO | obj 1-8, disc 9-10 | obj 11-19, disc 20 (CC+EC+SI) | obj 21-38, disc 39-40 | none (44 is EC-only) |
| 2011 | combined booklet | obj 1-8, disc D1-D2 | obj 9-30, disc D3-D5 | obj 36-40 | 13 |
| 2014 | single course | obj 01-08, disc D1-D2 | obj 09-35, disc D3-D5 | — | none |
| 2017 | single course | obj 01-08, disc D01-D02 | obj 09-35, disc D03-D05 | — | none |
| 2021 | single course | obj 01-08, disc D01-D02 | obj 09-35, disc D03-D05 | — | 29, 33 |

Expected import: 29 + 30 + 29 + 30 + 30 + 28 = **176 questions**
(160 objective after voids, plus 16 non-void discursive). Joint-booklet sections of other degrees and every FG
item are parsed and reported as rejections, never silently skipped.

Per-edition course ranges come from the provas' own instruction blocks
(e.g. 2005 page 8/16 tables, 2008 section banners, 2011 "Cursos / Numero
das questoes" table plus per-page course footers). The adapter pins these
ranges in a per-year config and asserts them: any deviation raises.

## Parsing hazards (verified)

- 2005 markers are split by line breaks (`QUESTÃ O 12`, `QUESTÃO 39 – DISC
  URSIVA`): the marker regex tolerates internal whitespace, and question
  kind comes from per-year config + gabarito, not marker text.
- 2014 and 2017 use custom-encoded fonts across their objective sections:
  the text layer is incomplete while glyphs render correctly. A page-level
  OCR fallback (PyMuPDF, 300 dpi; Tesseract `por`) recovers readable prose,
  but does not reliably recognize option labels, visual alternatives, or
  every question heading. OCR output must pass per-item completeness checks
  before import; a page's OCR text alone is not evidence that an item is
  complete.
- Gabarito layouts differ per year (plain pairs, `N - X` pairs,
  ITEM/GABARITO table, `QUESTÃO DISCURSIVA n ***` interleaved). One parser
  per family, each asserting the full expected item set.
- Padrão de resposta PDFs carry the discursive expected answers; they become
  `rubric` content blocks.

## Adapter contract

Follows `docs/ingestion.md`: fetcher (network, idempotent) -> borrowed
parser (PyMuPDF text/layout, Tesseract OCR fallback) -> normalizer
(`normalize(source_record) -> NormalizedQuestion | Rejection`, pure) ->
writer. The run report carries counts in/out and the rejection taxonomy
(`voided`, `out-of-scope-component`, `out-of-scope-degree`, `parse-error`,
`missing-answer-key`).

- Objective: exactly 5 options (A-E), answer letter from the gabarito.
- Discursive: `rubric` from the padrão; `options`/`answer` forbidden.
- `component: "specific"`, `course: "computer-science"` on every record.
- Figures are extracted as `assets/enade-<year>-q<NN>-<k>.png` and emitted
  as `image` blocks in document order with provenance alt text.
- Statements shared by several questions in one edition are factored into
  `contexts/enade-<year>-ctx-<n>.json` (schema v2) instead of being inlined.
- Tags: only slugs registered in `docs/tags.md`, assigned by deterministic
  keyword rules (POSCOMP 2025 adapter pattern) plus a small audited
  per-question override table inside the adapter for questions no rule
  classifies. Every record carries >= 1 tag.

## Validator extension (schema-conformant, POSCOMP-neutral)

`src/question_bank/validate.py` gains, only where the schema already
specifies the field:

- `exam` must be `poscomp` or `enade` (was unchecked).
- `type: "discursive"`: rubric required (non-empty content), options and
  answer forbidden. `mc` rules unchanged (exactly 5 options A-E).
- `exam == "enade"`: `component` in {`general-education`, `specific`} and
  `course == "computer-science"` required; `context`, when present, must be
  a non-empty string whose `contexts/<id>.json` file exists.
- Year rule widened from POSCOMP-only to per-exam: poscomp 2002-2025,
  enade {2005, 2008, 2011, 2014, 2017, 2021}.

Regression gate: the 1,375 existing files must produce byte-identical
validator verdicts before and after the change.

## Current extraction audit (2026-10-14)

The earlier cached full run emitted 115 items against a 177-item expectation.
The official 2005 Q55 rubric is recovered from `padrao.pdf` (its heading has
no dash); Q70 is explicitly annulled, correcting the expected import total
to 176.
Bounded, source-page-mapped reports now account for all 27 objective items in
the 2014 Componente Específico section, with 27 parsed and zero suspended.
All option crops record source page, normalized bounds, dimensions, and
SHA-256; the stems retain searchable text where readable, while grammar and
symbol-heavy choices remain image-backed. Official answers and registered
tags are recorded for every item. Official source audit confirms all six
objective answer-key inventories and all 16 non-void discursive rubrics; it
also found that 2005 Q70 is explicitly annulled in `padrao.pdf`, so it is a
voided discursive item rather than an importable rubric. The total expected
import is therefore 176, not 177. The adapter records Q70 as a `voided`
rejection. The 2005 full report covers all 29 eligible records. The full 2008
report in `reports/enade-cc-2008-full.json` covers all 27 objective and 3
non-void discursive records, integrating Q14/Q18/Q25/Q38 with the remaining
native-text extractions and bounded figure crops. These reports remain
report-only. The 2011 Q10 targeted fixture is integrated into its full report;
the 2014 full report is tracked in the later milestone below. The 2017 full
report integrates its 27-item targeted report and three discursive entries;
the 2021 full report follows the audited 28-record inventory and excludes
officially void Q29/Q33. All six editions now reconcile to 176 unique eligible
records. No question-bank files have been written, and import remains guarded.

Bounded visual lookup of the six 2017 headings missing from the native text
layer confirms Q14 on page 19, Q15 on page 20, Q24 and Q25 on page 25, Q34 on
page 32, and Q35 on page 33. Together with the 21 native-text page mappings,
all Q9-Q35 items are now recorded in
`reports/enade-cc-2017-targeted.json` with searchable OCR stems, ordered
image-backed options, official answers, registered tags, and deterministic
page/bounds/hash provenance. The crops were rerendered and hash-checked; this
remains report-only, with bank writes and import readiness false.

### Bounded 2014 Q17-Q23 milestone (2026-10-14)

The source-page-mapped Q17-Q23 batch (pages 17-20) is in
`reports/enade-cc-2014-batch-17-23.json`. All seven items parsed with
searchable stem and option text, ordered A-E option crops, and four figure
crops for Q19 and Q20. The report records normalized bounds, dimensions, and
SHA-256 values; all 39 crops were rerendered from their cited pages and
matched the recorded hashes. Answers A/E/A/E/B/E/D were checked against the
official 2014 `gabarito.pdf`, and every record has a registered topic tag.
Consolidated coverage is 18/27. The following bounded Q25-Q26 and Q28-Q34
batch resolves the final nine mapped items, bringing coverage to 27/27 with
zero suspended items. This remains report-only: `bank_records_written` and
`import_ready` are false.

### Bounded 2014 Q25-Q26 and Q28-Q34 milestone (2026-10-14)

The report in `reports/enade-cc-2014-batch-25-34.json` records nine parsed
items from pages 21-26, 45 ordered option crops, searchable stems and readable
option text where reliable, and image-backed grammar/math choices. Official
answers D/C/A/C/A/C/A/B/E and registered tags were verified. Crop paths,
normalized bounds, dimensions, and SHA-256 values are recorded. The
consolidated report accounts for 27 parsed and zero suspended items; it still
keeps `bank_records_written` and `import_ready` false.

## Approved extraction delta: image-backed objective options

The extraction audit above describes the OCR limitation; the approved
resolution is to preserve each objective item in A-E order even when its
printed option text cannot be read reliably. `options` remains the existing
array. Each entry may be either a legacy string (unchanged) or an ordered
schema-v2 content-block list containing `text` and/or `image` blocks. This is
the only schema extension. A string-option record remains valid and is never
rewritten during validation or flattening.

For an unreadable printed choice, the option entry contains a crop image
block referencing a deterministic, local PNG crop of that choice from the
verified edition PDF. The crop must include the printed choice boundary and
its visible label where present; the array index supplies its A-E position
when the label itself is not legible. Do not infer missing words, symbols, or
labels from an answer key. If reliable OCR text exists, preserve it as a text
block before/after the crop in the same option entry in visual reading order.
Image alt text identifies the crop as an option image without claiming its
contents. Stems and tags remain ordinary searchable text; option flattening
uses reliable text blocks and omits image pixels. The crop path is relative
to the bank and must resolve under `assets/`.

Image crops are generated from source PDF page coordinates and recorded in
the per-edition report with page, question number, option position, crop
rectangle, and output path so an auditor can reproduce them. Where OCR does
not provide defensible question/option boundaries, the item remains
explicitly suspended with source-page evidence; no synthetic A-E content is
created. The existing import safety gate remains in force until each year's
accounting, answer keys/rubrics, and all needed crop references validate.

### Report-only ENADE 2014 full-source milestone (2026-10-14)

`reports/enade-cc-2014-full.json` reconciles all 27 targeted objective records
with discursive D3-D5, for 30 unique eligible records and no voids or gaps.
The official answer key, prompts, rubrics, registered tags, and three pinned
source PDF hashes are checked against their source PDFs. Objective image
blocks retain their ordered A-E crops; the Sudoku and entity-relationship
figures use deterministic prompt-page crops with recorded bounds and hashes.
Every report crop can be reproduced from its cited `prova.pdf` page. Searchable
prompt, stem, option, and rubric text is retained. The report remains read-only
with respect to bank records and import readiness. At that milestone, the 2017
and 2021 full-source editions remained incomplete; they are completed in the
following milestone.

### Report-only ENADE 2017 and 2021 full-source milestone (2026-10-14)

`reports/enade-cc-2017-full.json` integrates the existing 27-objective
targeted report exactly once and adds the three official discursive prompts
and rubrics. Prompt crops for custom-encoded pages retain the original
page-specific content without OCR. `reports/enade-cc-2021-full.json` follows
the source-audited inventory: 27 objective entries, Q29/Q33 void, and three
discursive entries, yielding 25 objectives plus three discursive records.
Remaining objective text comes from the native text layer; page-specific
source crops preserve its printed context and figures. Both reports pin all
three source PDF hashes, compare answer keys and rubrics with native source
text, use registered tags, and record crop pages, normalized bounds, dimensions,
and hashes. The six full reports reconcile to 176 unique eligible records
(160 objective and 16 discursive). Report fixtures and crop assets remain
separate from `questions/`; bank writes and import readiness remain false.

The cached 115-item full run against the former 177-item expectation remains
unaudited and is not used as evidence for these manifests or counts.

### PDF-driven adapter completion (2026-10-27)

`normalize_year` now uses per-edition, source-hash-guarded producers and pinned
page/crop layouts to reproduce every audited record directly from the official
PDFs. Report JSON is never a runtime input. The six edition-scoped acceptance
tests compare all 176 records exactly, reject every `reports/` read, verify
official rejection inventories and PDF provenance, and rerender every runtime
crop to its recorded SHA-256. Out-of-scope items are reported from the verified
layout inventory even when their text markers are unreadable; the import gate
requires those exact inventories as well as complete records and image mapping.
