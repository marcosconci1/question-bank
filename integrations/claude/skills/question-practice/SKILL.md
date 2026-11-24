---
name: question-practice
description: Practice real exam questions without premature answers.
version: 0.2.0
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Learning, Practice, POSCOMP, ENADE]
    category: productivity
---

# Question Practice Skill

Run one-question-at-a-time practice with real POSCOMP and ENADE records. This
skill does not invent substitute questions, generate study plans, or move
session state into the question bank.

## When to Use

Use for exam practice, mock exams, targeted drills, discursive self-grading,
and reviews of recorded mistakes.

## Prerequisites

Use the connected question-bank MCP tools `search-questions`, `get-question`,
`list-topics`, and `get-stats` for bank access. Do not bypass these tools with
direct bank-file or CLI reads. Use Claude Code's `Read` tool for returned image
paths when the image reader can inspect them. Use `Bash` only for the optional
bundled answer recorder; keep bank access on the MCP tools.

## How to Run

1. Turn the learner's objective into one `search-questions` call. Keep the
   default `status: active`; apply exam, year, or tag filters only when the
   learner requested them or accepted an evidence-based proposal.
2. Select from the ranked results without shuffling. Fetch one item with
   `get-question(id, view="practice")`; this view omits answers and rubrics.
3. Render stem and options in block order. Read image blocks from their
   returned absolute `src` with Claude Code's image-capable file reader. If an
   image cannot be read, skip that record and explain why. Alt text is
   accessibility metadata, not a transcription.
4. Wait for a genuine attempt. After the attempt, call
   `get-question(id, view="solution")`, grade or support self-grading, and
   explain the exact error before continuing.
5. Record graded attempts with the bundled script, then use `get-stats` when
   the learner asks for progress or chooses the next practice target.

## Quick Reference

- Search: `search-questions(objective, filters?, limit?)`.
- Before an attempt: `get-question(id, view="practice")`.
- After an attempt: `get-question(id, view="solution")`.
- Progress: `get-stats()`.
- Record: run `python3 -I "${CLAUDE_SKILL_DIR}/scripts/record-answer.py" --input -`
  through `Bash`, supplying one JSON object on standard input. The script uses
  `QUESTION_BANK_ROOT` or its standard XDG bank location.

Required recorder fields are `question_id`, `session_id`, `given_answer`, and
`is_correct`. Optional `time_spent` is a non-negative integer measured during
the attempt; omit it rather than estimating it. The recorder derives exam,
year, tags, and timestamp from the bank and clock.

## Procedure

1. **Set the target.** Agree on the objective and rough question count. Create
   one opaque `session_id` for the practice run and reuse it. Do not include
   personal information in the identifier.
2. **Protect the challenge.** Never call the solution view or retrieve related
   worked answers before the learner attempts that question. Present one
   meaningful question at a time
   and do not leak the answer through hints, examples, or option emphasis.
3. **Handle visuals honestly.** Read every required image with the host's
   image-capable file reader. If a stem, figure, or option remains unreadable,
   skip that record without recording an attempt; never guess missing content.
4. **Grade by type.** For MC, compare the submitted letter with the official
   answer. For discursive items, show the rubric after the written attempt and
   ask the learner to self-assess; do not invent a correctness verdict for them.
   If the learner explicitly requests an early solution, reveal it but treat
   the challenge as spoiled and do not record an independent attempt.
5. **Append the attempt.** After grading, pass the attempt JSON to the recorder
   through `Bash` using a quoted heredoc so answer text is not shell-expanded.
   Run it with `python3 -I` and the explicit `${CLAUDE_SKILL_DIR}` script path.
   A duplicate `(question_id, session_id)` is already recorded; do
   not retry it or rewrite history. Never edit question JSON files.
6. **Close the loop.** Use `get-stats` only as evidence from the optional log.
   Propose a weak topic only after at least five recorded answers on that tag
   show weakness, and ask before changing the next practice target.

## Pitfalls

- In the MCP server, `get-question(id)` defaults to the answer-safe practice
  view. Request `view="solution"` only after the learner attempts the question.
- Search previews are for selection, not complete question presentation.
- Do not infer text from an option's array position, alt text, or answer key.
- Do not record skipped, spoiled, or ungraded attempts as independent answers.
- Do not auto-schedule practice, generate replacement questions, or silently
  widen filters when results are sparse.

## Verification

Before each attempt, confirm the practice payload contains neither `answer`
nor `rubric`. After grading, confirm the solution payload contains the expected
key or rubric. Verify recorder output against the appended JSONL line, and
leave all question files unchanged. Report empty retrieval, unavailable vision,
and recorder errors plainly instead of fabricating a session or statistics.
