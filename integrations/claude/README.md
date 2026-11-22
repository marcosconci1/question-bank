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
  (defaults to `marcos`).
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

You can reuse the agent-agnostic `SKILL.md` guides in
`integrations/hermes/question-bank/skills/` (`question-practice` and
`exercise-list`) directly with Claude Code.
