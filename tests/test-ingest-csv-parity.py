import json
from pathlib import Path

from question_bank.ingest.pipeline import run_ingest


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "ingest-poscomp.csv"
GOLDEN = REPO / "tests" / "fixtures" / "poscomp-golden"

MANIFEST_SOURCES = [
    {
        "id": "fixture-poscomp",
        "kind": "csv",
        "path": FIXTURE.name,
        "exam": "poscomp",
        "year": 2020,
        "options": {
            "answer_column": "key",
            "id_prefix": "poscomp-",
            "source_template": "POSCOMP {year}, question {number}",
        },
    }
]


def _ingest_once(tmp_path: Path):
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps(MANIFEST_SOURCES), encoding="utf-8")
    # Source paths are manifest-relative; copy the fixture beside the manifest.
    (tmp_path / FIXTURE.name).write_bytes(FIXTURE.read_bytes())
    bank = tmp_path / "bank"
    return run_ingest(manifest, bank_root=bank), bank


def test_csv_pipeline_matches_poscomp_import_normalized_records(tmp_path: Path):
    summary, bank = _ingest_once(tmp_path)
    assert summary.as_dict() == {"ingested": 5, "skipped": 0, "quarantined": 0}

    # The generic schema adds type/status/provenance. Compare normalized record
    # dictionaries to the golden fixtures captured from the retired POSCOMP
    # import transform.
    added_schema_fields = {"type", "status", "provenance"}
    golden_names = {path.name for path in GOLDEN.glob("*.json")}
    bank_names = {path.name for path in (bank / "questions").glob("*.json")}
    assert bank_names == golden_names
    for actual_path in (bank / "questions").glob("*.json"):
        actual = json.loads(actual_path.read_text(encoding="utf-8"))
        expected = json.loads((GOLDEN / actual_path.name).read_text(encoding="utf-8"))
        normalized = {key: value for key, value in actual.items() if key not in added_schema_fields}
        assert normalized == expected


def test_pipeline_quarantines_rejected_candidates(tmp_path: Path):
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "id": "fixture-fake",
                    "kind": "csv",
                    "path": "anything.csv",
                    "exam": "sat-math",
                    "year": 2024,
                }
            ]
        ),
        encoding="utf-8",
    )
    bank = tmp_path / "bank"

    def read(self, source):
        yield {"id": "bad id!", "stem": "x"}  # invalid id shape
        yield {"id": "valid-id", "stem": "x"}  # missing required fields

    fake_adapter = type("FakeAdapter", (), {"read": read})()
    summary = run_ingest(manifest, bank_root=bank, adapters={"csv": fake_adapter})
    assert summary.as_dict() == {"ingested": 0, "skipped": 0, "quarantined": 2}

    quarantine_path = bank / "reports" / "ingest-quarantine.jsonl"
    records = [json.loads(line) for line in quarantine_path.read_text(encoding="utf-8").splitlines()]
    reasons = [record["reason"] for record in records]
    assert reasons == ["invalid_id", "validator_error"]
    assert "codes" in records[1]


def test_pipeline_ingest_is_idempotent(tmp_path: Path):
    summary, bank = _ingest_once(tmp_path)
    assert summary.as_dict() == {"ingested": 5, "skipped": 0, "quarantined": 0}
    files_run1 = {path.name: path.read_bytes() for path in (bank / "questions").glob("*.json")}

    summary2, _ = _ingest_once(tmp_path)
    assert summary2.as_dict() == {"ingested": 0, "skipped": 5, "quarantined": 0}
    files_run2 = {path.name: path.read_bytes() for path in (bank / "questions").glob("*.json")}
    assert files_run1 == files_run2
