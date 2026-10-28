# question-ingestion Specification

## Purpose
Preserve official ENADE Computer Science questions in a validated, searchable bank without losing image-dependent content or silently dropping exam items.

## Requirements

### Requirement: ENADE Ciência da Computação source

The bank SHALL include the complete Componente Específico corpus of every
ENADE Bacharelado em Ciência da Computação edition (2005, 2008, 2011, 2014,
2017, 2021), normalized into schema v2.

#### Scenario: objective question

- **GIVEN** an objective CE question with an official gabarito letter
- **WHEN** it is normalized
- **THEN** the record carries `type: "mc"`, exactly 5 options in A-E order,
  the gabarito `answer`, `exam: "enade"`, `component: "specific"`,
  `course: "computer-science"`, and >= 1 registered tag.

#### Scenario: printed option cannot be read reliably

- **GIVEN** an objective item whose printed A-E option boundary is verified
  in the official PDF but whose OCR text is unreliable or incomplete
- **WHEN** it is normalized
- **THEN** its corresponding ordered option entry contains a local image
  block cropped from that exact choice, with any reliable OCR text preserved
  as a text block in visual reading order
- **AND** readable stem text and registered tags remain searchable
- **AND** no option wording, symbol, or answer is guessed

#### Scenario: legacy string options

- **GIVEN** an existing record whose options are strings
- **WHEN** validation and search flattening process it
- **THEN** the record remains valid and each string option keeps its existing
  text and A-E position

#### Scenario: discursive question

- **GIVEN** a discursive CE question with an official padrão de resposta
- **WHEN** it is normalized
- **THEN** the record carries `type: "discursive"`, the expected answer as
  `rubric` content blocks, and no `options`/`answer` fields.

#### Scenario: officially voided question

- **WHEN** the gabarito marks a CC-scope question ANULADA
- **THEN** it is reported as a `voided` rejection and never written to the
  bank.

#### Scenario: out-of-scope items

- **WHEN** a joint booklet contains Formação Geral items or other degrees'
  sections
- **THEN** each is reported as an `out-of-scope-component` or
  `out-of-scope-degree` rejection with counts per edition; nothing is
  silently skipped.

### Requirement: validator ENADE support

The validator SHALL accept `type: "discursive"` (rubric required, options
and answer forbidden) and SHALL enforce `exam` in {poscomp, enade}, ENADE
`component`/`course` values, existing `context` references, and per-exam
year ranges, without changing verdicts for existing POSCOMP records.

#### Scenario: discursive record validation

- **WHEN** a file has `type: "discursive"` with a non-empty `rubric` and no
  `options` or `answer`
- **THEN** it validates clean; missing rubric or present options/answer are
  format errors.

#### Scenario: POSCOMP regression

- **WHEN** the validator runs over the pre-existing POSCOMP bank
- **THEN** every file yields the same verdicts as before the extension.
