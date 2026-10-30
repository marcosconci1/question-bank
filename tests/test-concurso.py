"""Offline unit tests for concurso PDF parsing, gabarito matching, classification, and validation."""

from __future__ import annotations

from pathlib import Path
import pymupdf
import pytest

from question_bank.concurso import (
    ANNULLED,
    classify_question,
    deduplicate_records,
    extract_questions_from_pdf,
    fold_accents,
    match_gabarito_section,
    normalize_whitespace,
    parse_gabarito_pdf,
    parse_gabarito_text,
    question_fingerprint,
    split_questions_from_pages,
    strip_page_noise,
    verify_round_trip,
)
from question_bank.validate import load_registered_tags, validate_question


def _make_pdf(tmp_path: Path, filename: str, pages: list[str]) -> Path:
    """Create a tiny synthetic PDF using PyMuPDF with one text block per page."""
    pdf_path = tmp_path / filename
    doc = pymupdf.open()
    for page_text in pages:
        page = doc.new_page(width=595, height=842)
        rect = pymupdf.Rect(36, 36, 559, 806)
        page.insert_textbox(rect, page_text, fontsize=9, fontname="helv")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_fold_accents_and_normalize_whitespace() -> None:
    assert fold_accents("Árvore B+ e Dispersão") == "arvore b+ e dispersao"
    assert normalize_whitespace("tabela   de\xad\n  hash  ") == "tabela de hash"


def test_strip_page_noise_per_banca() -> None:
    fgv_page = (
        "Tribunal Regional Federal da 1ª Região\n"
        "FGV Conhecimento\n"
        "Técnico Judiciário - Desenvolvimento de Sistemas de Informação\n"
        "\uf09f\n"
        "Tipo 1 – Branca – Página 9\n"
        "Conhecimentos Específicos\n"
        "44\n"
        "Considere uma tabela hash com encadeamento.\n"
    )
    cleaned_fgv = strip_page_noise(fgv_page, "fgv")
    assert "FGV Conhecimento" not in cleaned_fgv
    assert "Página 9" not in cleaned_fgv
    assert "44" in cleaned_fgv
    assert "Considere uma tabela hash" in cleaned_fgv

    iades_page = (
        "PROVA APLICADA\n"
        "PÁGINA 9/17\n"
        "102 – ANALISTA DE TECNOLOGIA DA INFORMAÇÃO\n"
        "TIPO “A”\n"
        "QUESTÃO 26 _______________________\n"
        "Uma estrutura de dados que utiliza uma tabela de hash.\n"
        "Área livre\n"
    )
    cleaned_iades = strip_page_noise(iades_page, "iades")
    assert "PROVA APLICADA" not in cleaned_iades
    assert "Área livre" not in cleaned_iades
    assert "QUESTÃO 26" in cleaned_iades

    cesgranrio_page = (
        "12\n"
        "BANCO DO BRASIL\n"
        "AGENTE DE TECNOLOGIA\n"
        "GABARITO 1\n"
        "CONHECIMENTOS ESPECÍFICOS\n"
        "41\n"
        "Considere uma árvore B de ordem 4.\n"
        "RASCUNHO\n"
    )
    cleaned_cesg = strip_page_noise(cesgranrio_page, "cesgranrio")
    assert "GABARITO 1" not in cleaned_cesg
    assert "RASCUNHO" not in cleaned_cesg
    assert "41" in cleaned_cesg

    fcpc_page = (
        "Concurso UFC - Edital 01/2024\n"
        "Analista de Tecnologia da Informação / Área: Ciência de Dados\n"
        "Prova 3 - Conhecimentos Específicos\n"
        "30 questões\n"
        "10. Considere uma tabela de clientes.\n"
        "Pág. 8 de 12\n"
    )
    cleaned_fcpc = strip_page_noise(fcpc_page, "fcpc")
    assert "Pág. 8 de 12" not in cleaned_fcpc
    assert "30 questões" not in cleaned_fcpc
    assert "10. Considere uma tabela de clientes." in cleaned_fcpc


def test_split_and_extract_synthetic_pdfs_5_and_4_options(tmp_path: Path) -> None:
    fgv_pages = [
        "Informações Gerais\nLeia atentamente as instruções abaixo.\nCaderno de Provas",
        (
            "Tribunal Regional Federal da 1ª Região\n"
            "FGV Conhecimento\n"
            "Tipo 1 – Branca – Página 2\n"
            "1\n"
            "Considere uma tabela hash de tamanho 10 com função h(k) = k mod 10 e tratamento de colisões por encadeamento para as chaves 15, 25, 35, 45 e 55.\n"
            "(A) Todas as chaves colidem no índice 5.\n"
            "(B) Nenhuma colisão ocorre.\n"
            "(C) Ocorre overflow imediato.\n"
            "(D) As chaves são distribuídas uniformemente.\n"
            "(E) Apenas duas chaves colidem.\n"
        ),
    ]
    fgv_pdf = _make_pdf(tmp_path, "fgv-sample.pdf", fgv_pages)
    fgv_cands = extract_questions_from_pdf(fgv_pdf, "fgv")
    assert len(fgv_cands) == 1
    q1 = fgv_cands[0]
    assert q1.number == 1
    assert len(q1.options) == 5
    assert q1.round_trip_ok is True
    assert q1.quarantine_reason is None
    assert "15, 25, 35, 45 e 55" in q1.stem

    fcpc_pages = [
        "Prezado(a) Candidato(a), leia atentamente as instruções.",
        (
            "Concurso UFC\n"
            "Prova 3 - Conhecimentos Específicos\n"
            "10. Considere uma tabela de clientes com consulta por intervalo idade >= 25 AND idade < 30. Qual estrutura de índice é mais adequada?\n"
            "A) Índice Hash.\n"
            "B) Índice Bitmap.\n"
            "C) Árvore B+.\n"
            "D) Lista Invertida.\n"
            "Pág. 8 de 12\n"
        ),
    ]
    fcpc_pdf = _make_pdf(tmp_path, "fcpc-sample.pdf", fcpc_pages)
    fcpc_cands = extract_questions_from_pdf(fcpc_pdf, "fcpc")
    assert len(fcpc_cands) == 1
    qf = fcpc_cands[0]
    assert qf.number == 10
    assert qf.gabarito_number == 30
    assert len(qf.options) == 4
    assert qf.options[2] == "Árvore B+."
    assert qf.round_trip_ok is True
    assert qf.quarantine_reason is None


def test_quarantine_routing_visual_and_malformed() -> None:
    pages = [
        "Informações Gerais\nCaderno de Provas",
        (
            "1\n"
            "Observe a figura a seguir que representa uma árvore AVL após inserção.\n"
            "(A) Rotação simples à direita.\n"
            "(B) Rotação simples à esquerda.\n"
            "(C) Rotação dupla à direita.\n"
            "(D) Rotação dupla à esquerda.\n"
            "(E) Sem rotação.\n"
            "2\n"
            "Considere uma árvore rubro-negra com apenas três alternativas extraídas.\n"
            "(A) Altura negra constante.\n"
            "(B) Raiz sempre preta.\n"
            "(C) Folhas nulas pretas.\n"
        ),
    ]
    cands = split_questions_from_pages(pages, "fgv")
    assert len(cands) == 2
    assert cands[0].quarantine_reason == "needs_visual_asset"
    assert cands[1].quarantine_reason == "option_count_3_expected_5"
    assert verify_round_trip(cands[0].stem, cands[0].options, "corrupted span") is False


def test_parse_gabarito_and_annulments_across_bancas(tmp_path: Path) -> None:
    # FGV gabarito with '*' annulment
    fgv_gab = [
        (
            "TRIBUNAL REGIONAL FEDERAL\n"
            "GABARITOS DEFINITIVOS\n"
            "Técnico Judiciário - Desenvolvimento de Sistemas de Informação - TIPO 1\n"
            "1\n2\n3\n4\n5\n"
            "A\n*\nC\nD\nE\n"
            "(*) questão anulada\n"
        )
    ]
    fgv_pdf = _make_pdf(tmp_path, "fgv-gab.pdf", fgv_gab)
    fgv_secs = parse_gabarito_pdf(fgv_pdf, "fgv")
    matched_fgv = match_gabarito_section(
        fgv_secs,
        "fgv",
        "Técnico Judiciário - Desenvolvimento de Sistemas de Informação",
        "tipo-1",
    )
    assert matched_fgv is not None
    assert matched_fgv[1] == "A"
    assert matched_fgv[2] == ANNULLED
    assert matched_fgv[4] == "D"

    # IADES gabarito with '#' annulment across Tipo A and Tipo B
    iades_gab = [
        (
            "102 – Analista de Tecnologia da Informação\n"
            "Prova Tipo “A”\n"
            "1\n2\n3\n"
            "C\n#\nA\n"
            "Prova Tipo “B”\n"
            "1\n2\n3\n"
            "E\nB\n#\n"
        )
    ]
    iades_secs = parse_gabarito_text(iades_gab, "iades")
    sec_a = match_gabarito_section(iades_secs, "iades", "Analista de Tecnologia da Informação", "tipo-a")
    sec_b = match_gabarito_section(iades_secs, "iades", "Analista de Tecnologia da Informação", "tipo-b")
    assert sec_a == {1: "C", 2: ANNULLED, 3: "A"}
    assert sec_b == {1: "E", 2: "B", 3: ANNULLED}

    # Cesgranrio gabarito with 'Anulada'
    cesg_gab = [
        (
            "GABARITO 1\n"
            "1 - A\n"
            "2 - Anulada\n"
            "3 - E\n"
        )
    ]
    cesg_secs = parse_gabarito_text(cesg_gab, "cesgranrio")
    sec_c = match_gabarito_section(cesg_secs, "cesgranrio", "Agente de Tecnologia", "gabarito-1")
    assert sec_c == {1: "A", 2: ANNULLED, 3: "E"}

    # FCPC gabarito with 'N' and 'NULA'
    fcpc_gab = [
        (
            "GABARITO OFICIAL\n"
            "Analista de Tecnologia da Informação / Área: Ciência de Dados\n"
            "PROVA 1 - LÍNGUA PORTUGUESA\n"
            "01 02\n"
            "A N\n"
            "PROVA 2 - LEGISLAÇÃO\n"
            "01 02\n"
            "B NULA\n"
            "Fortaleza, 28 de janeiro de 2025.\n"
        )
    ]
    fcpc_secs = parse_gabarito_text(fcpc_gab, "fcpc")
    sec_f = match_gabarito_section(
        fcpc_secs,
        "fcpc",
        "Analista de Tecnologia da Informação / Área: Ciência de Dados",
        "unico",
    )
    assert sec_f == {1: "A", 2: ANNULLED, 3: "B", 4: ANNULLED}


def test_classifier_positives_and_negatives() -> None:
    tags_path = Path(__file__).resolve().parents[1] / "docs" / "tags.md"
    registered_tags = load_registered_tags(tags_path)

    # Probe A: Hash table with chaining
    tags_a, rules_a = classify_question(
        "Em uma tabela hash com encadeamento externo, inserem-se as chaves 15, 25, 35, 45 e 55.",
        ["(A) lista encadeada", "(B) colisão", "(C) bucket", "(D) hash", "(E) vetor"],
    )
    assert "tabelas-hash" in tags_a
    assert "hash-encadeamento" in tags_a
    assert "hash_chaining" in rules_a
    assert set(tags_a).issubset(registered_tags)

    # Probe B: IADES hash table
    tags_b, _ = classify_question(
        "Uma estrutura de dados que utiliza uma tabela de hash para armazenamento de informação.",
        ["Acesso O(1)", "Árvore", "Pilha", "Fila", "Grafo"],
    )
    assert "tabelas-hash" in tags_b
    assert set(tags_b).issubset(registered_tags)

    # Probe C: B-tree balance
    tags_c, _ = classify_question(
        "Uma árvore B se mantém balanceada com o decorrer do tempo através de divisões de nós.",
        ["Ordem da árvore B", "Folhas no mesmo nível", "Raiz", "Chaves", "Ponteiros"],
    )
    assert "arvore-b" in tags_c
    assert set(tags_c).issubset(registered_tags)

    # Probe D: Database range query index with B+ tree
    tags_d, _ = classify_question(
        "Considere uma tabela de clientes com cláusula WHERE idade >= 25 AND idade < 30. Qual estrutura de índice é mais eficiente para consultas por intervalo?",
        ["Índice Hash", "Índice Bitmap", "Árvore B+", "Lista Invertida"],
    )
    assert "indices-banco-de-dados" in tags_d
    assert "arvore-b-mais" in tags_d
    assert set(tags_d).issubset(registered_tags)

    # Negative 1: Portuguese / General administration text mentioning "índice" or "ordem"
    tags_neg1, rules_neg1 = classify_question(
        "O índice de inflação oficial subiu na última semana conforme a ordem econômica vigente no país.",
        ["Aumento de preços", "Redução da taxa", "Estabilidade", "Deflação", "Câmbio"],
    )
    assert tags_neg1 == []
    assert rules_neg1 == []

    # Negative 2: Cryptography SHA-256 / assinatura digital without data-structure hash table context
    tags_neg2, rules_neg2 = classify_question(
        "No contexto de assinatura digital e ICP-Brasil, a função de hash criptográfico SHA-256 garante integridade.",
        ["Chave privada", "Certificado digital", "MD5", "Criptografia assimétrica", "Carimbo do tempo"],
    )
    assert tags_neg2 == []
    assert rules_neg2 == []


def test_deduplicate_across_cadernos_and_roles() -> None:
    rec1 = {
        "id": "iades-2024-brb-analista-ti-tipo-a-026",
        "type": "mc",
        "exam": "iades",
        "year": 2024,
        "number": 26,
        "stem": "Uma estrutura de dados que utiliza uma tabela de hash para armazenamento de informação.",
        "options": ["Opção 1", "Opção 2", "Opção 3", "Opção 4", "Opção 5"],
        "answer": "C",
        "source": "IADES — BRB 2024",
        "tags": ["fundamentos-da-computacao", "algoritmos-e-estrutura-de-dados", "tabelas-hash"],
        "status": "active",
        "provenance": {
            "banca": "iades",
            "organ": "brb",
            "role": "Analista de Tecnologia da Informação",
            "year": 2024,
            "caderno": "tipo-a",
            "gabarito_kind": "definitivo",
            "round_trip_verified": True,
            "sources": [{"kind": "prova", "url": "https://www.iades.com.br/a.pdf", "sha256": "a" * 64}],
        },
    }
    rec2 = {
        **rec1,
        "id": "iades-2024-brb-analista-ti-tipo-b-053",
        "number": 53,
        "options": ["Opção 2", "Opção 1", "Opção 3", "Opção 5", "Opção 4"],
        "answer": "D",
        "provenance": {
            **rec1["provenance"],
            "caderno": "tipo-b",
            "sources": [{"kind": "prova", "url": "https://www.iades.com.br/b.pdf", "sha256": "b" * 64}],
        },
    }
    assert question_fingerprint(rec1["stem"], rec1["options"]) == question_fingerprint(rec2["stem"], rec2["options"])
    deduped = deduplicate_records([rec2, rec1])
    assert len(deduped) == 1
    canon = deduped[0]
    assert canon["id"] == "iades-2024-brb-analista-ti-tipo-a-026"
    assert canon["provenance"]["cadernos"] == ["tipo-a", "tipo-b"]
    assert len(canon["provenance"]["occurrences"]) == 2
    assert len(canon["provenance"]["sources"]) == 2


def test_validator_accepts_active_and_suspended_concurso_records(tmp_path: Path) -> None:
    tags_path = Path(__file__).resolve().parents[1] / "docs" / "tags.md"
    registered_tags = load_registered_tags(tags_path)

    active_q = {
        "id": "fgv-2024-trf1-tecnico-dsi-tipo-1-044",
        "type": "mc",
        "exam": "fgv",
        "year": 2024,
        "number": 44,
        "stem": "Considere uma tabela hash com encadeamento externo para as chaves 15, 25, 35, 45 e 55:",
        "options": [
            "Ocorre overflow imediato na primeira inserção.",
            "As chaves são distribuídas uniformemente em cinco buckets.",
            "A busca passa a ter complexidade logarítmica garantida.",
            "Todas as chaves colidem no mesmo índice formando uma lista encadeada.",
            "Nenhuma colisão ocorre durante o processo.",
        ],
        "answer": "D",
        "source": "FGV — TRF1 2024 (Técnico Judiciário - Desenvolvimento de Sistemas de Informação, tipo-1, Q44)",
        "tags": [
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "tabelas-hash",
            "hash-encadeamento",
        ],
        "status": "active",
        "provenance": {
            "banca": "fgv",
            "organ": "trf1",
            "role": "Técnico Judiciário - Desenvolvimento de Sistemas de Informação",
            "roles": ["Técnico Judiciário - Desenvolvimento de Sistemas de Informação"],
            "year": 2024,
            "caderno": "tipo-1",
            "cadernos": ["tipo-1"],
            "gabarito_kind": "definitivo",
            "round_trip_verified": True,
            "prova_url": "https://conhecimento.fgv.br/sites/default/files/concursos/50.pdf",
            "prova_sha256": "a" * 64,
            "gabarito_url": "https://conhecimento.fgv.br/sites/default/files/concursos/trf1_gab_def.pdf",
            "gabarito_sha256": "b" * 64,
            "sources": [
                {
                    "kind": "prova",
                    "url": "https://conhecimento.fgv.br/sites/default/files/concursos/50.pdf",
                    "sha256": "a" * 64,
                },
                {
                    "kind": "definitivo",
                    "url": "https://conhecimento.fgv.br/sites/default/files/concursos/trf1_gab_def.pdf",
                    "sha256": "b" * 64,
                },
            ],
        },
    }
    res_active = validate_question(active_q, tmp_path / f"{active_q['id']}.json", registered_tags)
    assert res_active.errors == []
    assert res_active.warnings == []

    suspended_q = {
        **active_q,
        "id": "fgv-2026-dataprev-ati-desenvolvimento-tipo-1-041",
        "year": 2026,
        "number": 41,
        "status": "suspended",
        "status_reason": "preliminary_answer_key",
        "provenance": {
            **active_q["provenance"],
            "organ": "dataprev",
            "year": 2026,
            "gabarito_kind": "preliminar",
        },
    }
    res_susp = validate_question(suspended_q, tmp_path / f"{suspended_q['id']}.json", registered_tags)
    assert res_susp.errors == []
    assert res_susp.warnings == []


def test_import_concurso_idempotence_and_quarantine(tmp_path: Path) -> None:
    import hashlib
    import importlib.util
    import json

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "import-concurso.py"
    spec = importlib.util.spec_from_file_location("import_concurso", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Create synthetic prova + definitivo gabarito in tmp_path
    prova_pages = [
        "Informações Gerais\nCaderno de Provas",
        (
            "Tribunal Regional Federal\n"
            "FGV Conhecimento\n"
            "Tipo 1 – Branca – Página 2\n"
            "1\n"
            "Considere uma tabela hash com tratamento de colisões por encadeamento externo para as chaves 15, 25, 35, 45 e 55.\n"
            "(A) Ocorre overflow imediato.\n"
            "(B) As chaves são distribuídas uniformemente.\n"
            "(C) A busca tem complexidade quadrática.\n"
            "(D) Todas as chaves colidem no mesmo índice.\n"
            "(E) Nenhuma colisão ocorre.\n"
            "2\n"
            "Observe a figura a seguir que mostra uma árvore B de ordem 3.\n"
            "(A) Altura 1.\n"
            "(B) Altura 2.\n"
            "(C) Altura 3.\n"
            "(D) Altura 4.\n"
            "(E) Altura 5.\n"
            "3\n"
            "Assinale a alternativa em que todas as palavras estão grafadas corretamente.\n"
            "(A) Exceção.\n"
            "(B) Excessão.\n"
            "(C) Esceção.\n"
            "(D) Excessão.\n"
            "(E) Ecessão.\n"
        ),
    ]
    gab_pages = [
        (
            "TRIBUNAL REGIONAL FEDERAL\n"
            "GABARITOS DEFINITIVOS\n"
            "Técnico Judiciário - Desenvolvimento de Sistemas de Informação - TIPO 1\n"
            "1\n2\n3\n"
            "D\nA\nA\n"
        )
    ]
    prova_pdf = _make_pdf(tmp_path, "prova.pdf", prova_pages)
    gab_pdf = _make_pdf(tmp_path, "gab.pdf", gab_pages)

    # Monkeypatch REPO_ROOT to tmp_path so relative local_path resolves
    mod.REPO_ROOT = tmp_path
    manifest = [
        {
            "url": "https://conhecimento.fgv.br/prova.pdf",
            "local_path": "prova.pdf",
            "sha256": hashlib.sha256(prova_pdf.read_bytes()).hexdigest(),
            "bytes": prova_pdf.stat().st_size,
            "fetched_at": "2026-10-30T00:00:00Z",
            "banca": "fgv",
            "organ": "trf1",
            "role": "Técnico Judiciário - Desenvolvimento de Sistemas de Informação",
            "year": 2024,
            "caderno": "tipo-1",
            "kind": "prova",
        },
        {
            "url": "https://conhecimento.fgv.br/gab.pdf",
            "local_path": "gab.pdf",
            "sha256": hashlib.sha256(gab_pdf.read_bytes()).hexdigest(),
            "bytes": gab_pdf.stat().st_size,
            "fetched_at": "2026-10-30T00:00:00Z",
            "banca": "fgv",
            "organ": "trf1",
            "role": "Todos os Cargos",
            "year": 2024,
            "caderno": "unico",
            "kind": "definitivo",
        },
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    q_dir = tmp_path / "questions"
    quar_path = tmp_path / "quarantine.jsonl"
    tags_path = Path(__file__).resolve().parents[1] / "docs" / "tags.md"

    s1 = mod.run_import(manifest_path, q_dir, quar_path, tags_path, dry_run=False)
    assert s1["deduped_imported_total"] == 1
    assert s1["quarantined_total"] == 1
    assert s1["skipped_out_of_scope_total"] == 1

    files_run1 = {p.name: p.read_bytes() for p in q_dir.glob("*.json")}
    quar_run1 = quar_path.read_bytes()

    s2 = mod.run_import(manifest_path, q_dir, quar_path, tags_path, dry_run=False)
    assert s1 == s2
    files_run2 = {p.name: p.read_bytes() for p in q_dir.glob("*.json")}
    assert files_run1 == files_run2
    assert quar_run1 == quar_path.read_bytes()

