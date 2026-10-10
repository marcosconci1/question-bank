# Question Schema v2

One JSON file per question in `questions/`. The bank is the project; this
schema is its contract. Every ingestion source (POSCOMP, ENADE, future ones)
normalizes into this shape.

Question content (stems, options, tags of exam origin) is in Portuguese —
that is the data, transcribed from Brazilian exams. Everything system-side
(field names, ids, docs, code) is English.

## v2 change: content blocks (2026-09-23)

v1 had `stem: string` + a flat `attachments` list. That cannot represent
how real exam questions are laid out: text, then an image, then more text;
an image inside an option; an image-only stem. v2 replaces the string stem
with an **ordered array of typed content blocks**, everywhere content
appears (stem, every option, context, rubric).

Decision (researched): this is the converged answer of QTI (itemBody =
ordered mixed content, images allowed inside choices), DocBook
(mediaobject/inlinemediaobject), and the INEP-family parsers (ENEM parser
extracts per-question PNGs into JSON). HTML-with-inline-img (Moodle style)
was rejected: the bank must stay greppable pure data, not opaque markup.

Block types:

- `text` — plain text. **Math stays inline inside text blocks as LaTeX**
  (`$...$`), because 531 POSCOMP questions carry math markers inline with
  prose; separating them would shatter sentences into fragments.
- `image` — `src` path under `assets/` (paths, never blobs), `alt` text
  mandatory for accessibility.

## Design decisions

1. **Superset over POSCOMP.** The 1,306 imported POSCOMP files remain valid
   instances: a bare string is accepted as shorthand for a one-text-block
   list, so v1 files validate unchanged. The canonical form is the block
   array; the normalizer canonicalizes on any future rewrite.
2. **Two question types, nothing more.** `mc` (graded by letter) and
   `discursive` (self-assessed against a rubric). `true-false` stays an MC
   variant, never its own type.
3. **Shared case text lives once** in `contexts/<id>.json`; questions
   reference it. Context bodies use the same block model.
4. **Images are first-class** as image blocks with asset paths. The flat
   `attachments` field is superseded by image blocks in place (kept
   temporarily as read-only legacy; the validator flags files that carry
   both).
5. **Tags are a flat list of slugs**, hierarchy derivable from the
   registry, not encoded per file.
6. **`source` is mandatory.** No provenance, no question.
7. **Blocks are structural, not cosmetic.** Every content field uses them,
   so the renderer (CLI now, anything later) has exactly one rendering
   rule per block type and zero per-source special cases.

## Schema

```jsonc
{
  "id": "poscomp-2022-67",            // "<exam>-<year>-<number>", unique, filename = id + ".json"
  "type": "mc",                       // "mc" | "discursive"          (required)
  "exam": "poscomp",                  // "poscomp" | "enade"          (required)
  "year": 2022,                       // exam year                    (required)
  "number": 67,                       // number in the exam           (required)
  "component": null,                  // ENADE only: "general-education" | "specific"
  "course": null,                     // ENADE only: e.g. "computer-science"
  "stem": [                           // content blocks (required)    (required)
    {"type": "text",  "content": "Considere o circuito lógico abaixo:"},
    {"type": "image", "src": "assets/poscomp-2019-12-fig1.png", "alt": "circuito com portas AND e OR"},
    {"type": "text",  "content": "Qual expressão representa a saída $X$?"}
  ],
  "context": null,                    // id of a file in contexts/, if the stem depends on shared text
  "options": [                        // mc only, 2–5, order = A,B,C,…; each option is a block list
    [{"type": "text", "content": "$f$ é injetora mas não sobrejetora;"}],
    [{"type": "image", "src": "assets/poscomp-2022-68-altB.png", "alt": "grafo dirigido"}]
  ],
  "answer": "A",                      // mc only: letter within options range
  "rubric": null,                     // discursive only: block list (expected answer / grading rubric)
  "attachments": [],                  // LEGACY (read-only): superseded by image blocks; validator flags files using it alongside image blocks
  "source": "POSCOMP 2022, question 67",  // human-readable provenance (required)
  "tags": ["tecnologia-de-computacao", "banco-de-dados"]  // slugged, ≥1
}
```

## Block model rules

- A content field is **either** a plain string (shorthand for one text
  block — the v1 form, still valid) **or** an array of blocks.
- Block: `{"type": "text", "content": "…"}` or
  `{"type": "image", "src": "assets/…", "alt": "…"}`.
- `text` content may embed LaTeX inline (`$…$` / `\(…\)`) — math is not a
  separate block type.
- `image.src` is a repo-relative path; binaries live under `assets/`.
  `alt` is mandatory (accessibility + greppable description).
- Blocks appear **in document order**; the renderer preserves order. This
  is what encodes the text-1 / image / text-2 permutations the schema must
  represent.
- Every block-bearing field allows the same two block types (stem, each
  option, context body, rubric). No per-field exceptions.
- Empty content fields are invalid (an empty stem or an empty option
  string is a capture bug).

## Field rules

- `mc`: `options` (2–5) and `answer` required; `rubric` forbidden.
- `discursive`: `options` and `answer` forbidden; `rubric` required
  (official resolution or an explicit expectation note; self-graded in the
  runner).
- `context` references `contexts/<id>.json` — never inline the case text.
- `tags`: knowledge-area tags when the source has them (POSCOMP's three
  levels), free-form slugs when it doesn't (ENADE). The tag taxonomy lives
  in `docs/tags.md` once ENADE import forces merges.
- `attachments` (legacy): paths only; being replaced by image blocks. New
  files must not use it.

## Validation

`scripts/validate-questions.py` (TODO, small): checks every file against
these rules, including: block-shape validation (types, mandatory `alt`),
answer-in-range, tag-registry membership, image paths resolving under
`assets/`, and the legacy `attachments` conflict check.
