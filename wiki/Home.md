# question-bank

> Store, validate, and search exam questions locally. Ingest from CSV files, exam-board PDFs, or any PDF with a text layer, with provenance on every question.

Studying from past exams means the material arrives as PDFs and
spreadsheets, not as data. A question lives on page 14 of a booklet, its
answer on page 40 of another file, and the connection between them
exists only in the reader's head. Copying questions by hand into
flashcard tools loses the source, and a bank without provenance cannot
be audited: when an answer looks wrong, there is nothing to check it
against.

question-bank turns source files into a validated bank in one pass. The
`ingest` command reads a manifest of sources and runs each through an
adapter: CSV files map through column definitions, exam-board PDFs go
through deterministic parsers, and any other PDF with a text layer goes
to a language model that extracts candidates page batch by page batch
under a strict schema with one bounded repair attempt. Every candidate
then passes the same structural validation; clean records land in the
bank as JSON with their source, page range, and adapter recorded, and
anything the pipeline cannot trust lands in a quarantine journal with
the reason attached.

The result is a bank you can search, audit, and grow across exams.
`question-search` ranks questions locally with keyword scoring that
needs no API key, or semantically through your own embedding endpoint.
Every page the PDF adapters touch is accounted for: extracted, empty,
or quarantined, nothing dropped silently. What the tool does not do is
invent content: scanned PDFs without a text layer are refused, and the
model adapter extracts what is on the page rather than guessing what
should be there.

## Map

| Page | What it covers |
| --- | --- |
| [[Context]] | The situation, the complication, the resolution, and what the system refuses to do |
| [[Architecture]] | The pipeline stage by stage, and the design decisions behind each one |
