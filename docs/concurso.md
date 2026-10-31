# Concurso TI Ingestion Guide (`fgv`, `iades`, `cesgranrio`, `fcpc`)

This document describes the architecture, quality gates, ID scheme, provenance contract, and operational workflow for ingesting Brazilian public-sector IT exam (*concurso público*) questions into `modules/question-bank`.

## Overview

The concurso ingestion pipeline extracts multiple-choice computer science questions from official exam booklets (`prova`) and official answer keys (`gabarito` / `definitivo`) published by four major Brazilian exam boards (*bancas*):

| Exam Slug (`exam`) | Exam Board | Option Count | Question Header Format | Option Format |
|---|---|---|---|---|
| `fgv` | Fundação Getulio Vargas (FGV Conhecimento) | 5 (`A`–`E`) | Standalone number (`1`..`80`) | `(A) text` |
| `iades` | Instituto Americano de Desenvolvimento (IADES) | 5 (`A`–`E`) | `QUESTÃO N` | `(A) text` |
| `cesgranrio` | Fundação Cesgranrio | 5 (`A`–`E`) | Standalone number (`1`..`80`) | `(A) text` |
| `fcpc` | Fundação Cearense de Pesquisa e Cultura (FCPC/UFC/UFCA) | 4 (`A`–`D`) | Two-digit dotted (`01. text`..`50. text`) | `A) text` |

All raw PDFs are stored locally under `data/raw/concurso/<banca>/<year>/` (gitignored) and cataloged with SHA-256 checksums and official URLs in [`reports/concurso-sources.json`](../reports/concurso-sources.json).

---

## How to Run

### 1. Dry-Run Inspection

To run the extraction, classification, answer-key matching, deduplication, and validation pass without modifying `questions/` or `reports/concurso-quarantine.jsonl`:

```bash
uv run python scripts/import-concurso.py --dry-run
```

### 2. Full Deterministic Import

To write verified question JSON files into `questions/` and route rejected candidates to `reports/concurso-quarantine.jsonl`:

```bash
uv run python scripts/import-concurso.py
```

Re-running `scripts/import-concurso.py` is strictly idempotent and produces zero `git diff`.

### 3. Validate and Search

```bash
# Run offline unit and bank validation tests
uv run python -m pytest tests -q

# Keyless lexical search across POSCOMP, ENADE, and Concurso exams
env -u OPENROUTER_API_KEY uv run question-search "arvore B" --top-k 5
env -u OPENROUTER_API_KEY uv run question-search "tabela hash encadeamento" --top-k 5
env -u OPENROUTER_API_KEY uv run question-search "indice consulta intervalo" --top-k 5
```

---

## Four-Gate Promotion & Quarantine Policy

Every extracted candidate question that matches at least one in-scope topic rule is evaluated against four deterministic gates in `src/question_bank/concurso.py` and `scripts/import-concurso.py`:

1. **Gate (a) — Clean Structural Parse & Visual Independence**:
   - The candidate must have the exact expected number of non-empty options (`5` for `fgv`, `iades`, `cesgranrio`; `4` for `fcpc`), a stem of at least 15 characters, and zero leaked PDF stream operators (`BT`/`ET`, `/F1 Tf`, `Td`).
   - Questions that depend on figures, diagrams, or unextracted visual assets (`"figura a seguir"`, `"imagem abaixo"`, `"diagrama a seguir"`, `"observe a figura"`, etc.) are rejected with reason `needs_visual_asset` unless verified image crops are provided.
2. **Gate (b) — Official Answer Key Resolution**:
   - The candidate's question number is matched against the official answer key for its specific `(organ, role, year, caderno)`.
   - **Definitive Answer Key (`gabarito_kind: "definitivo"`)**: Required for `"status": "active"`.
   - **Preliminary Answer Key Only (`gabarito_kind: "preliminar"`)**: Imported with `"status": "suspended"` and `"status_reason": "preliminary_answer_key"`.
   - **Annulled Questions (`*`, `#`, `X`, `N`, `NULA`, `ANULADA`)**: Never imported into `questions/`; routed to quarantine with reason `annulled_in_official_key`.
3. **Gate (c) — Explainable Topic Classification**:
   - Accent-insensitive keyword and phrase rules (`TOPIC_RULES` in `src/question_bank/concurso.py`) classify `stem + options` into registered slugs in [`docs/tags.md`](tags.md) covering:
     - B-trees and B+ trees (`arvore-b`, `arvore-b-mais`)
     - Balanced and binary search trees (`arvore-avl`, `arvore-rubro-negra`, `arvores-e-suas-generalizacoes-arvores-binarias-arvores-de-busca-e-arvores-balanceadas`)
     - Hash tables, collision resolution by chaining and open addressing (`tabelas-hash`, `hash-encadeamento`, `hash-enderecamento-aberto`)
     - Database indexes (`indices-banco-de-dados`)
     - Heaps and priority queues (`heap-fila-de-prioridade`)
     - Linear data structures (`estruturas-de-dados-lineares-e-suas-generalizacoes-listas-ordenadas-listas-encadeadas-pilhas-e-filas`)
     - Sorting and binary search (`algoritmos-para-pesquisa-e-ordenacao`)
     - Graph algorithms (`algoritmos-em-grafos`, `busca-em-largura-e-profundidade`, `arvore-geradora`, `algoritmos-do-menor-caminho`, `ordenacao-topologica`)
     - Asymptotic complexity (`medidas-de-complexidade-analise-assintotica-de-limites-de-complexidade-tecnicas-de-prova-de-cotas-inferiores`, `notacao-big-o-little-o-omega-e-theta`)
   - Questions that do not match any rule are skipped as out-of-scope and counted in the import report.
   - Disambiguation guards prevent false positives on non-IT Portuguese/English/law items and pure cryptographic digest (`SHA-256`, `MD5`, `ICP-Brasil`) questions that do not involve hash table data structures.
4. **Gate (d) — Round-Trip Text Verification**:
   - Re-rendering the JSON `stem` and `options` and comparing against the cleaned PDF question span after whitespace and option-marker normalization (`verify_round_trip`) must match (`"round_trip_verified": true`).

Candidates that match Gate (c) but fail Gate (a), Gate (b), or Gate (d) are written to `reports/concurso-quarantine.jsonl` (one JSON object per line with `candidate_id`, `banca`, `organ`, `role`, `year`, `caderno`, `number`, `reason`, `pdf`, `page`, `tags`) and excluded from `questions/`.

---

## ID Scheme & Cross-Caderno Deduplication

### Deterministic ID Format

Each question file is named `questions/<id>.json` where `<id>` follows:

```text
<banca>-<year>-<organ-slug>-<role-slug>-<caderno-slug>-<NNN>
```

Examples:
- `fgv-2024-trf1-tecnico-desenvolvimento-sistemas-tipo-1-044`
- `iades-2024-brb-analista-tipo-a-026`
- `fcpc-2025-ufc-analista-ciencia-dados-unico-010`

### Cross-Caderno and Cross-Role Deduplication

Exam boards frequently publish multiple booklet variants (*Tipo A/B/C/D* or *Tipo 1/2/3/4*) or share questions across multiple IT specialty tracks of the same `(banca, organ, year)`. `deduplicate_records()` computes an order-independent fingerprint (`question_fingerprint`) over accent-folded, punctuation-stripped `stem` and sorted `options`:

- Identical questions within the same `(banca, organ, year)` are collapsed into a single canonical JSON file (ordered deterministically by `(caderno, role, number)`).
- All roles appear in `provenance.roles`, all booklet codes appear in `provenance.cadernos`, all source PDFs appear in `provenance.sources`, and the exact per-booklet question number and answer letter mapping is recorded in `provenance.occurrences`.

---

## Provenance Schema Contract

Every concurso question record in `questions/` includes a `provenance` object validated by `src/question_bank/validate.py`:

```json
{
  "banca": "fgv",
  "organ": "trf1",
  "role": "Técnico Judiciário - Desenvolvimento de Sistemas de Informação",
  "roles": [
    "Técnico Judiciário - Desenvolvimento de Sistemas de Informação"
  ],
  "year": 2024,
  "caderno": "tipo-1",
  "cadernos": [
    "tipo-1"
  ],
  "gabarito_kind": "definitivo",
  "round_trip_verified": true,
  "matched_rules": [
    "hash_chaining",
    "hash_table"
  ],
  "prova_url": "https://conhecimento.fgv.br/sites/default/files/concursos/50.pdf",
  "prova_sha256": "a044e7e4814ce13131d7d44c13ba374cec9099c5628eb0ebb2ee032149a547a4",
  "gabarito_url": "https://conhecimento.fgv.br/sites/default/files/concursos/trf1_gabarito_definitivo_29-09_manha_0.pdf",
  "gabarito_sha256": "7fd2e362fa1869195292698ecabdcde883e9f672cc2a288b610f7fb574c158be",
  "occurrences": [
    {
      "role": "Técnico Judiciário - Desenvolvimento de Sistemas de Informação",
      "caderno": "tipo-1",
      "number": 44,
      "answer": "D"
    }
  ],
  "sources": [
    {
      "kind": "prova",
      "url": "https://conhecimento.fgv.br/sites/default/files/concursos/50.pdf",
      "sha256": "a044e7e4814ce13131d7d44c13ba374cec9099c5628eb0ebb2ee032149a547a4"
    },
    {
      "kind": "definitivo",
      "url": "https://conhecimento.fgv.br/sites/default/files/concursos/trf1_gabarito_definitivo_29-09_manha_0.pdf",
      "sha256": "7fd2e362fa1869195292698ecabdcde883e9f672cc2a288b610f7fb574c158be"
    }
  ]
}
```

---

## How to Add a New Exam

1. **Download Official PDFs**: Place the official exam booklet (`prova`) and official answer key (`definitivo` or `gabarito`) under `data/raw/concurso/<banca>/<year>/`. Never use third-party aggregator websites (`qconcursos`, `tecconcursos`, `grancursos`, `pciconcursos`, `estudeplan`, `certou`).
2. **Register in Manifest**: Add entries for the `prova` and `definitivo`/`gabarito` files in `reports/concurso-sources.json` with their `url`, `local_path`, `sha256`, `bytes`, `fetched_at`, `banca`, `organ`, `role`, `year`, `caderno`, and `kind`.
3. **Run Dry-Run & Inspect**: Run `uv run python scripts/import-concurso.py --dry-run` to verify that headers strip cleanly, options split accurately, and the answer key section matches.
4. **Import & Validate**: Run `uv run python scripts/import-concurso.py` followed by `uv run python -m pytest tests -q`.
