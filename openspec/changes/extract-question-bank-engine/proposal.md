# Extract question-bank into its own engine repo

Status: PLAN ONLY. Nothing has been moved, deleted, or published.

## Why

question-bank started as one folder inside the `hermes-modules` monorepo. It now holds three different things:

1. An engine: validator, importer pipeline, corrections overlay, answer log, BM25/semantic search, MCP server.
2. Integrations: a Hermes plugin with skills (Study uses it daily).
3. Data: 1,589 questions, 12 MB of figure crops, raw PDFs, corrections, per-user answer history.

Mixing them blocks three goals:

- Reuse by other people: a stranger needs the engine, not the owner's exam data.
- Use from other agent CLIs (Claude Code, Codex), not only Hermes.
- Safe publishing: question text is third-party copyright and must never ship in the engine repo.

## Decisions already made (grilling rounds, 2026-11-02)

| # | Decision |
|---|----------|
| Q1 | Engine repo holds code only. Data is never committed to the engine repo. |
| Q2 | `qb init` and `qb import` for new users. Install with `uv tool install` or `uvx`. |
| Q3 | MCP-first for other CLIs. One MCP server; thin Claude Code plugin and Codex config on top. |
| Q4 | `.gitignore` keeps data out of git. Data lives in a plain directory outside the repo. A nightly copy goes to `~/backups/`. No separate git repo for data. |
| Q5 | The repo, the Hermes plugin, the MCP server and the CLI are all named `question-bank`. The CLI binary is `qb`. `question-search` stays as an alias. |
| Q6 | Viability study and plan first. Then phased work, each phase verified before the next. |

Publishing is parked. This change makes the project clean for the owner first.

## Scope

In scope: new repo, data split, Hermes re-link, removal from `hermes-modules`, user bank bootstrap (`qb init`, `qb import`), MCP parity, Claude Code and Codex packaging.

Out of scope: public release, license choice, a hosted service, new exam sources.

## Non-goals

- No change to the data model, the status lifecycle, or the corrections overlay rules.
- No requirement for `OPENROUTER_API_KEY`, Qdrant, or any network service for core use.
