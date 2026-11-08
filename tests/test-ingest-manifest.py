import json
from pathlib import Path

import pytest

from question_bank.ingest.manifest import load_manifest


def test_manifest_loads_csv_sources_relative_to_manifest(tmp_path: Path):
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [{"id": "one", "kind": "csv", "path": "data.csv", "exam": "POSCOMP", "year": 2020}]
        ),
        encoding="utf-8",
    )
    source = load_manifest(manifest)[0]
    assert source.id == "one"
    assert source.exam == "poscomp"
    assert source.year == 2020
    assert source.path == (tmp_path / "data.csv").resolve()
    assert source.options == {}


def test_manifest_rejects_unknown_kind(tmp_path: Path):
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps([{"id": "one", "kind": "pdf", "path": "a", "exam": "poscomp", "year": 2020}]))
    with pytest.raises(ValueError, match="unknown source kind"):
        load_manifest(manifest)


def test_manifest_rejects_duplicate_ids(tmp_path: Path):
    entry = {"id": "one", "kind": "csv", "path": "a", "exam": "poscomp", "year": 2020}
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps([entry, entry]))
    with pytest.raises(ValueError, match="duplicate source id"):
        load_manifest(manifest)
