# Claude Code plugin

This directory packages `question-bank` as a Claude Code plugin backed by the
read-only stdio MCP server (`question-bank-mcp`).

## Quick start (local checkout)

```bash
claude --plugin-dir integrations/claude
```

To run against a local checkout instead of `uvx` from GitHub, update
`.mcp.json` to run `uv run --directory /path/to/question-bank question-bank-mcp`.

## Environment variables

- `QUESTION_BANK_ROOT`: path to your bank directory (defaults to
  `$XDG_DATA_HOME/question-bank`, usually `~/.local/share/question-bank`).
- `QUESTION_BANK_USER`: user name for `data/users/<user>/answers.jsonl`
  (defaults to `default`). Existing histories remain untouched; set this to the
  prior username to keep selecting an existing history. No old history is
  migrated, copied, merged, rewritten, or deleted.
- `OPENROUTER_API_KEY` (optional): enables semantic search; without it,
  `search-questions` automatically uses local keyless BM25 search.

## Exposed MCP tools

- `search-questions(objective, filters?, limit?)` — ranked previews without answers.
- `get-question(id, view="practice" | "solution")` — answer-safe practice view by
  default; pass `view="solution"` after the learner attempts the question.
- `list-topics(query?, level?, limit?)` — registered tags with active counts and
  `by_year` exam frequency.
- `get-stats()` — read-only aggregations from the optional answer log.

## Practice skills

Claude Code ships its own `question-practice` and `exercise-list` skills under
`integrations/claude/skills/`, including a standalone answer recorder for
`question-practice`.
