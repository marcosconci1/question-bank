# Hermes question-bank plugin

A native plugin for [Hermes Agent](https://hermes-agent.nousresearch.com)
that exposes read-only question-bank access to the agent. Its `tools.py`
implements the handlers, and the plugin bundles the `question-practice` and
`exercise-list` skills. The module's public MCP server remains independent.

## Activation

Copy or link this `question-bank/` folder into your Hermes profile's
`plugins/` directory. Then enable both the plugin and its profile gate:

```bash
hermes plugins enable question-bank
hermes config set question_bank.enabled true
```

Start a fresh session after activation. Do not enable
`question_bank.enabled` in profiles that should not receive these tools.

The bank root is selected from `QUESTION_BANK_ROOT`, then
`$XDG_DATA_HOME/question-bank`, or `~/.local/share/question-bank` when
`XDG_DATA_HOME` is unset. The search CLI is selected independently, in this
order: `QUESTION_SEARCH_BIN`, `question-search` on `PATH`, then the checkout's
`question-search.sh` launcher. Set portable paths in the service environment
for standalone deployments:

```ini
QUESTION_SEARCH_BIN=/path/to/question-bank/question-search.sh
QUESTION_BANK_ROOT=/path/to/question-bank
```

The adapter removes inherited `PYTHONPATH` and `PYTHONHOME` before invoking the
module CLI, isolating the Hermes and question-bank Python environments.

## Tool contract

The plugin exposes four read-only bank tools:

- `search-questions` calls `question-search query` and returns ranked previews
  without answer keys or rubrics.
- `get-question` reads one source JSON object. With no `view`, it preserves the
  legacy response, including answer/rubric and repository-relative image paths.
- `list-topics` lists registered tags from `docs/tags.md` (or the plugin's
  bundled `tags.md` when the bank has no local `docs/tags.md`) with active
  question counts and per-year `by_year` frequency.
- `get-stats` calls `question-search status` and aggregates the optional
  `data/users/<user>/answers.jsonl` log (configured via `QUESTION_BANK_USER`,
  default: `default`) without modifying it.

Explicit presentation views support independent practice:

- `get-question(id, view="practice")` removes `answer` and `rubric`, and
  converts every image-block `src` to an absolute path for `vision_analyze`.
- `get-question(id, view="solution")` retains the answer or rubric and also
  resolves image-block paths.

Missing images or paths outside `assets/` produce an adapter error rather than
an invented presentation.

## Attempt history

The four model-facing tools remain read-only. The practice skill uses the
agent-side `question-bank/skills/question-practice/scripts/record-answer.py`
helper through Hermes `terminal` to append graded attempts. It accepts one
JSON object through `--input -` with required `question_id`, `session_id`,
`given_answer`, and boolean `is_correct` fields; `time_spent` is optional.

The recorder derives exam, year, tags, and timestamp, writes one JSON object
per line to `data/users/<user>/answers.jsonl` (default user `default`), and rejects duplicate
`(question_id, session_id)` attempts. It never changes question files. The log
is runtime data and remains outside Git.

The default `question-search.sh` launcher runs the module through `uv`; ensure
`uv` is on the Hermes gateway PATH. `QUESTION_SEARCH_BIN` can select an alternate
launcher with the same CLI contract.

Existing answer histories are not moved or changed when the default is
`default`; no history is auto-selected, migrated, copied, merged, rewritten, or
deleted. Set `QUESTION_BANK_USER` to a prior username to keep selecting its
history.
