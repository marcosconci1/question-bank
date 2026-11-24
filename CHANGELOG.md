# Changelog

## 0.2.0

- Added direct CSV, JSON/JSONL, and PDF imports with TOML profiles, including packaged built-in profiles and bank-local tag registry overrides.
- Added the `qb` alias and `init`, `import`, `validate`, `search`, `stats`, and `mcp` commands.
- Added MCP practice and solution views, keyless lexical search, per-year topic counts, and the web Topics screen.
- Added Claude Code and Codex integrations, question correction overlays, and discursive rubric reveal before self-grading.
- The Hermes integration version now follows the common 0.2.0 release numbering.
- Fixed browser profile initialization and tag registry fallbacks in the web and Hermes integrations.
- Answer history now defaults to the `default` user across engine, Hermes, and
  bundled recorders. Existing histories are untouched; set `QUESTION_BANK_USER`
  to a prior username to keep selecting it. No history is auto-selected,
  migrated, copied, merged, rewritten, or deleted.

## Initial public release

First public version of question-bank: a local engine for storing,
validating, and searching exam questions. `question-bank ingest` runs
declared sources through pluggable adapters: a generic CSV adapter for
tabular question dumps, a deterministic adapter for the supported
exam-board PDF formats, and a language-model adapter for any PDF with a
text layer. Every candidate passes structural validation; failures land
in the quarantine journal with a reason, and every question carries its
source, pages, and provenance. `question-search index` and
`question-search query "<question>"` provide local retrieval.
