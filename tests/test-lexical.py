"""Keyless keyword search: ranking, filters, corrections, and CLI fallback."""
import json

import pytest

from question_search import cli, config, errors, lexical


def _bank(tmp_path):
    questions = tmp_path / "questions"
    questions.mkdir()
    rows = [
        ("q1", "poscomp", 2012, "Uma árvore AVL mantém o balanceamento após rotações.", ["trees"], "active"),
        ("q2", "poscomp", 2013, "O protocolo TCP controla congestionamento de redes.", ["networks"], "active"),
        ("q3", "enade", 2014, "Árvores binárias de busca e percurso em pós-ordem.", ["trees"], "active"),
        ("q4", "poscomp", 2015, "Árvore AVL suspensa por defeito.", ["trees"], "suspended"),
    ]
    for qid, exam, year, text, tags, status in rows:
        (questions / f"{qid}.json").write_text(
            json.dumps({"id": qid, "exam": exam, "year": year, "number": 1, "type": "discursive",
                        "stem": text, "tags": tags, "status": status}),
            encoding="utf-8",
        )
    return tmp_path


def test_accents_plurals_and_stems_match(tmp_path):
    root = _bank(tmp_path)
    ids = [r["id"] for r in lexical.search("arvores avl rotacao", root=root)]
    assert ids[0] == "q1" and "q2" not in ids
    assert all(r["engine"] == "lexical" for r in lexical.search("arvore", root=root))


def test_filters_status_exam_years_tags(tmp_path):
    root = _bank(tmp_path)
    assert "q4" not in [r["id"] for r in lexical.search("avl", root=root)]
    assert {r["id"] for r in lexical.search("avl", status="all", root=root)} == {"q1", "q4"}
    assert [r["id"] for r in lexical.search("arvore", exam="enade", root=root)] == ["q3"]
    assert [r["id"] for r in lexical.search("arvore", year_range=(2013, 2014), root=root)] == ["q3"]
    assert {r["id"] for r in lexical.search("arvore", tags=["trees"], root=root)} == {"q1", "q3"}


def test_tag_filter_lists_candidates_even_without_a_text_match(tmp_path):
    root = _bank(tmp_path)
    assert [r["id"] for r in lexical.search("zzz", tags=["networks"], root=root)] == ["q2"]
    assert lexical.search("zzz", root=root) == []


def test_corrections_overlay_changes_results(tmp_path):
    root = _bank(tmp_path)
    (root / "corrections").mkdir()
    (root / "corrections" / "log.jsonl").write_text(
        json.dumps({"question_id": "q2", "field": "stem", "new_value": "Agora fala de árvore AVL."}) + "\n",
        encoding="utf-8",
    )
    assert "q2" in [r["id"] for r in lexical.search("avl", root=root)]


@pytest.fixture
def keyless_cli(tmp_path, monkeypatch):
    root = _bank(tmp_path)
    monkeypatch.setattr(config, "BANK_ROOT", root)
    monkeypatch.setattr(config, "QUESTIONS_DIR", root / "questions")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    return root


def test_cli_query_falls_back_without_a_key(keyless_cli, capsys):
    assert cli.main(["query", "arvore avl", "--json"]) == errors.EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert results[0]["id"] == "q1" and results[0]["engine"] == "lexical"


def test_cli_semantic_mode_still_requires_a_key(keyless_cli):
    assert cli.main(["query", "avl", "--mode", "semantic"]) == errors.EXIT_CONFIG_ERROR


def test_cli_auto_falls_back_when_the_vector_store_is_down(keyless_cli, monkeypatch, capsys):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(cli.embed, "embed", lambda texts: [[0.0]])

    def down(**kwargs):
        raise errors.QdrantUnreachableError("down")

    monkeypatch.setattr(cli.store, "search_questions", down)
    assert cli.main(["query", "avl", "--json"]) == errors.EXIT_OK
    assert json.loads(capsys.readouterr().out)[0]["engine"] == "lexical"


def test_cli_index_without_a_key_is_a_clean_noop(keyless_cli, capsys):
    assert cli.main(["index", "--json"]) == errors.EXIT_OK
    assert json.loads(capsys.readouterr().out)["mode"] == "lexical"
