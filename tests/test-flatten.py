"""Unit tests for content block flattening and payload building."""
import json
from pathlib import Path
from question_search.flatten import (
    build_payload,
    flatten_block,
    flatten_blocks,
    flatten_options,
    flatten_question,
)


def test_flatten_bare_string_stem_v1():
    q = {
        "id": "poscomp-2002-01",
        "exam": "poscomp",
        "year": 2002,
        "number": 1,
        "type": "mc",
        "stem": "Considere a funcao $y = \\frac{1}{x}$.",
        "options": [
            "opcao um",
            "opcao dois",
        ],
        "answer": "A",
        "tags": ["matematica"],
    }
    text = flatten_question(q)
    assert "Considere a funcao $y = \\frac{1}{x}$." in text
    assert "A. opcao um" in text
    assert "B. opcao dois" in text
    # Answer and tags are NOT in embedded text
    assert "matematica" not in text
    assert "answer" not in text


def test_flatten_content_blocks_with_image_alt_and_latex():
    q = {
        "id": "poscomp-2022-67",
        "exam": "poscomp",
        "year": 2022,
        "number": 67,
        "type": "mc",
        "stem": [
            {"type": "text", "content": "Considere o circuito logico:"},
            {"type": "image", "src": "assets/circuit.png", "alt": "circuito AND e OR"},
            {"type": "text", "content": "Qual a expressao da saida $X$?"},
        ],
        "options": [
            [{"type": "text", "content": "Saida $A \\cdot B$"}],
            [{"type": "image", "src": "assets/opt.png", "alt": "diagrama de portas"}],
        ],
        "answer": "A",
        "tags": ["circuitos"],
    }
    text = flatten_question(q)
    lines = text.split("\n")
    assert lines[0] == "Considere o circuito logico:"
    assert lines[1] == "circuito AND e OR"
    assert lines[2] == "Qual a expressao da saida $X$?"
    assert lines[3] == "A. Saida $A \\cdot B$"
    assert lines[4] == "B. diagrama de portas"


def test_flatten_with_context_file(tmp_path):
    contexts_dir = tmp_path / "contexts"
    contexts_dir.mkdir()
    ctx_file = contexts_dir / "ctx-text-1.json"
    ctx_data = {
        "id": "ctx-text-1",
        "body": [
            {"type": "text", "content": "Este e o texto base compartilhado."},
            {"type": "image", "src": "assets/fig.png", "alt": "imagem contexto"},
            {"type": "text", "content": "Segundo paragrafo do texto base."},
        ],
    }
    ctx_file.write_text(json.dumps(ctx_data), encoding="utf-8")

    q = {
        "id": "poscomp-2022-05",
        "exam": "poscomp",
        "year": 2022,
        "number": 5,
        "type": "mc",
        "context": "ctx-text-1",
        "stem": "Com base no texto, responda:",
        "options": ["A favor", "Contra"],
    }

    text = flatten_question(q, contexts_dir=contexts_dir)
    assert text.startswith("Este e o texto base compartilhado.\nCom base no texto, responda:")
    assert "A. A favor" in text
    assert "B. Contra" in text


def test_flatten_discursive_excludes_rubric():
    q = {
        "id": "enade-2021-36",
        "exam": "enade",
        "year": 2021,
        "number": 36,
        "type": "discursive",
        "stem": "Explique o conceito de concorrencia e exclusao mutua.",
        "rubric": [
            {"type": "text", "content": "Criterio de correcao: citar semaforos e mutex."}
        ],
        "tags": ["sistemas-operacionais"],
    }
    text = flatten_question(q)
    assert text == "Explique o conceito de concorrencia e exclusao mutua."
    assert "Criterio de correcao" not in text
    assert "semaforos" not in text


def test_build_payload_shape():
    q = {
        "id": "poscomp-2022-67",
        "exam": "POSCOMP",
        "year": "2022",
        "number": "67",
        "type": "mc",
        "status": "active",
        "source": "POSCOMP 2022, questao 67",
        "answer": "B",
        "tags": ["banco-de-dados", "sql"],
        "rubric": "secret rubric",
    }
    flattened = "flattened text"
    payload = build_payload(q, flattened)

    assert payload["question_id"] == "poscomp-2022-67"
    assert payload["exam"] == "poscomp"
    assert payload["year"] == 2022
    assert payload["number"] == 67
    assert payload["type"] == "mc"
    assert payload["status"] == "active"
    assert payload["source"] == "POSCOMP 2022, questao 67"
    assert payload["answer"] == "B"
    assert payload["tags"] == ["banco-de-dados", "sql"]
    assert payload["text"] == "flattened text"
    assert "rubric" not in payload
