# Architecture

The pipeline is one command with pluggable adapters behind a single
interface. This page walks the stages and the decisions behind each
one, with a diagram per stage.

## Stage 1: dispatch

The manifest declares every source with a `kind`; the dispatcher picks
the matching adapter and yields candidates. Adapters produce
candidates, never writes: only the pipeline persists anything, so no
code path exists from an adapter to the questions directory.

```mermaid
graph LR
  M[sources.json] --> K{kind}
  K -->|csv| C[CSV adapter]
  K -->|pdf-board| B[Board adapter]
  K -->|pdf-llm| L[LLM adapter]
  C --> V
  B --> V
  L --> V
  V[Structural validation]
```

**Exam identity is a slug, not a list.** The manifest declares each
source with a free-form `exam` slug and validation applies only two
kinds of rules: structural rules that every question must pass, and
exam-specific rules that fire only when the record belongs to a known
exam. The why: the tool must take any exam, and gating specific rules
by exam means supporting a new exam requires zero code changes.

## Stage 2: extract (LLM adapter)

Only the LLM adapter talks to a model, and it talks to it in batches
under a strict schema. A batch that comes back unparsable gets exactly
one repair call, with the validator error attached; a batch that still
fails is quarantined and the pipeline moves on.

```mermaid
sequenceDiagram
  participant P as Pipeline
  participant A as LLM adapter
  participant E as Extraction endpoint
  P->>A: page batch
  A->>E: extract prompt (schema)
  E-->>A: candidates JSON
  A->>A: parse under schema
  alt parses
    A-->>P: candidates + page provenance
  else fails
    A->>E: repair prompt (validator error)
    E-->>A: candidates JSON
    alt parses
      A-->>P: candidates + page provenance
    else fails
      A-->>P: quarantine batch + reason
    end
  end
```

## Stage 3: validation and landing

Every candidate from every adapter passes the same structural
validation, then takes exactly one of two exits. A question id already
in the bank is skipped, which makes re-runs safe.

```mermaid
stateDiagram-v2
  [*] --> candidate
  candidate --> validating: adapter yields
  validating --> landed: schema and rules pass
  validating --> quarantined: invalid id, validator error, unparsable batch
  landed --> written: questions/ JSON with provenance
  written --> [*]
  quarantined --> logged: quarantine journal with reason
  logged --> [*]
```

**Failure is a record, not an exit.** One unreadable page in a 60-page
booklet should cost one batch, not the whole ingest run. Each rejection
lands in the quarantine journal with source, candidate, and reason
attached.

**Every page is accounted for.** The LLM adapter tracks each page as
extracted, empty, or quarantined, and stamps each candidate with the
page range it came from, the adapter name, and the model used. The why:
provenance is what makes a bank auditable, and page accounting makes
silent drops impossible by construction.

## What lands on disk

The bank root is a plain directory of JSON and logs, relocatable with
`QUESTION_BANK_ROOT`:

```mermaid
graph TD
  B[bank root] --> Q[questions/ .json records with source, pages, adapter]
  B --> R[reports/]
  R --> MA[manifest.json declared sources]
  R --> QA[ingest-quarantine.jsonl rejected candidates + reasons]
  R --> EV[events.jsonl local event journal]
  B --> I[index/ search index ledger and vector store]
```

**Idempotence is built in.** Running the same ingest twice produces
identical bank files: already-present question ids are skipped, and
quarantine records append, never rewrite. The why: an ingest command
that is safe to re-run needs no state management around crashes and
retries.

**Diagnostics are local and always on.** The event journal records
ingest and doctor activity with secrets scrubbed on write, trims
itself to 30 days and 1 MB, and `diagnose` renders a redacted bundle
for bug reports. It never opens a network connection. The why: a local
tool should be debuggable from local evidence alone.

It never writes to the bank outside ingest. It never drops a candidate
silently. It never reads a scanned page it cannot see. It never sends
bank content anywhere except the endpoints you configure.
