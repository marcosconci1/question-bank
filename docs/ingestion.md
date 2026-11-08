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
| `kind` | Adapter kind: `csv`, `pdf-board`, or `pdf-llm`. |
| `path` | Path to the source file, relative to the manifest. |
| `exam` | Exam slug. It is normalized to lowercase and is not restricted to a list of known exams. |
| `year` | Integer exam year. |
| `options` | Optional object containing adapter-specific configuration. |

`csv` reads structured question records from a CSV file. By default, it reads `id`, `stem`, `number`, `options`, and `answer` columns, and derives tags from `knowledge_area`, `area`, and `subarea`. Set `options_columns` to name separate option columns, or set `options_column` for a column containing a Python or JSON list of strings. Column names, ID prefix, source text template, type, status, and tag columns can be configured in `options`.

`pdf-board` parses exam booklets and answer keys using the existing board parser. Its `options` must include `banca`, `organ`, `role`, and `caderno`. This adapter currently supports the `fgv`, `iades`, `cesgranrio`, and `fcpc` board formats. An answer key can be supplied with `gabarito_path` or `answer_key_path`; related settings include `gabarito_kind`, `prova_url`, `prova_sha256`, `gabarito_url`, and `gabarito_sha256`.

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
      "banca": "fgv",
      "organ": "sample-organization",
      "role": "analyst",
      "caderno": "type-1",
      "gabarito_path": "fgv-sample-answer-key.pdf",
      "gabarito_kind": "definitivo"
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

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `QUESTION_BANK_ROOT` | Overrides the bank directory used to find the default manifest and write question and report files. | `$XDG_DATA_HOME/question-bank`, or `~/.local/share/question-bank` when `XDG_DATA_HOME` is unset. |
| `QUESTION_EXTRACT_MODEL` | Model name used by the PDF LLM adapter. | `openai/gpt-4o-mini` |
| `OPENROUTER_API_KEY` | API credential required for live PDF LLM requests. | No default; required when using the live API. |
