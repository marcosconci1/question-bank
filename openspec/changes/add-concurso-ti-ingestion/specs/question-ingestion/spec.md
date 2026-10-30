# Spec Delta: question-ingestion

## ADDED Requirements

### Requirement: Concurso TI official PDF ingestion

The bank SHALL ingest high-confidence Information Technology multiple-choice questions on data structures, algorithms, hashing, trees, and database indexing from official FGV, IADES, CESGRANRIO, and FCPC examination PDFs (`exam` in `{"fgv", "iades", "cesgranrio", "fcpc"}`), normalized into schema v2 with full source provenance.

#### Scenario: active concurso question with definitive gabarito

- **GIVEN** an official concurso `prova` PDF and its official `definitivo` answer-key PDF
- **WHEN** a question has cleanly parsed number, stem, and 4 or 5 ordered options (`A-D` or `A-E`), a non-annulled definitive answer letter, at least one registered in-scope tag assigned by the rule-based classifier, and a passing whitespace-normalized round-trip check against the PDF text
- **THEN** the importer writes a schema-v2 JSON record with `status: "active"`, `exam` set to the board slug, `provenance` recording organ, role(s), year/date, caderno(s), and official PDF URLs + SHA-256 hashes, and `>= 1` registered tags.

#### Scenario: preliminary answer key only

- **GIVEN** an official concurso question that passes structural extraction, topic classification, and round-trip verification, but whose official answer key is only published as `preliminar`
- **WHEN** the question is imported
- **THEN** the record is written with `status: "suspended"` and `status_reason: "preliminary_answer_key"`.

#### Scenario: officially annulled concurso question

- **GIVEN** a concurso question marked annulled (`*`, `X`, `ANULADA`, or `NULA`) in the official answer key
- **WHEN** the ingestion pipeline runs
- **THEN** the question is excluded and never written to `questions/`.

#### Scenario: cross-caderno or cross-role duplicate question

- **GIVEN** an identical question appearing across multiple booklet types or roles of the same `(banca, organ, year)` concurso (even with different question numbers or shuffled options)
- **WHEN** the concurso is ingested
- **THEN** the pipeline deduplicates the question into a single canonical record and lists all roles and cadernos in `provenance`.

#### Scenario: structural or round-trip failure routed to quarantine

- **GIVEN** an in-scope candidate question whose stem or options fail clean extraction or fail the whitespace-normalized round-trip check against the source PDF
- **WHEN** the ingestion pipeline processes the candidate
- **THEN** the candidate is not written to `questions/` and is logged to `reports/concurso-quarantine.jsonl` with candidate ID, reason, and PDF page number.

### Requirement: validator concurso support

The validator SHALL accept `exam` in `{"fgv", "iades", "cesgranrio", "fcpc"}` with `year` in `1990..2030`, 4 or 5 options (`A-D` or `A-E`) for `mc` questions, and required `provenance` fields (`organ`, `role`/`roles`, `year`/`exam_date`, `caderno`/`edition`, and source URLs with SHA-256 digests), while leaving all existing POSCOMP and ENADE validation verdicts unchanged.

#### Scenario: valid concurso question validation

- **WHEN** a concurso question file has `exam` in `{"fgv", "iades", "cesgranrio", "fcpc"}`, `year` in `1990..2030`, 4 or 5 non-empty options, an answer letter within the option range, registered tags, and complete `provenance`
- **THEN** `validate_question` reports zero format errors.

#### Scenario: missing or malformed concurso provenance

- **WHEN** a concurso question file omits `provenance` or lacks required `organ`, `role`, `caderno`, or official PDF URL/SHA-256 metadata
- **THEN** `validate_question` reports a format error blocking promotion.
