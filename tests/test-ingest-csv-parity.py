import importlib.util
import json
from pathlib import Path

from question_bank.ingest.pipeline import run_ingest


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "ingest-poscomp.csv"


def _load_legacy_importer():
    spec = importlib.util.spec_from_file_location("legacy_poscomp_importer", REPO / "scripts" / "import-poscomp.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_csv_pipeline_matches_poscomp_import_normalized_records(tmp_path: Path):
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    importer = _load_legacy_importer()
    written, skipped, _ = importer.convert(FIXTURE, legacy_dir, False)
    assert written == 5
    assert skipped == []

    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [
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
        ),
        encoding="utf-8",
    )
    # Source paths are manifest-relative; copy the fixture beside the manifest.
    (tmp_path / FIXTURE.name).write_bytes(FIXTURE.read_bytes())
    bank = tmp_path / "bank"
    summary = run_ingest(manifest, bank_root=bank)
    assert summary.as_dict() == {"ingested": 5, "skipped": 0, "quarantined": 0}

    # The generic schema adds type/status/provenance. Compare normalized record
    # dictionaries to the retired POSCOMP transform, which emits its legacy core.
    added_schema_fields = {"type", "status", "provenance"}
    for actual_path in (bank / "questions").glob("*.json"):
        actual = json.loads(actual_path.read_text(encoding="utf-8"))
        expected = json.loads((legacy_dir / actual_path.name).read_text(encoding="utf-8"))
        normalized = {key: value for key, value in actual.items() if key not in added_schema_fields}
        assert normalized == expected
