# Codex integration

Connect OpenAI Codex to `question-bank` via the read-only stdio MCP server
(`question-bank-mcp`).

## Register the MCP server

From a local checkout:

```bash
codex mcp add question-bank -- uv run --directory /path/to/question-bank question-bank-mcp
```

Or via `uvx` directly from GitHub:

```bash
codex mcp add question-bank -- uvx --from git+https://github.com/marcosconci1/question-bank question-bank-mcp
```

## Equivalent `~/.codex/config.toml` snippet

```toml
[mcp_servers.question-bank]
command = "uv"
args = ["run", "--directory", "/path/to/question-bank", "question-bank-mcp"]

[mcp_servers.question-bank.env]
QUESTION_BANK_ROOT = "/home/you/.local/share/question-bank"
```

## Optional `AGENTS.md` snippet

```markdown
## Question bank practice
- Use `list-topics` and `search-questions` to pick real exam questions.
- Call `get-question(id, view="practice")` before the learner attempts an item so answers and rubrics are withheld.
- Only call `get-question(id, view="solution")` after the learner submits an attempt (or asks to see the answer).
- Use `get-stats` to review recorded accuracy trends without mutating bank files.
```

## Exposed MCP tools

- `search-questions(objective, filters?, limit?)` — semantic search when configured, keyless BM25 fallback otherwise.
- `get-question(id, view="practice" | "solution")` — answer-safe practice view by default; solution view on request.
- `list-topics(query?, level?, limit?)` — registered tags with active counts and per-year `by_year` frequency.
- `get-stats()` — accuracy aggregations from `data/users/<user>/answers.jsonl`.
