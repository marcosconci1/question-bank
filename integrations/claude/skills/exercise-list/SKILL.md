---
name: exercise-list
description: Use when asked for an exercise list on a content, built progressively.
version: 1.0.0
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Learning, Practice, POSCOMP, ENADE]
    category: productivity
---

# Exercise List

Build a short, ordered list of real exam questions for one content (a course unit or a topic). Triggers: "monta uma lista de exercícios de X", "exercícios de árvores", "lista progressiva", "quero treinar X do básico ao difícil".

The list is only a plan. To answer the questions, hand off to `question-practice`, one at a time.

## Rules that shape the list

- The bank has **no difficulty field and no prerequisite links**. Progression comes from the **order of the subtopics** (concept first, then use, then analysis/combination). Never say a question is "easy" or "hard" from the bank alone.
- Never expose answers. Planning uses `search-questions` previews only. Do not call `get-question` while listing.
- Never invent questions and never silently widen filters. If a subtopic has few or none, say so.
- Search needs no API key. It is keyword-based, so query with **short keyword phrases in Portuguese** (add synonyms yourself), not full sentences.

## Procedure

1. **Fix the content and size.** Default: 4-6 subtopics, 2-3 questions each, 12-18 total. Ask only if the content is truly ambiguous.
2. **Order the subtopics.** For a university course, read the course `README.md` (ementa) and `ROADMAP.md` in `~/unochapeco-cc/<course>/` and follow that order. Otherwise use standard teaching order for the content.
3. **Map subtopics to tags.** Call `list-topics(query=<keyword>)` per subtopic. Pick the registered slug that fits and read its `active_questions`. Drop empty slugs and report them in one line.
4. **Fetch candidates.** `search-questions(objective=<keywords>, filters={tags:[slug]}, limit=8)` per subtopic. Use `exam`/`year` filters only if the learner asked.
5. **Select per subtopic.** Keep 2-3: multiple choice first, a discursive item last in the group, different years when possible. Skip a candidate whose preview is garbled and note its id for `question-bank-repair`.
6. **Show the list** in the chat, grouped by subtopic: `n. id — exam year #number — preview (about 80 chars)`. Then one line: how many questions, which subtopics were short, and the first question to start with.
7. **Save only on request** (or when it is course work): append a `## Lista de exercícios — <content>` section with checkboxes to that course's single `ROADMAP.md`. Never create another file.
8. **Practice.** When the learner says go, run `question-practice` in list order. After at least five recorded answers on one subtopic, use `get-stats` to propose repeating a weak subtopic. Ask before changing the list.

## Pitfalls

- Presenting stem previews as the full question. Previews are for selection only.
- Padding a thin subtopic with unrelated questions to reach the count.
- Claiming difficulty order that the data cannot support.
- Reusing a list after the bank changed. Re-run the searches when the learner returns on another day.
