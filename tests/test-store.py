"""Unit tests for store operations and deterministic ID generation."""
import uuid
from question_search.store import make_point_id


def test_make_point_id_deterministic_and_63_bit():
    qid = "poscomp-2022-67"
    pid1 = make_point_id(qid)
    pid2 = make_point_id(qid)

    assert pid1 == pid2
    assert isinstance(pid1, int)
    assert 0 <= pid1 < (1 << 63)

    # Invariant to chunk 0 format
    expected = int(uuid.uuid5(uuid.NAMESPACE_URL, f"{qid}:0").int & 0x7FFFFFFFFFFFFFFF)
    assert pid1 == expected


def test_make_point_id_unique_per_question():
    pid1 = make_point_id("poscomp-2022-01")
    pid2 = make_point_id("poscomp-2022-02")
    assert pid1 != pid2
