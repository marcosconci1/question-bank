# Tasks

Each task is shippable and testable on its own. Tick a box only after verification.

## 0. Prepare (no behavior change)
- [ ] 0.1 Resolve the pending uncommitted edits in `modules/question-bank` (commit or drop). Tree must be clean.
- [ ] 0.2 Back up: tar of `modules/question-bank` (including `data/`, `assets/`, `questions/`) to `~/backups/question-bank/`.
- [ ] 0.3 Tag `hermes-modules` as `question-bank-pre-extract`.
- [ ] 0.4 Install `git-filter-repo` with `uv tool install`.

## 1. Move (engine repo + data split)
- [ ] 1.1 Create the bank directory and copy data into it: `questions/`, `assets/`, `corrections/`, `data/users/`, `reports/`, `docs/tags.md`, `sources/` (from `reports/concurso-sources.json`), `raw/`, owner extractor scripts.
- [ ] 1.2 Build the engine repo from history with data paths removed (`git filter-repo` on a fresh clone of `hermes-modules`). Verify with a scan: no `questions/`, `assets/`, `data/` in any commit.
- [ ] 1.3 Add one `resolve_bank_root()` used by the CLI, the MCP server, the Hermes plugin and the `record-answer` script. Add the `bank` pytest marker. Tests use synthetic fixtures.
- [ ] 1.4 Replace `question-search.sh` with the installed `qb`/`question-search` entry point. Document `uv tool install`.
- [ ] 1.5 Run the full suite in the engine repo. Run `bank`-marked tests against the owner's bank.
- [ ] 1.6 Create the private GitHub repo `question-bank` and push.
- [ ] 1.7 Flip the Study symlink, set `QUESTION_BANK_ROOT` and `QUESTION_SEARCH_BIN`, check the `question-bank-repair` skill path, smoke-test every plugin tool.
- [ ] 1.8 Owner restarts the gateway and starts `/new` in Study. Verify a real practice request.
- [ ] 1.9 (after owner confirms) Remove `modules/question-bank` from `hermes-modules`. Update its README, STATE.md, changelog.
- [ ] 1.10 Nightly silent backup of the bank directory to `~/backups/question-bank/`.

## 2a. Modularize (bring your own data)
- [ ] 2a.1 `qb` umbrella CLI: `init`, `validate`, `search`, `stats`, `mcp`, `doctor`. Keep `question-search` as alias.
- [ ] 2a.2 `qb init`: empty bank, starter tag registry, example CSV. `qb doctor` checks every prerequisite and names what is missing.
- [ ] 2a.3 `qb import` for CSV and JSON with validation, dedupe, and a rejects report.
- [ ] 2a.4 Dependency extras: `[import]` (pymupdf), `[semantic]` (qdrant-client), `[web]`. Base install small.
- [ ] 2a.5 README quick start: install, init, import, search, in under 5 commands. Test it on a clean machine/venv.

## 2b. Declarative PDF profiles (optional, can slip)
- [ ] 2b.1 Define the TOML profile schema and the small adapter interface.
- [ ] 2b.2 Port `concurso.py` rules into four example profiles without changing output. Golden test: re-import of the owner's sources gives byte-identical questions.
- [ ] 2b.3 Port POSCOMP and ENADE importers as example profiles.
- [ ] 2b.4 `qb import pdf --profile`.

## 3. Other CLIs
- [ ] 3.1 MCP parity: add `list-topics`, answer-safe practice view by default, solution view on request.
- [ ] 3.2 Claude Code plugin: `.claude-plugin/plugin.json`, `.mcp.json` using `uvx`, shared `skills/`. Test with `claude --plugin-dir`.
- [ ] 3.3 Codex: `codex mcp add` instructions, config snippet, `AGENTS.md` section, skills layout. Test with a real Codex session.
- [ ] 3.4 Contract test per client that the tool list and schemas match.
- [ ] 3.5 Docs: one page per client.

## Close
- [ ] Archive this change, update `~/STATE.md` and `~/changelog/`.
