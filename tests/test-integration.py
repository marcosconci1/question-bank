"""Integration tests against live Qdrant instance for question-search."""
import json
import pytest
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException

from question_search import config, errors, flatten, ledger, store


@pytest.mark.integration
def test_qdrant_live_integration_and_filtering(tmp_path, monkeypatch):
    test_collection = "test-fixture-questions"
    client = QdrantClient(url=config.QDRANT_URL)

    # Ensure clean test collection
    try:
        collection_exists = client.collection_exists(test_collection)
    except ResponseHandlingException:
        pytest.skip(f"Qdrant not reachable at {config.QDRANT_URL}")

    if collection_exists:
        client.delete_collection(test_collection)

    store.ensure_collection(client=client, collection_name=test_collection, dim=4)

    # Create 5-question fixture bank
    qdir = tmp_path / "questions"
    qdir.mkdir()

    fixtures = [
        {
            "id": "poscomp-2018-01",
            "exam": "poscomp",
            "year": 2018,
            "number": 1,
            "type": "mc",
            "status": "active",
            "stem": "Pergunta sobre banco de dados relacional e SQL.",
            "options": ["Opcao A", "Opcao B"],
            "answer": "A",
            "tags": ["banco-de-dados"],
        },
        {
            "id": "poscomp-2022-10",
            "exam": "poscomp",
            "year": 2022,
            "number": 10,
            "type": "mc",
            "status": "active",
            "stem": "Pergunta sobre normalizacao em banco de dados.",
            "options": ["Opcao A", "Opcao B"],
            "answer": "B",
            "tags": ["banco-de-dados", "modelagem"],
        },
        {
            "id": "poscomp-2023-15",
            "exam": "poscomp",
            "year": 2023,
            "number": 15,
            "type": "mc",
            "status": "active",
            "stem": "Pergunta sobre redes de computadores e TCP/IP.",
            "options": ["Opcao A", "Opcao B"],
            "answer": "A",
            "tags": ["redes"],
        },
        {
            "id": "enade-2021-05",
            "exam": "enade",
            "year": 2021,
            "number": 5,
            "type": "mc",
            "status": "active",
            "stem": "Pergunta ENADE sobre banco de dados NoSQL.",
            "options": ["Opcao A", "Opcao B"],
            "answer": "A",
            "tags": ["banco-de-dados"],
        },
        {
            "id": "poscomp-2015-02",
            "exam": "poscomp",
            "year": 2015,
            "number": 2,
            "type": "mc",
            "status": "suspended",
            "stem": "Pergunta antiga anulada sobre banco de dados.",
            "options": ["Opcao A", "Opcao B"],
            "answer": "A",
            "tags": ["banco-de-dados"],
        },
    ]

    # Deterministic 4-dim unit vectors for testing
    vectors = [
        [1.0, 0.0, 0.0, 0.0],
        [0.9, 0.1, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.8, 0.2, 0.0, 0.0],
        [0.7, 0.3, 0.0, 0.0],
    ]

    points_data = []
    for q, vec in zip(fixtures, vectors):
        f = qdir / f"{q['id']}.json"
        f.write_text(json.dumps(q), encoding="utf-8")
        text = flatten.flatten_question(q)
        payload = flatten.build_payload(q, text)
        pid = store.make_point_id(q["id"])
        points_data.append((pid, vec, payload))

    store.upsert_points(points_data, client=client, collection_name=test_collection)

    # 1. Default query with status=active (suspended excluded)
    query_vec = [1.0, 0.0, 0.0, 0.0]
    res_all_active = store.search_questions(
        query_vector=query_vec,
        limit=10,
        status="active",
        client=client,
        collection_name=test_collection,
    )
    res_ids = [r["id"] for r in res_all_active]
    assert "poscomp-2015-02" not in res_ids
    assert len(res_ids) == 4
    # Highest score first
    assert res_ids[0] == "poscomp-2018-01"

    # 2. Filtered query: exam=poscomp, years=2018-2023, tags=["banco-de-dados"]
    res_filtered = store.search_questions(
        query_vector=query_vec,
        limit=10,
        status="active",
        exam="poscomp",
        year_range=(2018, 2023),
        tags=["banco-de-dados"],
        client=client,
        collection_name=test_collection,
    )
    filtered_ids = [r["id"] for r in res_filtered]
    assert filtered_ids == ["poscomp-2018-01", "poscomp-2022-10"]

    # 3. Query explicitly for status=suspended
    res_suspended = store.search_questions(
        query_vector=query_vec,
        limit=10,
        status="suspended",
        client=client,
        collection_name=test_collection,
    )
    assert [r["id"] for r in res_suspended] == ["poscomp-2015-02"]

    # Cleanup test collection
    client.delete_collection(test_collection)
