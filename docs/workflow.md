# Core Workflow — question-bank

DESIGN PHASE DRAFT — for sign-off in the project thread. No implementation
until this is approved.

The reset (2026-09-23): everything built so far was a PoC. The bank files,
the import script, the models — all of it is provisional input to this
design, not a commitment. What follows is the system as it should exist,
stated before any more code.

## The four stages

    CAPTURE -> CURATE -> PRACTICE -> MEASURE
         ^                          |
         +--------------------------+

The loop is the product. Each stage owns one question and one artifact.

### 1. CAPTURE — "how does a question enter the system?"

Real exam questions arrive from official sources (POSCOMP, ENADE) as PDFs
or datasets. The capture stage turns raw sources into candidate question
files.

- **Input:** raw source (CSV dataset, exam PDF, answer-key PDF).
- **Output:** candidate JSON files in the bank format (schema.md) + a
  rejection report (what was skipped and why: voided, parse failure,
  duplicate).
- **Rule:** capture is mechanical and rerunnable. Same source in, same
  files out. Manual fixes never touch imported files directly — they go
  through a corrections overlay applied after import.
- **Rule:** capture never silently drops information. If a question needs
  an image or a shared case block, the capture stage records that need
  (attachments paths, context references) even when the asset itself is
  not yet extracted.

### 2. CURATE — "is this question good enough to practice with?"

Raw capture is not trust. The curate stage is where a human (Marcos)
reviews candidates and promotes them into the practice pool.

- **Input:** candidate questions (capture output).
- **Output:** approved questions, tagged and registered.
- **Actions:**
  - Verify stem, options, and answer key against the official source
    (sampled per edition, not exhaustive — capture quality determines
    sample size).
  - Register every tag a question uses in the tag registry (docs/tags.md).
  - Fix transcription errors via the corrections overlay.
  - Flag image-dependent questions as blocked until assets exist.
- **Status model (the one design decision this stage adds):** every
  question carries `status: candidate | active | suspended | voided`.
  Only `active` questions enter practice sessions. This single field is
  what makes curation a stage instead of a ritual.
  - `candidate` — captured, unreviewed.
  - `active` — reviewed, in the practice pool.
  - `suspended` — was active, found broken (bad key, missing image,
    unreadable stem). Excluded from practice, kept for repair.
  - `voided` — the exam board annulled it, or it is unfixably wrong.
    Never deleted: the bank is append-only.

### 3. RETRIEVAL — "how does study actually happen?"

SCOPE RULING (Marcos, 2026-09-23): **the bank is infrastructure, like
graphify.** There is NO study plan, NO session artifacts, NO runner UX
inside the bank. The bank's entire job: answer free-format queries with
the best-matching questions and their locations (file paths). Everything
else — running practice, pacing, plans, resumability — belongs to the
AGENT side (the MCP client), not the bank.

- **The bank provides:** `search-questions(objective, filters, limit)`
  -> (0,n) ranked questions (ids, paths, previews),
  `get-question(id, view?)` -> the complete question object or an explicit
  practice/solution presentation, and `get-stats()` -> read-only answer-log
  aggregations. Free-format in, questions + locations + statistics out. That
  is the whole product surface.
- **The agent provides:** the practice loop itself — presenting one
  question at a time, showing the answer key after each attempt,
  handling discursive self-grading with the rubric, keeping its own
  session state (including resumability, if the agent wants it).
- **Answer records live OUTSIDE the bank.** The bank directory stays
  pure content. When an agent-run session wants to record answers, it
  writes to its own runtime store (`data/answers.jsonl`, append-only,
  one JSON per line), never as question content. Rebuilding the bank
  must never lose answer history — content and behavior are separate
  stores. The bank itself never writes answers; this store is optional
  convention for agents that choose to record on it.

### 4. MEASURE — "what do the answers say?" (agent-side consumer)

The stats tool reads the answer log and answers one question: where am
I losing points? Under the 2026-09-23 scope ruling, measure is also
agent-side: the bank exposes get-stats over the optional answer log;
the INTERPRETATION ("you are weak on X") and the proposal to practice X
happen in the agent, not the bank. The bank stays a facts-and-paths
service.

- **Input:** the answer log.
- **Output:** aggregations only — wrong-answer counts by tag, by exam,
  by year; accuracy trend over time; per-tag accuracy table. All
  derivable, nothing authoritative: the raw log is the store, aggregates
  are recomputed on demand.
- **First deliverable:** per-tag error ranking (which of the 206 POSCOMP
  subareas produce the most mistakes), because that directly feeds the
  next session's filter. This closes the loop: measure -> curate the
  next practice target -> practice.
- **Derived layers (error graph, concept maps) stay parked** until this
  simple aggregation has produced real study decisions.

## What the reset changes in practice

1. The 1,306 imported POSCOMP questions become `status: candidate` —
   they are capture output, not a curated pool, until a review pass
   marks them active.
2. The schema gains the `status` field (the only structural addition
   this design requires; everything else in schema.md stands).
3. Nothing else is built until this document + the data model + the two
   diagrams are signed off in the thread.

## Anti-scope (unchanged from kickoff)

No LLM question generation, no accounts, no web platform first, no
spaced repetition, no vector DB. One user. The bank is the project.


## CURATION — agent-reviewed (2026-09-23, Marcos ruling)

Marcos does NOT personally review bank questions. **Coddy (the agent)
performs the curation review**: take a set, verify the fields match the
schema, verify the question format is right, and promote or flag
accordingly. Marcos sees only the exceptions report.

### The agent review pass (what "check the set" means concretely)

Per question, mechanically verified (all automatable):

1. **Fields match**: every required field present and non-empty (id, type,
   exam, year, number, stem, answer, source, tags); id unique; id matches
   filename; year/number are integers in sane ranges.
2. **Format is right** (multiple choice): exactly 2-5 options, no empty
   option text, answer key is one letter within the options range, answer
   distribution across the set is plausible (a set where 90% of keys are
   "A" is a broken source), no duplicate ids.
3. **Content sanity** (heuristic, flags for deeper look): suspiciously
   short stems, stems ending mid-sentence, LaTeX that fails to parse,
   options that are near-duplicates of each other.
4. **Tags**: every tag registered in docs/tags.md (validator enforces).

Verdicts: format-clean questions get `status: active` in bulk per year
(the POSCOMP-RAG dataset proved structurally sound: first audit found
zero field/format problems across all 1,306); questions flagged by
content heuristics get `status: suspended` with a machine-readable reason
for a closer pass; board-voided stay `voided`.

### Day-one outcome under this ruling

The 1,306 POSCOMP questions can be promoted to `active` after the
automated audit passes (it did: no duplicate ids, no empty fields, all
5-option, uniform answer distribution A-E 226-281, zero format problems)
— with the heuristic-flagged list reviewed individually before those
specific questions activate. ENADE questions get the same treatment when
ingested: agent audit first, exceptions to Marcos only.


### MEASURE — the 2026-09-23 decision table (Q2)

The stats layer answers ONE question: where am I losing points? Three
sub-decisions make it concrete:

**M1. What drives what.** Stats exist to feed the NEXT SESSION's
objective. The per-tag error ranking is the bridge: "your 3 worst tags
this month" becomes the input of search-questions next session. Measure
without a resulting practice decision is trivia — cut it.

**M2. Who reads the stats.** The AGENT reads them (MCP ruling made the
agent the practice consumer). APPROVED by Marcos 2026-09-23 with the
concrete spec: the MCP tool surface for day one is exactly THREE tools —
`search-questions`, `get-question`, `get-stats`, all read-only.
`get-stats` returns accuracy per tag (the error ranking), accuracy per
exam/year, and the trend over time — one read over the answer log.
So measure is exposed as the third MCP tool:

    get-stats(scope) -> aggregations over the answer log
      - per-tag accuracy + error ranking
      - per-exam/year accuracy
      - accuracy trend over time

  The agent then PROPOSES the next session ("you've missed 7 of 9 on
  banco-de-dados; 10 questions on it?"). Marcos approves or overrides in
  chat. No dashboard, no web UI.

**M3. Loop closure: manual trigger, agent-prepared.** APPROVED by
Marcos 2026-09-23. The loop never closes silently (no auto-scheduling,
no spaced repetition). The agent proposes; the human decides. Proposal
discipline (part of the approval): the agent only raises a topic on REAL
evidence — at least 5 recorded answers on that topic showing weakness —
and every proposal is a question Marcos approves in chat, never an action
taken unilaterally. The system suggests, Marcos chooses.

Answer-log invariants that make M2 possible: one JSON line per answer,
session_id + denormalized exam/year/tags written at record time, so
get-stats never re-parses the bank and stays one read over one file.
