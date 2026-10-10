# Hermes question-bank tools

`questionbank-tools.py` is the portable source for the Studdy-only native
question-bank handlers. It deliberately does not expose a generic MCP route:
the native plugin owns this retrieval surface while the module's public MCP
server remains independent for a future release.

## Deployment

Copy `questionbank-tools.py` to `scripts/lib/questionbank-tools.py` below the
configured Hermes root. Register it from the Studdy plugin, then enable the
plugin and `question_bank.enabled` only in the Studdy profile configuration.
The handlers are unavailable in every profile where that flag is absent or
false.

The source file defaults to its owning module's `.venv/bin/question-search`
binary and `questions/` directory. A copied deployment must set these portable
paths in its service environment when the module is elsewhere:

```ini
QUESTION_SEARCH_BIN=/path/to/hermes-modules/modules/question-bank/.venv/bin/question-search
QUESTION_BANK_ROOT=/path/to/hermes-modules/modules/question-bank
```

The adapter removes inherited `PYTHONPATH` and `PYTHONHOME` before invoking the
module CLI. This prevents the Hermes gateway interpreter and question-bank
virtual environment from contaminating one another.

The tools are all read-only. `search-questions` uses `question-search query`,
`get-question` reads the source JSON object (including the answer key), and
`get-stats` uses `question-search status` plus read-only aggregation of the
optional `data/answers.jsonl` log.

Plugin manifest fragment:

```yaml
name: question-bank
provides_tools:
  - search-questions
  - get-question
  - get-stats
```
