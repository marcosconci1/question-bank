# Design: add-concurso-ti-ingestion

## Identifier and Deduplication Contract

Concurso examinations frequently publish multiple booklet variants (`Tipo 1`, `Tipo 2`, etc.) or share common IT questions across several specialist roles (`Analista de TI - Desenvolvimento`, `Analista de TI - Infraestrutura`, `Técnico Judiciário - TI`) within the same selection process.

1. **Canonical ID format**:
   `<banca>-<organ>-<year>-<role_slug>-q<number:02d>` (or `<banca>-<organ>-<year>-<number>` when a single IT role/booklet exists), where all components use lowercase kebab-case ASCII slugs.
2. **Cross-caderno and cross-role deduplication**:
   - Candidate questions within the same `(banca, organ, year)` are fingerprinted using accent-folded, whitespace-normalized stem text plus sorted normalized option texts.
   - When two or more booklets or roles contain the same question (even if question numbers or option permutations differ), the importer emits a single canonical record (ordered deterministically by `(role_slug, caderno_slug, number)`) and merges all matching roles into `provenance.roles`, all booklets into `provenance.cadernos`, and all per-booklet occurrences into `provenance.occurrences`.

## Provenance Schema for Concurso Records

Every question with `exam` in `{"fgv", "iades", "cesgranrio", "fcpc"}` carries a required `provenance` object:

```json
{
  "banca": "fgv",
  "organ": "TRF1",
  "role": "Técnico Judiciário - Área Apoio Especializado - Especialidade: Tecnologia da Informação",
  "roles": [
    "Técnico Judiciário - Área Apoio Especializado - Especialidade: Tecnologia da Informação"
  ],
  "year": 2024,
  "exam_date": "2024-09-29",
  "caderno": "Tipo 1 - Branca",
  "cadernos": ["Tipo 1 - Branca"],
  "gabarito_kind": "definitivo",
  "prova_url": "https://conhecimento.fgv.br/sites/default/files/concursos/50.pdf",
  "prova_sha256": "<64-char lowercase hex>",
  "gabarito_url": "https://conhecimento.fgv.br/sites/default/files/concursos/...",
  "gabarito_sha256": "<64-char lowercase hex>",
  "sources": [
    {
      "kind": "prova",
      "url": "https://conhecimento.fgv.br/sites/default/files/concursos/50.pdf",
      "sha256": "<64-char lowercase hex>"
    },
    {
      "kind": "definitivo",
      "url": "https://conhecimento.fgv.br/sites/default/files/concursos/...",
      "sha256": "<64-char lowercase hex>"
    }
  ]
}
```

## Four-Gate Confidence Pipeline

A candidate question extracted from an official PDF is imported as `status: "active"` only when all four gates succeed:

1. **Gate 1 — Clean Structural Extraction**:
   - Question number (`1..100`), non-empty stem (`>= 40` chars, no mid-sentence truncation unless colon/lead-in to options), and exactly 4 (`A-D`) or 5 (`A-E`) non-empty options in strict alphabetical order.
   - Zero leaked PDF operator strings (`BT`, `ET`, `Tm`, `Tf`, `/F1`, `obj`, `endobj`) and zero page headers/footers inside stem or option text.
   - Items depending on unextracted visual figures/tables in stem or options without verified cropped image blocks fail Gate 1 and are routed to quarantine.
2. **Gate 2 — Official Answer Key Resolution**:
   - The official answer key for the exact booklet/role maps the question number to a valid letter within the option range (`A-D` for 4-option items, `A-E` for 5-option items).
   - Officially annulled items (`*`, `X`, `ANULADA`, `NULA`) are excluded (logged as `annulled`, never imported).
   - If only a preliminary answer key (`preliminar`) is available from the official source, the record is imported with `status: "suspended"` and `status_reason: "preliminary_answer_key"`.
3. **Gate 3 — Explainable Topic Classification**:
   - Deterministic rule-based matcher over normalized stem + options assigns at least one in-scope registered tag from `docs/tags.md` together with its parent topic and area tags (`fundamentos-da-computacao` or `tecnologia-de-computacao`, `algoritmos-e-estrutura-de-dados` or `banco-de-dados` or `organizacao-de-arquivos-e-dados`).
   - Core rules cover B-trees (`arvore-b`), B+ trees (`arvore-b-mais`), AVL trees (`arvore-avl`), red-black trees (`arvore-rubro-negra`), general trees/BST (`arvores-e-suas-generalizacoes-...`), hash tables (`tabelas-hash`), hash chaining (`hash-encadeamento`), open addressing (`hash-enderecamento-aberto`), database indexes (`indices-banco-de-dados`), priority queues/heaps (`heap-fila-de-prioridade`), linear structures (`estruturas-de-dados-lineares-...`), sorting/searching (`algoritmos-para-pesquisa-e-ordenacao`), graphs (`algoritmos-em-grafos`, `busca-em-largura-e-profundidade`, `arvore-geradora`, `algoritmos-do-menor-caminho`, `ordenacao-topologica`), and asymptotic complexity (`medidas-de-complexidade-...`, `notacao-big-o-little-o-omega-e-theta`).
   - Items outside the classifier scope are skipped with reason `out_of_scope_topic` (not quarantined as parse failures).
4. **Gate 4 — Whitespace-Normalized Round-Trip Check**:
   - The normalized question stem and options are re-rendered and compared against the cleaned source PDF span after normalizing whitespace and option markers. Any character mismatch routes the candidate to `reports/concurso-quarantine.jsonl` with reason `round_trip_mismatch`.
