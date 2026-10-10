# semantic-search Specification

## Purpose
TBD - created by archiving change semantic-search-layer. Update Purpose after archive.

## Requirements

### Requirement: Question indexing
The system SHALL index every question file as exactly one Qdrant point,
keyed by question id, with the embedded text derived from content blocks
(text blocks + option texts + image alt text), and SHALL skip unchanged
files via a content-hash ledger.

#### Scenario: Fresh index over full bank
- **WHEN** `question-search index` runs against the 1,306-question bank
- **THEN** the Qdrant collection contains one point per question and the
  ledger records each file's content hash.

#### Scenario: Incremental re-index
- **WHEN** `question-search index` runs again with no bank changes
- **THEN** no embedding API calls are made and the index is unchanged.

#### Scenario: Bank file deleted
- **WHEN** `question-search index` runs after a question file is deleted
- **THEN** its point is removed from the index and ledger.

### Requirement: Semantic query with deterministic filters
The system SHALL answer a free-format natural-language query with ranked
question references, applying status/exam/year/tag filters inside the
vector search (Qdrant Filter), defaulting to `status: active`.

#### Scenario: Nuance query
- **WHEN** the agent queries "questions where you read code and pick the
  correct output"
- **THEN** ranked question refs are returned (id, exam, year, number,
  score, preview, tags) without any tag filter required.

#### Scenario: Filtered query
- **WHEN** a query runs with `--tags banco-de-dados --years 2015-2024
  --exam poscomp`
- **THEN** only matching, active POSCOMP questions appear.

#### Scenario: No matches
- **WHEN** nothing clears the result bar
- **THEN** an empty result is returned as a valid answer, not an error.

### Requirement: Isolation from other projects
The layer SHALL run its own Qdrant container, volume, ports, state
directory, and env file; it SHALL NOT import code from, share runtime
with, or touch the storage of any other project (library-query included).

#### Scenario: Other project absent
- **WHEN** the library-query container is stopped or removed
- **THEN** `question-search` index/query still function unchanged.

### Requirement: Bank is the only source of truth
The index SHALL be derived and rebuildable; the system SHALL NEVER modify
bank files, and SHALL NOT embed answer keys or rubrics.

#### Scenario: Volume loss
- **WHEN** the Qdrant volume is deleted and `question-search index` reruns
- **THEN** the index is rebuilt to the same state from bank files alone.
