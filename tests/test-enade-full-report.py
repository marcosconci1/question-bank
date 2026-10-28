"""Reconciliation checks for the report-only ENADE 2014 full fixture."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pymupdf

from question_bank.validate import load_registered_tags, validate_question

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "scripts" / "adapters" / "enade-cc-pdf.py"
SPEC = importlib.util.spec_from_file_location("enade_cc_pdf", ADAPTER_PATH)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)

REPORT_PATH = ROOT / "reports" / "enade-cc-2014-full.json"
TARGETED_PATH = ROOT / "reports" / "enade-cc-2014-targeted.json"
EXPECTED_HASHES = {
    "prova": "bd3e8436b4d2da2211eaedc4fd6a28a3a2583c0c0b3280aa210cd3d305bcce42",
    "gabarito": "fbd23a3e9e5da2d5f305e4ab6cf705eda42bb2a2bf3f43cb041a752b8a194659",
    "padrao": "35f342eed6e6befc1819edee393cd6e5728d03a89af310a2869e89b4e33fda8d",
}
OBJECTIVE_KEYS = {str(number) for number in range(9, 36)}
DISCURSIVE_KEYS = {"d3", "d4", "d5"}
FULL_REPORT_YEARS = (2005, 2008, 2011, 2014, 2017, 2021)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _crop_sha256(page: pymupdf.Page, bounds: list[float]) -> tuple[str, int, int]:
    rectangle = ADAPTER.normalized_rect(page, tuple(bounds))
    pixmap = page.get_pixmap(clip=rectangle, matrix=pymupdf.Matrix(2, 2), alpha=False)
    return hashlib.sha256(pixmap.tobytes("png")).hexdigest(), pixmap.width, pixmap.height


def test_full_2014_report_reconciles_all_eligible_items_without_writes():
    report = _read_json(REPORT_PATH)
    targeted = _read_json(TARGETED_PATH)
    registered = load_registered_tags(ROOT / "docs" / "tags.md")

    assert report["year"] == 2014
    assert report["emitted"] == 30
    assert report["pending"] == 0
    assert report["inventory"] == {
        "objective_items": 27,
        "discursive_entries": 3,
        "officially_voided_objective": [],
        "officially_voided_discursive": [],
        "eligible_objective": 27,
        "eligible_discursive": 3,
        "eligible_total": 30,
    }
    assert report["accounting"] == {
        "total": 30, "objective": 27, "discursive": 3,
        "parsed": 30, "suspended": 0, "voided": 0,
    }
    assert set(report["items"]) == OBJECTIVE_KEYS | DISCURSIVE_KEYS
    assert len({item["record"]["id"] for item in report["items"].values()}) == 30
    assert report["bank_records_written"] is False
    assert report["import_ready"] is False

    for name, expected_hash in EXPECTED_HASHES.items():
        source = report["source_pdfs"][name]
        source_path = ROOT / source["path"]
        assert source["sha256"] == expected_hash
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == expected_hash

    for key in OBJECTIVE_KEYS:
        item = report["items"][key]
        target_item = targeted["items"][key]
        record = item["record"]
        assert item["status"] == target_item["status"] == "parsed"
        assert item["source_page"] == target_item["source_page"]
        assert item["crops"] == target_item["crops"]
        assert record == target_item["record"]
        assert item["provenance"]["prova_sha256"] == EXPECTED_HASHES["prova"]
        assert item["provenance"]["gabarito_sha256"] == EXPECTED_HASHES["gabarito"]
        assert item["option_order"] == list("ABCDE")
        assert len(record["options"]) == 5
        assert [crop["position"] for crop in item["crops"] if crop["kind"] == "option"] == list("ABCDE")
        option_paths = [
            block["src"]
            for option in record["options"]
            for block in option
            if block["type"] == "image"
        ]
        crop_paths = [crop["path"] for crop in item["crops"] if crop["kind"] == "option"]
        assert option_paths == crop_paths
        assert all(crop["page"] == item["source_page"] for crop in item["crops"])

    with pymupdf.open(ROOT / "data/raw/enade-cc/2014/gabarito.pdf") as key_pdf:
        answers = ADAPTER.parse_gabarito(2014, "\n".join(page.get_text("text") for page in key_pdf))
    assert report["official_answer_key"]["source_sha256"] == EXPECTED_HASHES["gabarito"]
    assert report["official_answer_key"]["verified_answers"] == {
        key: report["items"][key]["record"]["answer"] for key in sorted(OBJECTIVE_KEYS, key=int)
    }
    assert all(report["items"][key]["record"]["answer"] == answers[key] for key in OBJECTIVE_KEYS)

    with pymupdf.open(ROOT / "data/raw/enade-cc/2014/padrao.pdf") as padrao_pdf:
        rubrics = ADAPTER.parse_padrao(2014, "\n".join(page.get_text("text") for page in padrao_pdf))
    expected_rubric_pages = {"d3": [5], "d4": [6, 7], "d5": [8]}
    for key in DISCURSIVE_KEYS:
        item = report["items"][key]
        record = item["record"]
        assert item["status"] == "extracted"
        assert item["provenance"]["prova_sha256"] == EXPECTED_HASHES["prova"]
        assert item["provenance"]["padrao_sha256"] == EXPECTED_HASHES["padrao"]
        assert item["provenance"]["padrao_pages"] == expected_rubric_pages[key]
        assert record["rubric"] == rubrics[key]
        assert len(record["rubric"]) >= 250
        assert any(block["type"] == "text" for block in record["stem"])
        assert set(record["tags"]) <= registered
        validation = validate_question(record, ROOT / "questions" / f"{record['id']}.json", registered)
        assert validation.format_clean, [issue.message for issue in validation.errors]

    for key in OBJECTIVE_KEYS:
        validation = validate_question(
            report["items"][key]["record"],
            ROOT / "questions" / f"{report['items'][key]['record']['id']}.json",
            registered,
        )
        assert validation.format_clean, [issue.message for issue in validation.errors]


def test_full_2014_report_crops_reproduce_from_cited_source_pages():
    report = _read_json(REPORT_PATH)
    with pymupdf.open(ROOT / "data/raw/enade-cc/2014/prova.pdf") as prova:
        for item in report["items"].values():
            record = item["record"]
            crop_paths = {crop["path"] for crop in item["crops"]}
            image_paths = {
                block["src"]
                for value in [record["stem"], *record.get("options", [])]
                for block in (value if isinstance(value, list) else [])
                if isinstance(block, dict) and block.get("type") == "image"
            }
            assert image_paths <= crop_paths
            for crop in item["crops"]:
                assert crop["page"] == item["source_page"]
                path = ROOT / crop["path"]
                assert path.is_file()
                digest, width, height = _crop_sha256(prova[crop["page"] - 1], crop["bounds_normalized"])
                assert digest == crop["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
                assert width == crop["width"] and height == crop["height"]


def test_extraction_progress_marks_2014_full():
    progress = _read_json(ROOT / "reports" / "enade-cc-extraction-progress.json")
    assert progress["per_edition"]["2014"]["full_report"] == "reports/enade-cc-2014-full.json"
    assert progress["per_edition"]["2014"]["full_source_coverage"] is True
    assert progress["per_edition"]["2014"]["target_import_ready"] is False


def test_full_reports_reconcile_all_six_official_manifests_to_176():
    audit = _read_json(ROOT / "reports" / "enade-cc-source-audit.json")
    progress = _read_json(ROOT / "reports" / "enade-cc-extraction-progress.json")
    all_ids = []
    total = 0

    for year in FULL_REPORT_YEARS:
        report = _read_json(ROOT / "reports" / f"enade-cc-{year}-full.json")
        edition = audit["editions"][str(year)]
        progress_edition = progress["per_edition"][str(year)]
        assert report["year"] == year
        assert report["inventory"]["objective_items"] == edition["objective_manifest_count"]
        assert report["inventory"]["discursive_entries"] == len(edition["discursive_manifest_keys"])
        assert report["inventory"].get("officially_voided_objective", []) == [
            int(number) for number in edition["official_voided_objective"]
        ]
        assert report["inventory"]["eligible_total"] == edition["expected_importable_records"]
        assert report["accounting"]["total"] == edition["expected_importable_records"]
        assert report["emitted"] == edition["expected_importable_records"]
        assert report["pending"] == 0
        assert report["bank_records_written"] is False
        assert report["import_ready"] is False
        assert progress_edition["full_report"] == f"reports/enade-cc-{year}-full.json"
        assert progress_edition["full_source_coverage"] is True
        assert progress_edition["full_source_records_verified"] == edition["expected_importable_records"]
        assert progress_edition["target_import_ready"] is False
        all_ids.extend(item["record"]["id"] for item in report["items"].values())
        total += report["emitted"]

    assert total == audit["consolidated"]["expected_importable_record_count"] == 176
    assert len(all_ids) == len(set(all_ids)) == 176
    assert progress["consolidated"]["expected_importable_records"] == 176
    assert progress["consolidated"]["full_source_coverage_editions"] == list(FULL_REPORT_YEARS)
    assert progress["consolidated"]["incomplete_editions"] == []


def test_full_2017_and_2021_reports_match_source_keys_rubrics_and_targeted_items():
    audit = _read_json(ROOT / "reports" / "enade-cc-source-audit.json")
    registered = load_registered_tags(ROOT / "docs" / "tags.md")

    for year in (2017, 2021):
        report = _read_json(ROOT / "reports" / f"enade-cc-{year}-full.json")
        targeted = _read_json(ROOT / "reports" / f"enade-cc-{year}-targeted.json")
        edition = audit["editions"][str(year)]
        expected_objectives = {
            str(number)
            for number in range(9, 36)
            if str(number) not in edition["official_voided_objective"]
        }
        assert set(report["items"]) == expected_objectives | DISCURSIVE_KEYS
        assert len({item["record"]["id"] for item in report["items"].values()}) == len(report["items"])
        assert not (set(report["items"]) & set(edition["official_voided_objective"]))
        assert set(report["official_answer_key"]["verified_answers"]) == {
            str(number) for number in range(9, 36)
        }

        raw_dir = ROOT / "data" / "raw" / "enade-cc" / str(year)
        for source_name, source in report["source_pdfs"].items():
            assert source["sha256"] == edition[f"{source_name}_sha256"]
            assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]

        with pymupdf.open(raw_dir / "gabarito.pdf") as key_pdf:
            answers = ADAPTER.parse_gabarito(year, "\n".join(page.get_text("text") for page in key_pdf))
        assert report["official_answer_key"]["verified_answers"] == {
            str(number): answers[str(number)] for number in range(9, 36)
        }

        with pymupdf.open(raw_dir / "padrao.pdf") as padrao_pdf:
            rubrics = ADAPTER.parse_padrao(year, "\n".join(page.get_text("text") for page in padrao_pdf))
        for key in DISCURSIVE_KEYS:
            item = report["items"][key]
            record = item["record"]
            assert item["status"] == "extracted"
            assert record["rubric"] == rubrics[key]
            assert key in report["official_discursive_rubrics"]
            assert report["official_discursive_rubrics"][key]["record_id"] == record["id"]
            assert set(record["tags"]) <= registered

        for key in expected_objectives:
            item = report["items"][key]
            record = item["record"]
            assert record["type"] == "mc"
            assert record["answer"] == answers[key]
            assert item["option_order"] == list("ABCDE")
            assert len(record["options"]) == 5
            assert set(record["tags"]) <= registered
            assert item["provenance"]["prova_sha256"] == report["source_pdfs"]["prova"]["sha256"]
            assert item["provenance"]["gabarito_sha256"] == report["source_pdfs"]["gabarito"]["sha256"]

        targeted_keys = set(targeted["items"])
        for key in targeted_keys:
            assert report["items"][key]["record"] == targeted["items"][key]["record"]
            assert report["items"][key]["crops"] == targeted["items"][key]["crops"]

        with pymupdf.open(raw_dir / "prova.pdf") as prova:
            for key, item in report["items"].items():
                record = item["record"]
                validation = validate_question(
                    record,
                    ROOT / "questions" / f"{record['id']}.json",
                    registered,
                )
                assert validation.format_clean, [issue.message for issue in validation.errors]
                crop_paths = {crop["path"] for crop in item["crops"]}
                image_paths = {
                    block["src"]
                    for value in [record["stem"], *record.get("options", [])]
                    for block in (value if isinstance(value, list) else [])
                    if isinstance(block, dict) and block.get("type") == "image"
                }
                assert image_paths <= crop_paths
                assert {crop["page"] for crop in item["crops"]} <= set(item["source_pages"])
                for crop in item["crops"]:
                    digest, width, height = _crop_sha256(prova[crop["page"] - 1], crop["bounds_normalized"])
                    path = ROOT / crop["path"]
                    assert path.is_file()
                    assert digest == crop["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
                    assert (width, height) == (crop["width"], crop["height"])


def test_full_2021_uses_source_audited_void_inventory_and_counts():
    report = _read_json(ROOT / "reports" / "enade-cc-2021-full.json")
    assert report["inventory"] == {
        "objective_items": 27,
        "discursive_entries": 3,
        "officially_voided_objective": [29, 33],
        "officially_voided_discursive": [],
        "eligible_objective": 25,
        "eligible_discursive": 3,
        "eligible_total": 28,
    }
    assert report["accounting"] == {
        "total": 28, "objective": 25, "discursive": 3,
        "parsed": 28, "suspended": 0, "voided": 2,
    }
    assert "29" not in report["items"]
    assert "33" not in report["items"]
