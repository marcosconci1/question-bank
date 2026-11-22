# Generic question ingestion

The `question-bank ingest` command loads configured sources for any exam slug. A source declares its exam, year, input file, adapter kind, and adapter options in a JSON manifest named `sources.json`. The default manifest is `reports/sources.json` under the bank root. Paths in the manifest are resolved relative to the manifest file.

## Command

```bash
uv run question-bank ingest
uv run question-bank ingest --manifest /path/to/sources.json
uv run question-bank ingest --source sat-math-2025
uv run question-bank ingest --dry-run
uv run question-bank ingest --json
```

The command accepts these options:

| Option | Purpose |
| --- | --- |
| `--manifest PATH` | Use a specific `sources.json` file. By default, use `reports/sources.json` under the bank root. |
| `--source ID` | Process only the source with this manifest `id`. |
| `--dry-run` | Validate candidates and report counts without writing questions or quarantine records. |
| `--json` | Print the ingestion summary as JSON. |

The summary reports ingested, skipped, and quarantined question counts. Existing question IDs and duplicate IDs in a run are skipped.

## Manifest

The manifest is a JSON array. Each entry has these required fields:

| Field | Description |
| --- | --- |
| `id` | Unique identifier for this source entry. |
| `kind` | Adapter kind: `csv`, `json`, `pdf-board`, or `pdf-llm`. |
| `path` | Path to the source file, relative to the manifest. |
| `exam` | Exam slug. It is normalized to lowercase and is not restricted to a list of known exams. |
| `year` | Integer exam year. |
| `options` | Optional object containing adapter-specific configuration. |

`csv` reads structured question records from a CSV file. By default, it reads `id`, `stem`, `number`, `options`, and `answer` columns, and derives tags from `knowledge_area`, `area`, and `subarea`. Set `options_columns` to name separate option columns, or set `options_column` for a column containing a Python or JSON list of strings. Column names, ID prefix, source text template, type, status, and tag columns can be configured in `options`.

`pdf-board` parses Brazilian public-sector exam booklets and answer keys. Its `options` must include `board`, `agency`, `role`, and `booklet`. Supported board formats are `fgv`, `iades`, `cesgranrio`, and `fcpc`. Set `answer_key_path` to the answer-key PDF and supply the official source URLs and SHA-256 digests with `booklet_url`, `booklet_sha256`, `answer_key_url`, and `answer_key_sha256`. Set `answer_key_kind` to `final` (the default) or `preliminary`. Questions with a preliminary answer key are suspended. Existing manifests continue to work.

`pdf-llm` extracts multiple-choice questions from PDFs that contain a text layer. Its optional `batch_pages` setting controls the number of pages sent in each extraction request and defaults to 4. Other options, such as `tags`, can be supplied in the same object.

Example manifest:

```json
[
  {
    "id": "sat-math-2025",
    "kind": "csv",
    "path": "sat-math-2025.csv",
    "exam": "sat-math",
    "year": 2025,
    "options": {
      "id_column": "question_id",
      "stem_column": "question",
      "options_columns": ["A", "B", "C", "D"],
      "answer_column": "correct_answer",
      "number_column": "number",
      "tags_columns": ["topic"]
    }
  },
  {
    "id": "fgv-sample-booklet-2025",
    "kind": "pdf-board",
    "path": "fgv-sample-booklet.pdf",
    "exam": "fgv",
    "year": 2025,
    "options": {
      "board": "fgv",
      "agency": "TRF1",
      "role": "analyst",
      "booklet": "Tipo 1",
      "answer_key_path": "fgv-sample-answer-key.pdf",
      "answer_key_kind": "final"
    }
  }
]
```

## Pipeline and provenance

An adapter reads a configured source and yields candidate records. The shared pipeline then validates each candidate against the question structure and registered tags. Valid candidates are written as question JSON files under `questions/`. Invalid candidates are quarantined in `reports/ingest-quarantine.jsonl` with a reason. Candidates rejected by an adapter are also quarantined with their adapter-provided reason. Dry runs perform validation without writing either destination.

Every written question includes a `provenance` object. CSV provenance records the source ID, source filename, and CSV row. PDF LLM provenance records the source ID, adapter, extraction model, and page range. The board adapter records source and answer-key metadata, including available URLs and checksums.

## PDF LLM behavior

The PDF LLM adapter groups pages according to `options.batch_pages`, which defaults to 4. Each batch is sent with temperature 0 and must return strict JSON matching the extraction schema. If the response is invalid, the adapter makes one repair attempt for that batch. A batch that remains invalid is quarantined as a unit with its page range and failure reason; other batches continue independently.

The adapter keeps page accounting for each processed page, with outcomes such as yielded candidate, empty, or quarantined. A PDF must provide selectable text for extraction. Scanned pages without a text layer yield no question candidates; OCR is not performed. Use a text-layer PDF for this adapter.

## Direct imports and TOML profiles

For one-off imports without writing a manifest, use `qb import`:

```bash
uv run qb import questions.csv --exam my-exam --year 2025
uv run qb import questions.json --exam my-exam --year 2025 --rejects rejects.jsonl
```

For a board PDF import, set `BOOKLET_URL` and `ANSWER_KEY_URL` to the official source URLs and pass the role and booklet labels as printed in the source documents. `qb import` computes the local PDFs' SHA-256 digests when you omit them.

```bash
uv run --extra import qb import pdf booklet.pdf --profile fgv --year 2024 \
  --agency TRF1 --role 'Técnico Judiciário TI' --booklet 'Tipo 1' \
  --answer-key answer-key.pdf --booklet-url "$BOOKLET_URL" --answer-key-url "$ANSWER_KEY_URL"
```

Example declarative profiles live under `profiles/examples/` (`fgv`, `iades`, `cesgranrio`, `fcpc`, `poscomp`, `enade`). Each TOML file declares `name`, `kind`, `exam`, and an `[options]` table passed to the matching adapter; custom `.toml` paths can be passed directly to `--profile`.

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `QUESTION_BANK_ROOT` | Overrides the bank directory used to find the default manifest and write question and report files. | `$XDG_DATA_HOME/question-bank`, or `~/.local/share/question-bank` when `XDG_DATA_HOME` is unset. |
| `QUESTION_EXTRACT_MODEL` | Model name used by the PDF LLM adapter. | `openai/gpt-4o-mini` |
| `OPENROUTER_API_KEY` | API credential required for live PDF LLM requests. | No default; required when using the live API. |
