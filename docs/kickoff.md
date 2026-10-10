# Kickoff: question-bank

Kickoff run 2026-09-20 using the `project-kickoff` skill (design-thinking for
software, v1.1.0). Order of concern: problem understanding first, data models
third, wireframes last.

## Observations (Empathize)

- Marcos studies for university exams and postgraduate admission (POSCOMP);
  the highest-value practice material is real questions from official exams
  (ENADE, POSCOMP).
- Prior attempt: LLM-generated questions (ChatGPT) are not effective for
  studying — LLM generation is a rejected path.
- Existing asset: open-source extraction repos exist. A peer-reviewed
  POSCOMP dataset (Agents4Good/POSCOMP-RAG, 1,340 questions, 2002–2024, CSV
  with year/number/stem/options/key/knowledge_area/area/subarea) already
  exists; `issilva5/questoes_poscomp` is an alternative JSON source;
  `paladini/awesome-poscomp` has all exams + answer keys (2002–2025) for
  gaps and validation.
- Skill-updated principle from this kickoff: the bank is the asset; the
  interface is disposable.

## Open Questions

- ~~ENADE or POSCOMP first, or both mixed?~~ → Both, mixed in one bank but
  tagged by origin (`exam: poscomp` / `exam: enade`) and content tags (the
  tag list covers what the question covers, multiple tags per question
  allowed).
- Which extraction repos to use? → Research done: POSCOMP-RAG dataset as the
  primary source (peer-reviewed, structured, official answer keys included);
  awesome-poscomp PDFs as the validation source and gap-filler; ENADE from
  INEP PDFs + the HF MCQ dataset as a seed.
- Vector DB for semantic search/generation? → **Start simple: the tag system
  is the first retrieval mechanism.** Vector search was parked until a
  consumer exists that needs semantics over structure. **Unparked
  2026-09-23**: the AI agent (question selection in free natural language)
  is that consumer — see `docs/semantic-search.md`.

## Problem (Define)

**POV:** Marcos needs to practice with real ENADE/POSCOM exam questions,
because LLM-generated questions aren't effective for studying and the
official PDFs are not queryable or gradable as-is.

**Anti-scope:** No LLM question generation, no accounts, no web platform
first, no vector DB (parked), no spaced repetition. One user: Marcos. The
bank is the project; the interface is secondary.

## Options (Ideate)

1. **Static JSON bank + single HTML grader** — cost: zero infra, stats in
   localStorage, spartan UI. → Deferred: interface work before the bank
   exists.
2. **CLI quiz runner over JSON** — cost: fastest to build, terminal-native,
   fits how Marcos already uses `educational/`; no mobile/sofa usage.
   → **CHOSEN first iteration.**
3. **Import pipeline into Anki** — cost: Anki does scheduling/stats for
   free, but inherits Anki's data model, loses the "building it" value, and
   a prior attempt didn't stick. → REJECTED.

## Prototype (Prototype)

**Riskiest assumption:** The POSCOMP-RAG dataset's structure and quality are
good enough to power a study workflow directly (feasibility risk — a data
PoC, not a UI prototype).

**Artifact:** Import script: load `dataset.csv` → validate every row against
the question schema → emit `questions/*.json` (one file per question, `exam`
and tags normalized) → run the quiz runner over the imported set. If the
CSV loads and grades correctly, the assumption is confirmed; if parsing or
answer-key mismatches are rampant, the assumption is refuted and the import
pipeline becomes the project.

**Type: PoC** — proving feasibility, not desirability.

## Result (Test)

**PoC run 2026-09-20 — CONFIRMED (feasibility).**

- Dataset downloaded: 1,340 rows, 2002–2024, unique ids, all 5 options parse
  on every row.
- Validation: 1,306 questions clean and gradeable; the only 34 rejects are
  `key = ANULADA` (annulled questions — voided by the exam board; correctly skipped,
  not data corruption). Answer distribution across A–E is uniform
  (244–281), zero answers outside the options range.
- Import script: `scripts/import-poscomp.py` → one JSON per question in
  `questions/`, each with `exam`, `year`, `number`, `stem`, `options`
  (enumeration prefixes stripped), `answer`, `source`, and 3 normalized
  content tags (knowledge area / area / subarea, slugged).
- Tag system: **206 distinct subarea tags** — the retrieval primitive
  requested in Define exists out of the box for POSCOMP.

**Decision:** assumption confirmed. Next: CLI quiz runner with tag filters
(produces the wrong-answer evidence a future derived graph layer would
consume). Vector DB remains parked. ENADE import is the next ingestion
task after the runner exists.

## Parked Ideas

- **Derived concept/error graph** (graphify-style): nodes = questions and
  concepts, edges = tags + wrong-answer history. Derived index over the
  JSON bank, rebuildable; needs real study data before its edges are
  meaningful. Build after the runner accumulates error stats.
- **Vector DB**: parked, likely unnecessary at this scale (1,306 tagged
  questions; tag filtering is instant). Revisit only if tag retrieval
  proves insufficient.

