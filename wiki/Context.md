# Context

## Situation

The material for studying any exam arrives the same way: past papers as
PDFs, question dumps as spreadsheets, answer keys in separate files. A
serious study session needs those questions in one place, searchable by
topic, with answers attached.

## Complication

Turning that material into a bank is manual work with no memory. Each
source speaks its own layout: one board prints options as (A) through
(E) across columns, another uses answer matrices, a CSV dump invents
its own column names. Copying questions by hand is slow and throws
away the source. Scripted importers exist but are bound to one format:
each new exam means writing a new importer from zero, and every import
is trusted blindly. When an answer in the bank looks wrong, nothing in
the record says where the question came from or how it was extracted,
so there is nothing to check it against.

## Resolution

question-bank replaces per-format importers with one pipeline and
pluggable adapters. Sources are declared in a manifest with a free-form
exam slug; CSV files map through column definitions, supported
exam-board PDFs go through deterministic parsers, and any other PDF
with a text layer goes through a language-model adapter that extracts
under a strict schema and gets one bounded repair attempt before a
batch is quarantined. Every candidate passes the same structural
validation before it lands in the bank, and every record carries its
source, location, and adapter. Failure is explicit: quarantined
batches are journaled with reasons, and the LLM adapter accounts for every page it reads.

## What this system refuses to do

* No OCR: scanned PDFs without a text layer are refused.
* No invented content: the model adapter extracts what the page says
  and quarantines what it cannot parse.
* No silent drops: validation failures and unreadable batches are
  journaled with reasons.
* No writes outside ingest: search and query commands read the bank
  and never modify it.
* No telemetry: nothing leaves the machine except text you
  deliberately send to the extraction or embedding endpoint.
