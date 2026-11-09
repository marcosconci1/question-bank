# Changelog

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
