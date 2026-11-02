# Design and viability study

Verdict: **viable, medium effort, low risk if done in phases.** The module is already closer to a clean split than expected. The hard part is Phase 2b (declarative PDF profiles), and it can slip without blocking the rest.

## 1. What is already in our favor

- `QUESTION_BANK_ROOT` already exists in `question_search/config.py`, the Hermes `tools.py`, and `record-answer.py`. The bank root is mostly a parameter.
- `answers.py`, `corrections.py`, and `mcp_server.py` already take `root` as an argument.
- An MCP server (`question-bank-mcp`) already exists.
- Search works with no key: BM25 is the default, semantic search is optional.
- Study already reads the bank through `QUESTION_BANK_ROOT`, so changing the data location is an env change.
- The Hermes plugin presents questions answer-safe (it pops `answer` in practice view).

## 2. Coupling inventory (what breaks if we just move the folder)

| Item | Problem | Fix |
|------|---------|-----|
| `tools.py` `ROOT = parents[3]` | Default bank root is "the repo". After the split the repo has no data. | Default to `QUESTION_BANK_ROOT`, then `$XDG_DATA_HOME/question-bank`. Fail with a clear message if missing. |
| `question_search/config.py` `REPO_ROOT` | Same default. | Same fix, one shared `resolve_bank_root()` function. |
| `question-search.sh` launcher | Uses `uv run --directory <module>`. Path breaks on move. | Replace with the installed `qb` entry point. Study `.env` `QUESTION_SEARCH_BIN` points at it. |
| 5 test files read real data (`test-corrections`, `test-enade-adapter`, `test-enade-full-report`, `test-question-practice`, `test-web`) | Engine repo will not have data. | Engine tests use small synthetic fixtures. Real-data checks become a `bank` pytest marker, skipped when no bank is present, runnable against the owner's bank. |
| `scripts/extract-enade-*.py`, `fetch-enade-cc.py`, `import-enade-reports.py` | Contain hand-typed question text and hand-tuned crops. This is data in disguise. | Move to the data directory (`bank/scripts/`). Not in the engine repo. |
| `scripts/import-concurso.py`, `import-poscomp.py`, `adapters/` | Reusable logic, but paths are repo-relative. | Become `qb import` subcommands. Parameterized by bank root. |
| `concurso.py` (1.3k lines) | Per-board rules (headers, footers, option format, answer-key layout) are hardcoded. | See Phase 2b. |
| `docs/*.png|d2|mmd` | Project design artifacts. | Stay in the engine repo under `docs/`. Anything quoting exam text stays out. |
| `web/`, `docker/` | Optional Starlette UI, Qdrant compose. | Keep as optional extra (`[web]`). Qdrant stays optional. |
| Heavy dependencies | `pymupdf` and `qdrant-client` are hard dependencies today. | Extras: `[import]` for pymupdf, `[semantic]` for qdrant-client. Base install is small. |
| Uncommitted edits in the module | Another session left pending changes (`pyproject.toml` dev group, `uv.lock`, `tools.py` launcher default, README text, untracked `question-search.sh`). | Resolve first (commit or drop) so the extraction starts from a clean tree. |

## 3. Parity gaps for other CLIs

- The Hermes plugin has 4 tools: `search-questions`, `get-question`, `list-topics`, `get-stats`. The MCP server has 3 and lacks `list-topics`.
- MCP `get-question` returns the answer key. The Hermes plugin has practice and solution views. A tutor in Claude or Codex needs the same answer-safe default.
- Corrections and the answer log are applied/written the same way in both paths (same module). Keep one implementation.
- Skills (`question-practice`, `exercise-list`) are plain `SKILL.md` files. Claude Code and Codex both read this format, so one skills directory can serve all three. Verify at build time.

## 4. Target layout

```
question-bank/                 # engine repo (code only)
  src/question_bank/           # model, validate, corrections, answers, importers
  src/question_search/         # BM25, optional semantic
  src/qb/                      # CLI: init, import, validate, search, stats, mcp, doctor
  integrations/
    hermes/question-bank/      # Hermes plugin (thin adapter)
    claude/                    # .claude-plugin/plugin.json, .mcp.json, skills/
    codex/                     # config snippet, AGENTS.md section
  skills/                      # shared SKILL.md files
  profiles/examples/           # TOML board profiles (no exam text)
  tests/                       # synthetic fixtures only
  docs/

~/.local/share/question-bank/  # bank (data, never in the repo); QUESTION_BANK_ROOT overrides
  questions/ assets/ corrections/log.jsonl data/users/*/answers.jsonl
  sources/manifest.json  raw/  reports/  docs/tags.md  scripts/  # owner's own extractors
```

## 5. User journey (new user)

1. Install: `uv tool install git+<repo>` (or `uvx --from git+<repo> qb ...`). Needs Python 3.12+ and uv.
2. `qb init` creates an empty bank and a starter tag registry, and runs `qb doctor` checks.
3. `qb import questions.csv` (or `.json`) loads structured questions. First search works in minutes.
4. `qb search "hash table"` and `qb stats` work with no key and no services.
5. `qb mcp` serves the bank to any MCP client. Claude Code: install the plugin. Codex: `codex mcp add question-bank -- uvx ... qb mcp`.
6. For PDFs: `qb import pdf --profile <name> prova.pdf gabarito.pdf` (Phase 2b).

Failure modes to cover in `doctor`: wrong Python version, bank root missing or unwritable, bank has invalid questions, optional extras not installed (named, with install command), Qdrant unreachable (falls back to BM25).

## 6. Data safety (Q4)

- Engine repo `.gitignore` ignores `bank/`, `data/`, `questions/`, `assets/`, `reports/`, `*.pdf` as a guard if someone inits inside the repo.
- The history of the engine repo is rebuilt without data paths (see tasks 1.2). A `git filter-repo` run is needed; it is not installed yet (`uv tool install git-filter-repo`).
- The corrections log and the answer log are append-only JSONL, so the file itself is its own history. That is why a separate git repo for data is not worth it.
- Irreplaceable files: `data/users/*/answers.jsonl`, `corrections/log.jsonl`, hand-cropped ENADE figures in `assets/`, and the ENADE questions that came from hand-typed prompts. A nightly silent copy to `~/backups/question-bank/` covers them. Restore is a directory copy.
- Before anything moves: tar backup of the whole module and a git tag in `hermes-modules`.

## 7. Hermes re-link (Study)

Study loads the plugin through a symlink `profiles/study/plugins/question-bank -> .../hermes-modules/modules/question-bank/integrations/hermes/question-bank`. The config name `question-bank` does not change.

1. Install the new repo and verify it with the owner's bank (tests and a plugin smoke test).
2. Flip the symlink to the new repo path. Set `QUESTION_BANK_ROOT` and `QUESTION_SEARCH_BIN` in the study profile `.env`.
3. Restart the gateway (the owner does this; it cannot run from inside the gateway). Start a fresh Study session (`/new`) so skills reload.
4. Rollback is flipping the symlink back and restoring the two env values.

The Study skill `question-bank-repair` (in the study profile) writes to `corrections/log.jsonl`. Its path must follow `QUESTION_BANK_ROOT` after the split. Checked in Phase 1.

## 8. Phase 2b: declarative PDF profiles (the real risk)

Parsing differs a lot per board. Header and footer noise lists, option markers (`(A)` vs `A)`), question numbering, and answer-key layout are the main variation. A TOML profile can express the common knobs: noise patterns, option regex, number style, expected option count, section markers. Answer-key parsing varies too much to be fully declarative, so the design keeps a small Python adapter interface (`parse_exam`, `parse_key`) and lets a profile pick built-in parsers and set knobs. Our four boards and ENADE/POSCOMP ship as example profiles with no data.

Risk: medium. Mitigation: ship Phase 2a (CSV/JSON import and `init`) first. It already gives a stranger a working bank, and 2b can be done later or cut.

## 9. Phases and rollback

| Phase | Result | Rollback |
|-------|--------|----------|
| 0 | Clean tree, backup, git tag | Nothing changed yet |
| 1 | Engine repo exists, data in the bank dir, Study works from the new location. Old copy still in `hermes-modules`. | Flip symlink and env back |
| 1b | Old copy removed from `hermes-modules` (only after the owner confirms Study works) | Restore from tag/tar |
| 2a | `qb` CLI, `init`, `doctor`, CSV/JSON import, extras split | Revert commits in engine repo |
| 2b | TOML PDF profiles | Optional; skip if too costly |
| 3 | MCP parity, Claude Code plugin, Codex config | Independent of Hermes |

Each worker task commits after every step (30-minute worker limit). Independent verification after each phase: full test suite, plugin smoke test against the real bank, and a check that Study still answers a practice request.

## 10. Open items for the owner

- Repo location on GitHub (private for now) and owner account.
- OK to run `uv tool install git-filter-repo`.
- Confirm "delete the one in hermes-modules" means the original module folder (assumed), executed only at Phase 1b.
