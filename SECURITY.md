# Security policy

question-bank is a local tool: it stores questions as JSON files under
your bank root, keeps a local search index, and talks to one network
endpoint that you configure for LLM extraction (and optionally for
embedding queries). There is no telemetry and no hosted component.

## Reporting a vulnerability

Open a private security advisory through
[GitHub security advisories](https://github.com/marcosconci1/question-bank/security/advisories/new)
rather than a public issue. Include the version, the command you ran,
and what you expected to stay local.

The maintainer treats the following as security issues:

* Anything that sends file contents, page text, or bank structure
  anywhere other than the configured extraction or embedding endpoint.
* Anything that writes to the bank outside `question-bank ingest`.
* Anything that executes code from ingested question content.

A report that ingestion quarantined a record you expected to pass is a
normal issue, not a security report.
