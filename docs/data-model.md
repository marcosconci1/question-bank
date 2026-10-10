# Data Model — question-bank (post-reset)

DESIGN PHASE DRAFT — for sign-off in the project thread.

This doc maps the four-stage workflow (workflow.md) onto the ER model. The
conceptual model (conceptual-model.md) survives the reset unchanged in
shape; the reset adds one attribute, one entity split, and one status
lifecycle. Changes are marked **[NEW]**.

## Entities and what the workflow does to them

### Content entities (committed files)

**EXAM** — unchanged. An official exam edition (board + year + course).

**QUESTION** — gains one attribute: **[NEW] `status`**.
- `candidate | active | suspended | voided`, default `candidate`.
- The lifecycle belongs to CURATE: capture creates candidates, review
  activates them, defects suspend them, boards void them. Transition rules:
  - `candidate -> active` — human review pass approved it.
  - `active -> suspended` — defect found during practice (wrong key,
    missing image, unreadable stem). Reversible: `suspended -> active`
    after a correction.
  - `any -> voided` — board annulment or unfixable wrongness. Terminal,
    never deleted (the bank is append-only).
- Practice selects `active` only. Stats include everything attempted,
  regardless of current status (a question suspended today still owns
  the answers it earned).

**OPTION / CONTEXT / CONCEPT — content shape [NEW, 2026-09-23]:** every
content-bearing attribute (QUESTION stem, OPTION text, CONTEXT body, and
the discursive RUBRIC) is a **content-block list** — an ordered array of
typed blocks (`text`, `image`), with math inline inside text blocks as
LaTeX. This is the schema-level encoding of how real questions are laid
out (text / image / text in any order, images inside options); see
`schema.md` v2 for the block contract. A bare string remains valid
shorthand for a single text block. CONTEXT still lives once in
`contexts/`; CONCEPT still lives in the tag registry.

**CORRECTION** — **[NEW]** a first-class record, not a habit.
- `{question_id, field, old_value, new_value, reason, date}`.
- Corrections overlay lives in `corrections/`; importers apply them
  after capture. This is what keeps capture idempotent (rerun an
  importer without losing manual fixes) and curation auditable.

### Behavior entities (runtime, not bank content)

**STUDY_SESSION** — **[NEW]** now persisted as a file, not just a
concept: `{session_id, filter, question_ids, progress, started_at}`.
Written before the first question; the progress pointer is what makes a
session resumable.

**ANSWER** — unchanged in fields (`given_answer, is_correct, time_spent,
confidence`), but its store is now explicit: `data/answers.jsonl`,
append-only, one JSON object per line. **[NEW rule]** answers are keyed
by `(question_id, session_id)`; a question may be answered in many
sessions, but only once per session.

**STATS** — **[NEW]** explicitly NOT an entity. Aggregations over the
answer log, recomputed on demand, never stored as truth. The answer log
is the store; stats are views.

## The fact table

ANSWER is the fact table — every Measure-stage aggregation runs over it.
QUESTION is the dimension. This is stated explicitly because it decides
what gets normalized: question content is highly normalized (one file
per question); answers are deliberately denormalized (exam, year, and
tags denormalized into each answer record at write time) so stats never
need to join against 1,306 files.

## ER deltas (from er-model.md)

    QUESTION gains attribute: status (candidate | active | suspended | voided)
    QUESTION/OPTION/CONTEXT/RUBRIC content becomes content-block lists (text | image)
    QUESTION 1 -- N CORRECTION   (a question may receive corrections over time)
    STUDY_SESSION becomes persisted: session file with filter + ids + progress
    ANSWER gains: session_id, denormalized exam/year/tags at write time

Everything else in er-model.md stands as written.


## MCP access layer (2026-09-23, approved)

Agents consume the bank through an MCP server exposing exactly two
read-only tools:

    search-questions(objective, filters, limit) -> (0,n) ranked matches
        - objective in plain language (the student's study goal)
        - ranked by semantic search + tags; limit caps the count (never shuffles)
        - returns pointers: id, file path, preview, tags, status
    get-question(id) -> COMPLETE question object
        - stem blocks, image paths, options, ANSWER KEY (always included),
          rubric, exam, year, tags, status

Rulings: no random selection ever (objective-driven retrieval only);
answer key never withheld from agents. The bank files remain the source
of truth; the MCP layer is another derived consumer over them, same as
the search index.
