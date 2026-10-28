# Hermes question-bank plugin

`question-bank/` is the self-contained Study-profile native plugin. Its
`tools.py` implements the handlers, `questionbank-tools.py` preserves the
original compatibility import path, and the plugin bundles the
`question-practice` skill. The module's public MCP server remains independent.

## Activation

Keep the plugin inside this module and link it into the Study profile, or copy
it to the profile's `plugins/` directory. Then enable both the plugin and its
profile gate:

```bash
hermes -p study plugins enable question-bank
hermes -p study config set question_bank.enabled true
```

Start a fresh Study session after activation. Do not enable
`question_bank.enabled` in profiles that should not receive these tools.

When the plugin remains in this module, it finds `question-search`,
`questions/`, and `assets/` without additional configuration. A copied
deployment must set portable paths in its service environment:

```ini
QUESTION_SEARCH_BIN=/path/to/question-bank/.venv/bin/question-search
QUESTION_BANK_ROOT=/path/to/question-bank
```

The adapter removes inherited `PYTHONPATH` and `PYTHONHOME` before invoking the
module CLI, isolating the Hermes and question-bank Python environments.

## Tool contract

The plugin exposes exactly three read-only bank tools:

- `search-questions` calls `question-search query` and returns ranked previews
  without answer keys or rubrics.
- `get-question` reads one source JSON object. With no `view`, it preserves the
  legacy response, including answer/rubric and repository-relative image paths.
- `get-stats` calls `question-search status` and aggregates the optional
  `data/users/<user>/answers.jsonl` log (configured via `QUESTION_BANK_USER`, default: `marcos`) without modifying it.

Explicit presentation views support independent practice:

- `get-question(id, view="practice")` removes `answer` and `rubric`, and
  converts every image-block `src` to an absolute path for `vision_analyze`.
- `get-question(id, view="solution")` retains the answer or rubric and also
  resolves image-block paths.

Missing images or paths outside `assets/` produce an adapter error rather than
an invented presentation.

## Attempt history

The three model-facing tools remain read-only. The Study skill uses the
agent-side `question-bank/skills/question-practice/scripts/record-answer.py`
helper through Hermes `terminal` to append graded attempts. It accepts one
JSON object through `--input -` with required `question_id`, `session_id`,
`given_answer`, and boolean `is_correct` fields; `time_spent` is optional.

The recorder derives exam, year, tags, and timestamp, writes one JSON object
per line to `data/users/<user>/answers.jsonl` (default user `marcos`), and rejects duplicate
`(question_id, session_id)` attempts. It never changes question files. The log
is runtime data and remains outside Git.
