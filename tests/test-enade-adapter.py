"""Regression tests for source layouts that differ across ENADE editions."""

import hashlib
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pymupdf
import pytest

from question_bank.validate import load_registered_tags, validate_question

ADAPTER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "adapters" / "enade-cc-pdf.py"
SPEC = importlib.util.spec_from_file_location("enade_cc_pdf", ADAPTER_PATH)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def assert_imported_reports_preserved(root: Path, years: tuple[int, ...]) -> None:
    """Check imported bank files match source reports without curation fields."""
    for year in years:
        report = json.loads(
            (root / "reports" / f"enade-cc-{year}-full.json").read_text(encoding="utf-8")
        )
        assert report["bank_records_written"] is False
        for item in report["items"].values():
            expected = item["record"]
            actual = json.loads(
                (root / "questions" / f"{expected['id']}.json").read_text(encoding="utf-8")
            )
            status = actual.pop("status")
            reason = actual.pop("status_reason", None)
            assert actual == expected
            assert status in {"active", "suspended"}
            assert (bool(reason)) == (status == "suspended")


@pytest.mark.parametrize(
    ("year", "expected_count"),
    [(2005, 29), (2008, 30), (2011, 29), (2014, 30), (2017, 30), (2021, 28)],
    ids=[2005, 2008, 2011, 2014, 2017, 2021],
)
def test_generic_year_normalization_matches_all_audited_editions(tmp_path, monkeypatch, year, expected_count):
    root = ADAPTER.REPO_ROOT
    raw = tmp_path / "raw"
    registered = load_registered_tags(root / "docs" / "tags.md")
    expected_report = json.loads((root / "reports" / f"enade-cc-{year}-full.json").read_text(encoding="utf-8"))
    written_before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "questions").glob("enade-*.json")
    }
    original_read_text = Path.read_text
    mismatches = []

    def forbid_runtime_report_read(path, *args, **kwargs):
        if path.parent.name == "reports" and path.suffix == ".json":
            raise AssertionError("runtime normalization must not read report fixtures")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", forbid_runtime_report_read)
    for name in ("prova", "gabarito", "padrao"):
        source = root / "data" / "raw" / "enade-cc" / str(year) / f"{name}.pdf"
        if not source.exists():
            pytest.skip("pinned ENADE PDFs are required for generic normalization")
        dest = raw / str(year) / f"{name}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())

    cfg = ADAPTER.CONFIGS[year]
    records, rejections, counts = ADAPTER.normalize_year(
        cfg, raw, registered, tmp_path / "assets"
    )
    expected = [item["record"] for item in expected_report["items"].values()]
    if len(records) != expected_count:
        mismatches.append(f"{year}: {len(records)}/{expected_count} records")
    if records != expected:
        mismatches.append(f"{year}: runtime output differs from expected report fixture")
    if any(
        rejection["reason"] in {"parse-error", "missing-answer-key"}
        for rejection in rejections
    ):
        mismatches.append(f"{year}: parse-error or missing-answer-key rejection")

    def rejection_keys(objective, discursive):
        return [str(number) for number in objective] + [
            f"d{number}" if cfg.separate_discursive_numbering else str(number)
            for number in discursive
        ]

    configured_rejections = {
        "out-of-scope-component": rejection_keys(cfg.fg_objective, cfg.fg_discursive),
        "out-of-scope-degree": rejection_keys(cfg.other_degree_objective, cfg.other_degree_discursive),
        "voided": rejection_keys(cfg.voided_objective, cfg.voided_discursive),
    }
    for reason, expected_keys in configured_rejections.items():
        actual_keys = [item["key"] for item in rejections if item["reason"] == reason]
        if sorted(actual_keys) != sorted(expected_keys):
            mismatches.append(f"{year}: {reason} rejection inventory differs")
    if not counts["item_provenance"] or set(counts["source_pdfs"]) != {
        "prova", "gabarito", "padrao"
    }:
        mismatches.append(f"{year}: missing runtime PDF provenance")
    if year == 2005 and "enade-2005-59" not in {record["id"] for record in records}:
        mismatches.append("2005: Q59 absent from PDF-driven output")
    crop_total = 0
    with pymupdf.open(raw / str(year) / "prova.pdf") as source:
        for question_id, provenance in counts["item_provenance"].items():
            if provenance.get("source_sha256") != counts["source_pdfs"]["prova"]["sha256"]:
                mismatches.append(f"{question_id}: runtime source hash differs")
            option_positions = []
            for crop in provenance.get("crops", []):
                relative = Path(crop["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    mismatches.append(f"{question_id}: unsafe crop path {relative}")
                    continue
                replay = ADAPTER.crop_png(
                    source[crop["page"] - 1],
                    tuple(crop["bounds_normalized"]),
                    tmp_path / "replay" / relative,
                )
                if replay["sha256"] != crop["sha256"]:
                    mismatches.append(f"{question_id}: crop hash differs for {relative}")
                if crop.get("kind") == "option":
                    option_positions.append(crop.get("position"))
                crop_total += 1
            if option_positions != sorted(option_positions, key="ABCDE".index):
                mismatches.append(f"{question_id}: option crop order differs")
    if not crop_total:
        mismatches.append(f"{year}: no reproducible runtime crops reported")
    if mismatches:
        pytest.fail("; ".join(mismatches))
    written_after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "questions").glob("enade-*.json")
    }
    assert written_after == written_before


def test_runtime_normalizer_reads_pdf_inputs_without_reading_report_fixtures(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    raw = tmp_path / "raw" / "2005"
    raw.mkdir(parents=True)
    monkeypatch.setattr(ADAPTER, "REPO_ROOT", root)

    for name in ("prova", "gabarito", "padrao"):
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), f"PDF input: {name}")
        document.save(raw / f"{name}.pdf")
        document.close()

    config = ADAPTER.YearConfig(
        2005, (), (), (), (), ocr=True, separate_discursive_numbering=False
    )
    original_read_text = Path.read_text

    def reject_report_fixture(path, *args, **kwargs):
        if path.name.endswith("-full.json"):
            raise AssertionError("runtime normalization must not read report fixtures")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_report_fixture)
    records, rejections, counts = ADAPTER.normalize_year(config, raw.parent, set())

    assert records == []
    assert rejections == []
    assert set(counts["source_pdfs"]) == {"prova", "gabarito", "padrao"}
    assert all(Path(item["path"]).is_file() for item in counts["source_pdfs"].values())
    assert all(len(item["sha256"]) == 64 for item in counts["source_pdfs"].values())
    assert not (raw / ".ocr-cache").exists()


def test_cli_dry_run_uses_and_cleans_temporary_crop_directory(tmp_path, monkeypatch, capsys):
    captured = {}

    def fake_normalize(config, raw_root, registered, asset_output):
        captured["asset_output"] = asset_output
        assert asset_output.is_dir()
        return [], [], {"source_pdfs": {}, "item_provenance": {}}

    monkeypatch.setattr(ADAPTER, "normalize_year", fake_normalize)
    monkeypatch.setattr(
        ADAPTER,
        "write_records",
        lambda *args, **kwargs: pytest.fail("dry-run must not write question records"),
    )
    monkeypatch.setattr(sys, "argv", [str(ADAPTER_PATH), "--year", "2005", "--dry-run"])

    assert ADAPTER.main() == 0
    capsys.readouterr()
    assert not captured["asset_output"].exists()


def test_pdf_driven_2005_q59_matches_audited_record_and_source_provenance():
    root = ADAPTER.REPO_ROOT
    raw = root / "data" / "raw" / "enade-cc"
    if not (raw / "2005" / "prova.pdf").exists():
        pytest.skip("pinned ENADE PDFs are required for generic normalization")

    records, rejections, counts = ADAPTER.normalize_year(
        ADAPTER.CONFIGS[2005], raw, load_registered_tags(root / "docs" / "tags.md")
    )
    record = next(item for item in records if item["id"] == "enade-2005-59")
    expected = json.loads((root / "reports" / "enade-cc-2005-full.json").read_text())
    expected_record = expected["items"]["59"]["record"]
    provenance = counts["item_provenance"]["enade-2005-59"]

    assert record == expected_record
    assert not any(item["key"] == "59" for item in rejections)
    assert provenance["source_page"] == 22
    assert provenance["source_sha256"] == counts["source_pdfs"]["prova"]["sha256"]
    assert [crop["position"] for crop in provenance["crops"] if crop["kind"] == "option"] == list("ABCDE")
    assert all(len(crop["sha256"]) == 64 for crop in provenance["crops"])

def test_all_audited_crops_rerender_to_recorded_hashes(tmp_path, monkeypatch):
    root = ADAPTER.REPO_ROOT
    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)
    total_crops = 0

    for year in ADAPTER.YEARS:
        report = json.loads((root / "reports" / f"enade-cc-{year}-full.json").read_text())
        with pymupdf.open(root / report["source_pdfs"]["prova"]["path"]) as source:
            for key, item in report["items"].items():
                option_positions = []
                for crop in item.get("crops", []):
                    assert crop["page"] in item.get("source_pages", [item.get("source_page")])
                    x0, y0, x1, y1 = crop["bounds_normalized"]
                    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
                    assert crop["path"].startswith("assets/")
                    if crop.get("kind") == "option":
                        assert crop.get("position") in "ABCDE"
                        option_positions.append(crop["position"])
                    replay = ADAPTER.crop_png(
                        source[crop["page"] - 1],
                        tuple(crop["bounds_normalized"]),
                        tmp_path / crop["path"],
                    )
                    assert replay["sha256"] == crop["sha256"], (year, key, crop["path"])
                    total_crops += 1
                assert option_positions == sorted(option_positions, key="ABCDE".index)

    assert total_crops > 250


def test_option_labels_can_be_alone_or_share_a_line_with_the_option():
    body = """QUESTÃO 10
Enunciado completo.
A)
Primeira alternativa.
B)
Segunda alternativa.
C)
Terceira alternativa.
D)
Quarta alternativa.
E)
Quinta alternativa."""

    stem, options = ADAPTER.split_options(body)

    assert stem == "QUESTÃO 10 Enunciado completo."
    assert options == [
        "Primeira alternativa.",
        "Segunda alternativa.",
        "Terceira alternativa.",
        "Quarta alternativa.",
        "Quinta alternativa.",
    ]


def test_2005_rubric_heading_without_dash_is_recognized():
    rubrics = ADAPTER.parse_padrao(
        2005,
        "QUESTÃO - 39 rubric 39\nQUESTÃO 55 rubric 55\nQUESTÃO - 70 anulada",
    )

    assert rubrics["55"] == "rubric 55"
    assert "anulada" in rubrics["70"].casefold()
    assert 70 in ADAPTER.CONFIGS[2005].voided_discursive


def test_import_gate_rejects_incomplete_extraction_and_unmapped_graphics():
    cfg = ADAPTER.CONFIGS[2011]
    expected = (
        len(cfg.ce_objective) - len(cfg.voided_objective)
        + len(cfg.ce_discursive) - len(cfg.voided_discursive)
    )
    complete_records = [{} for _ in range(expected)]

    assert not ADAPTER.year_is_complete(cfg, complete_records[:-1], [], images_mapped=True)
    assert not ADAPTER.year_is_complete(cfg, complete_records, [], images_mapped=False)
    assert not ADAPTER.year_is_complete(
        cfg,
        complete_records,
        [{"reason": "missing-answer-key", "key": "d3"}],
        images_mapped=True,
    )

    complete_rejections = [
        {"reason": reason, "key": key}
        for reason, keys in ADAPTER.configured_rejection_keys(cfg).items()
        for key in keys
    ]
    assert ADAPTER.year_is_complete(cfg, complete_records, complete_rejections, images_mapped=True)
    assert not ADAPTER.year_is_complete(cfg, complete_records, complete_rejections[:-1], images_mapped=True)
    assert not ADAPTER.year_is_complete(
        cfg,
        complete_records,
        complete_rejections + [complete_rejections[0]],
        images_mapped=True,
    )


def test_normalized_crop_generation_is_byte_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)
    document = pymupdf.open()
    page = document.new_page(width=100, height=100)
    page.draw_rect(pymupdf.Rect(20, 20, 80, 80), color=(0, 0, 0), fill=(1, 1, 1))
    first = ADAPTER.crop_png(page, (0.1, 0.1, 0.9, 0.9), tmp_path / "assets" / "first.png")
    second = ADAPTER.crop_png(page, (0.1, 0.1, 0.9, 0.9), tmp_path / "assets" / "second.png")
    explicit = ADAPTER.crop_png(
        page, (0.1, 0.1, 0.9, 0.9), tmp_path / "temporary-crops" / "third.png"
    )
    document.close()

    assert (tmp_path / "assets" / "first.png").read_bytes() == (tmp_path / "assets" / "second.png").read_bytes()
    assert first["bounds_normalized"] == [0.1, 0.1, 0.9, 0.9]
    assert first["sha256"] == second["sha256"]
    assert first["page"] == 1
    assert first["width"] > 0 and first["height"] > 0
    assert (tmp_path / "temporary-crops" / "third.png").is_file()
    assert explicit["path"] == "temporary-crops/third.png"


def test_targeted_2014_fixture_records_validate_with_exact_a_to_e_order():
    root = ADAPTER.REPO_ROOT
    report = json.loads((root / "reports" / "enade-cc-2014-targeted.json").read_text(encoding="utf-8"))
    registered = load_registered_tags(root / "docs" / "tags.md")

    assert report["expected_unresolved"] == 27
    assert report["emitted"] == 27
    assert report["pending"] == 0
    assert report["accounting"] == {"total": 27, "parsed": 27, "suspended": 0}
    assert report["batch"]["expected_count"] == 27
    assert report["batch"]["parsed_count"] == 27
    assert report["batch"]["suspended_count"] == 0
    assert report["bank_records_written"] is False
    expected_pages = {
        9: 12, 10: 13, 11: 13, 12: 14, 13: 15, 14: 15, 15: 15,
        16: 16, 17: 17, 18: 17, 19: 18, 20: 18, 21: 19, 22: 20,
        23: 20, 24: 20, 25: 21, 26: 22, 27: 22, 28: 23, 29: 23,
        30: 24, 31: 24, 32: 25, 33: 25, 34: 26, 35: 27,
    }
    for number, expected_page in expected_pages.items():
        item = report["items"][str(number)]
        record = item["record"]
        result = validate_question(record, root / "questions" / f"{record['id']}.json", registered)
        assert item["status"] == "parsed"
        assert item["source_status"] == "extracted"
        assert item["source_page"] == expected_page
        assert record["answer"] == report["official_answer_key"]["verified_answers"][str(number)]
        assert record["tags"] and set(record["tags"]) <= registered
        assert item["option_order"] == list("ABCDE")
        assert len(record["options"]) == 5
        assert [option[-1]["src"] for option in record["options"]] == [
            f"assets/enade-2014-q{number:02d}-option-{letter.lower()}.png" for letter in "ABCDE"
        ]
        assert result.format_clean
        assert all((root / crop["path"]).is_file() for crop in item["crops"])
        assert all(crop["page"] == item["source_page"] for crop in item["crops"])

    assert report["items"]["9"]["record"]["stem"][1]["type"] == "image"
    assert report["items"]["13"]["record"]["stem"][1]["type"] == "image"
    assert report["items"]["35"]["record"]["stem"][1]["type"] == "image"
    assert report["items"]["9"]["crops"][0]["kind"] == "stem-figure"
    assert report["items"]["13"]["crops"][0]["kind"] == "stem-figure"
    assert report["items"]["35"]["crops"][0]["kind"] == "stem-figure"
    assert report["official_answer_key"]["source_pdf"] == "data/raw/enade-cc/2014/gabarito.pdf"
    assert len(report["official_answer_key"]["verified_answers"]) == 27
    assert all(item["accounting_status"] == "parsed" for item in report["items"].values())
    assert report["items"]["32"]["record"]["stem"][0]["content"].count("→") >= 1
    assert all(block["type"] == "image" for block in report["items"]["27"]["record"]["options"][0])
    assert any(block["type"] == "text" for block in report["items"]["24"]["record"]["options"][0])
    batch = json.loads((root / "reports" / "enade-cc-2014-batch-10-15.json").read_text(encoding="utf-8"))
    assert batch["batch"]["expected_items"] == ["10", "11", "12", "13", "14", "15"]
    assert batch["batch"]["expected_count"] == batch["batch"]["parsed_count"] == 6
    assert batch["batch"]["suspended_count"] == 0
    assert_imported_reports_preserved(root, (2014,))


def test_2014_q17_q23_batch_report_is_source_backed_and_reconciled():
    root = ADAPTER.REPO_ROOT
    report = json.loads(
        (root / "reports" / "enade-cc-2014-batch-17-23.json").read_text(encoding="utf-8")
    )
    registered = load_registered_tags(root / "docs" / "tags.md")
    expected_answers = {"17": "A", "18": "E", "19": "A", "20": "E", "21": "B", "22": "E", "23": "D"}
    expected_pages = {"17": 17, "18": 17, "19": 18, "20": 18, "21": 19, "22": 20, "23": 20}

    assert report["expected_unresolved"] == 27
    assert report["emitted"] == 18
    assert report["pending"] == 9
    assert report["import_ready"] is False
    assert report["bank_records_written"] is False
    assert report["official_answer_key"]["source_pdf"] == "data/raw/enade-cc/2014/gabarito.pdf"
    assert report["official_answer_key"]["verified_answers"] == expected_answers
    assert report["batch"]["expected_items"] == list(expected_answers)
    assert report["batch"]["expected_count"] == report["batch"]["parsed_count"] == 7
    assert report["batch"]["suspended_count"] == 0

    for number, answer in expected_answers.items():
        item = report["items"][number]
        record = item["record"]
        assert item["status"] == "extracted"
        assert item["source_page"] == expected_pages[number]
        assert item["option_order"] == list("ABCDE")
        assert record["answer"] == answer
        assert record["tags"] and set(record["tags"]) <= registered
        assert validate_question(
            record, root / "questions" / f"{record['id']}.json", registered
        ).format_clean
        assert [blocks[-1]["src"] for blocks in record["options"]] == [
            f"assets/enade-2014-q{int(number):02d}-option-{letter.lower()}.png"
            for letter in "ABCDE"
        ]
        option_positions = []
        for crop in item["crops"]:
            assert crop["page"] == expected_pages[number]
            x0, y0, x1, y1 = crop["bounds_normalized"]
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
            crop_path = root / crop["path"]
            assert crop_path.is_file()
            assert hashlib.sha256(crop_path.read_bytes()).hexdigest() == crop["sha256"]
            if crop["kind"] == "option":
                option_positions.append(crop["position"])
        assert option_positions == list("ABCDE")

    assert_imported_reports_preserved(root, (2014,))


def test_adapter_import_guard_does_not_write_question_records():
    root = ADAPTER.REPO_ROOT
    before = sorted(path.name for path in (root / "questions").glob("enade-2014-*.json"))
    assets_before = {
        path.name: path.read_bytes() for path in (root / "assets").glob("enade-2014-*.png")
    }
    runpy.run_path(str(ADAPTER_PATH))
    after = sorted(path.name for path in (root / "questions").glob("enade-2014-*.json"))
    assets_after = {
        path.name: path.read_bytes() for path in (root / "assets").glob("enade-2014-*.png")
    }
    assert after == before
    assert assets_after == assets_before


def test_remaining_non_2017_targets_have_exact_order_keys_and_reproducible_crops(tmp_path, monkeypatch):
    root = ADAPTER.REPO_ROOT
    expected = {
        2005: {"59": ("C", [22])},
        2008: {"14": ("E", [8, 9]), "18": ("C", [9]), "25": ("E", [12]), "38": ("E", [15])},
        2011: {"10": ("E", [9])},
        2021: {"14": ("C", [23]), "35": ("D", [43])},
    }
    registered = load_registered_tags(root / "docs" / "tags.md")
    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)

    for year, questions in expected.items():
        report = json.loads((root / "reports" / f"enade-cc-{year}-targeted.json").read_text(encoding="utf-8"))
        assert report["accounting"] == {"expected": len(questions), "parsed": len(questions), "suspended": 0}
        assert report["bank_records_written"] is False
        assert report["import_ready"] is False
        assert set(report["items"]) == set(questions)
        assert report["source_sha256"] == hashlib.sha256((root / report["source_pdf"]).read_bytes()).hexdigest()
        key_path = root / report["official_answer_key"]["source_pdf"]
        assert report["official_answer_key"]["source_sha256"] == hashlib.sha256(key_path.read_bytes()).hexdigest()

        with pymupdf.open(root / report["source_pdf"]) as source:
            with pymupdf.open(key_path) as key_document:
                source_answers = ADAPTER.parse_gabarito(
                    year, "\n".join(page.get_text("text") for page in key_document)
                )
            for number, (answer, source_pages) in questions.items():
                item = report["items"][number]
                record = item["record"]
                assert item["status"] == "extracted"
                assert item["source_pages"] == source_pages
                assert item["option_order"] == list("ABCDE")
                assert record["answer"] == answer
                assert record["answer"] == source_answers[number]
                assert record["answer"] == report["official_answer_key"]["verified_answers"][number]
                assert record["tags"] and set(record["tags"]) <= registered
                assert len(record["options"]) == 5
                assert validate_question(
                    record, root / "questions" / f"{record['id']}.json", registered
                ).format_clean

                option_crops = [crop for crop in item["crops"] if crop["kind"] == "option"]
                assert [crop["position"] for crop in option_crops] == list("ABCDE")
                for crop in item["crops"]:
                    source_page = source[crop["page"] - 1]
                    original = root / crop["path"]
                    assert original.is_file()
                    assert hashlib.sha256(original.read_bytes()).hexdigest() == crop["sha256"]
                    replay = ADAPTER.crop_png(
                        source_page,
                        tuple(crop["bounds_normalized"]),
                        tmp_path / crop["path"],
                    )
                    assert replay["sha256"] == crop["sha256"]
                    assert [replay["width"], replay["height"]] == [crop["width"], crop["height"]]

                for option, crop in zip(record["options"], option_crops):
                    image = next(block for block in option if block["type"] == "image")
                    assert image["src"] == crop["path"]

    assert_imported_reports_preserved(root, tuple(expected))


def test_2017_targeted_batch_has_source_backed_order_keys_tags_and_reproducible_crops(tmp_path, monkeypatch):
    root = ADAPTER.REPO_ROOT
    extractor_path = root / "scripts" / "extract-enade-2017-targeted.py"
    extractor_spec = importlib.util.spec_from_file_location("extract_enade_2017_targeted", extractor_path)
    assert extractor_spec and extractor_spec.loader
    extractor = importlib.util.module_from_spec(extractor_spec)
    extractor_spec.loader.exec_module(extractor)
    report = json.loads((root / "reports" / "enade-cc-2017-targeted.json").read_text(encoding="utf-8"))
    registered = load_registered_tags(root / "docs" / "tags.md")
    expected_numbers = {str(number) for number in range(9, 36)}
    source_path = root / report["source_pdf"]
    key_path = root / report["official_answer_key"]["source_pdf"]

    assert report["accounting"] == {"expected": 27, "parsed": 27, "suspended": 0}
    assert report["bank_records_written"] is False
    assert report["import_ready"] is False
    assert set(report["items"]) == expected_numbers
    assert report["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert report["official_answer_key"]["source_sha256"] == hashlib.sha256(key_path.read_bytes()).hexdigest()
    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)

    with pymupdf.open(source_path) as source, pymupdf.open(key_path) as key_document:
        answers = ADAPTER.parse_gabarito(2017, "\n".join(page.get_text("text") for page in key_document))
        for number in sorted(expected_numbers, key=int):
            item = report["items"][number]
            record = item["record"]
            assert item["status"] == "extracted"
            assert item["option_order"] == list("ABCDE")
            assert record["answer"] == answers[number]
            assert record["answer"] == report["official_answer_key"]["verified_answers"][number]
            assert record["tags"] and set(record["tags"]) <= registered
            assert any(block["type"] == "text" for block in record["stem"])
            assert len(record["options"]) == 5
            assert validate_question(record, root / "questions" / f"{record['id']}.json", registered).format_clean
            if number != "9":
                assert record["options"] == [
                    [{"type": "text", "content": text}] for text in extractor.TEXT_OPTIONS[int(number)]
                ]

            option_crops = [crop for crop in item["crops"] if crop["kind"] == "option"]
            assert [crop["position"] for crop in option_crops] == (list("ABCDE") if number == "9" else [])
            for crop in item["crops"]:
                assert crop["page"] == item["source_page"]
                original = root / crop["path"]
                assert original.is_file()
                assert hashlib.sha256(original.read_bytes()).hexdigest() == crop["sha256"]
                replay = ADAPTER.crop_png(
                    source[crop["page"] - 1], tuple(crop["bounds_normalized"]), tmp_path / crop["path"]
                )
                assert replay["sha256"] == crop["sha256"]
                assert [replay["width"], replay["height"]] == [crop["width"], crop["height"]]

            if number == "9":
                for option, crop in zip(record["options"], option_crops):
                    image = next(block for block in option if block["type"] == "image")
                    assert image["src"] == crop["path"]
            else:
                assert all(any(block["type"] == "text" for block in option) for option in record["options"])

    assert_imported_reports_preserved(root, (2017,))


def test_extraction_progress_marks_completed_full_source_editions():
    root = ADAPTER.REPO_ROOT
    progress = json.loads((root / "reports" / "enade-cc-extraction-progress.json").read_text(encoding="utf-8"))
    assert progress["per_edition"]["2005"]["source_backed_objective_records_verified"] == 28
    assert progress["per_edition"]["2005"]["source_backed_discursive_records_verified"] == 1
    assert progress["per_edition"]["2005"]["full_source_coverage"] is True
    assert progress["per_edition"]["2008"]["source_backed_objective_records_verified"] == 27
    assert progress["per_edition"]["2008"]["source_backed_discursive_records_verified"] == 3
    assert progress["per_edition"]["2008"]["full_source_coverage"] is True
    assert progress["per_edition"]["2011"]["source_backed_objective_records_verified"] == 26
    assert progress["per_edition"]["2011"]["source_backed_discursive_records_verified"] == 3
    assert progress["per_edition"]["2011"]["full_source_coverage"] is True
    assert progress["per_edition"]["2011"]["voided_objective"] == 13
    assert progress["per_edition"]["2014"]["source_backed_objective_records_verified"] == 27
    assert progress["per_edition"]["2014"]["source_backed_discursive_records_verified"] == 3
    assert progress["per_edition"]["2014"]["full_source_records_verified"] == 30
    assert progress["per_edition"]["2014"]["full_source_coverage"] is True
    assert progress["per_edition"]["2017"]["source_backed_objective_records_verified"] == 27
    assert progress["per_edition"]["2017"]["remaining_target_count"] == 0
    assert progress["per_edition"]["2017"]["full_source_records_verified"] == 30
    assert progress["per_edition"]["2017"]["source_backed_discursive_records_verified"] == 3
    assert progress["per_edition"]["2021"]["source_backed_objective_records_verified"] == 25
    assert progress["per_edition"]["2021"]["full_source_records_verified"] == 28
    assert progress["per_edition"]["2021"]["source_backed_discursive_records_verified"] == 3
    assert progress["per_edition"]["2021"]["voided_objective"] == [29, 33]
    assert progress["consolidated"]["source_backed_objective_records_verified"] == 160
    assert progress["consolidated"]["source_backed_discursive_records_verified"] == 16
    assert progress["consolidated"]["full_source_coverage_editions"] == [2005, 2008, 2011, 2014, 2017, 2021]
    assert progress["consolidated"]["incomplete_editions"] == []
    assert progress["consolidated"]["remaining_target_objective_count"] == 0
    assert progress["consolidated"]["remaining_targets"] == {}
    assert progress["consolidated"]["bank_records_written"] is False
    assert progress["consolidated"]["import_ready"] is False


def test_enade_2008_full_report_is_source_backed_and_report_only(tmp_path, monkeypatch):
    root = ADAPTER.REPO_ROOT
    report = json.loads((root / "reports" / "enade-cc-2008-full.json").read_text(encoding="utf-8"))
    targeted = json.loads((root / "reports" / "enade-cc-2008-targeted.json").read_text(encoding="utf-8"))
    registered = load_registered_tags(root / "docs" / "tags.md")
    objective_numbers = list(range(11, 20)) + list(range(21, 39))
    expected_keys = {str(number) for number in objective_numbers} | {"20", "39", "40"}
    expected_pages = {
        **{str(number): 8 for number in (11, 12, 13, 14)},
        **{str(number): 9 for number in (15, 16, 17, 18)},
        "19": 10,
        **{str(number): 11 for number in (21, 22, 23)},
        **{str(number): 12 for number in (24, 25)},
        **{str(number): 13 for number in (26, 27, 28, 29, 30)},
        **{str(number): 14 for number in (31, 32, 33, 34)},
        **{str(number): 15 for number in (35, 36, 37, 38)},
        "20": 10, "39": 16, "40": 17,
    }
    expected_hashes = {
        "prova": "5c8a08f7fdaccaa3b5661f40705e214bffdab634b845bce6288f8eeaa25db264",
        "gabarito": "707a326330c6982a9368957c6d9af1563b886d32d6c6720319faeb71803f2425",
        "padrao": "7021d115731ddcbad3c227da50f6d8c9c2c7f8a5a4b4d7dabce4b3726d0d35ef",
    }
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
    assert report["emitted"] == 30 and report["pending"] == 0
    assert set(report["items"]) == expected_keys
    assert len({item["record"]["id"] for item in report["items"].values()}) == 30
    assert set(report["items"]).isdisjoint({"9", "10", "41", "44", "59", "60", "79", "80"})
    assert report["bank_records_written"] is False and report["import_ready"] is False

    for name, digest in expected_hashes.items():
        source = root / "data" / "raw" / "enade-cc" / "2008" / f"{name}.pdf"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        assert report["source_pdfs"][name] == {"path": f"data/raw/enade-cc/2008/{name}.pdf", "sha256": digest}

    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)
    with pymupdf.open(root / "data/raw/enade-cc/2008/prova.pdf") as prova, \
         pymupdf.open(root / "data/raw/enade-cc/2008/gabarito.pdf") as key_pdf, \
         pymupdf.open(root / "data/raw/enade-cc/2008/padrao.pdf") as padrao_pdf:
        answers = ADAPTER.parse_gabarito(2008, "\n".join(page.get_text("text") for page in key_pdf))
        rubrics = ADAPTER.parse_padrao(2008, "\n".join(page.get_text("text") for page in padrao_pdf))
        assert report["official_answer_key"]["verified_answers"] == {
            str(number): answers[str(number)] for number in objective_numbers
        }
        assert set(report["official_discursive_rubrics"]) == {"20", "39", "40"}

        for number, item in report["items"].items():
            record = item["record"]
            assert item["status"] == "extracted"
            assert record["year"] == 2008 and record["component"] == "specific"
            assert record["course"] == "computer-science"
            assert item["source_page"] in item["source_pages"]
            assert item["source_page"] == expected_pages[number]
            assert record["tags"] and set(record["tags"]) <= registered
            assert validate_question(record, root / "questions" / f"{record['id']}.json", registered).format_clean
            provenance = item["provenance"]
            assert provenance["prova_sha256"] == expected_hashes["prova"]
            assert provenance["prova_pdf"] == "data/raw/enade-cc/2008/prova.pdf"

            if number in targeted["items"]:
                assert number in ("14", "18", "25", "38")
                assert record == targeted["items"][number]["record"]
            if number in {str(value) for value in objective_numbers}:
                assert record["type"] == "mc"
                assert item["option_order"] == list("ABCDE")
                assert len(record["options"]) == 5
                assert record["answer"] == answers[number] == report["official_answer_key"]["verified_answers"][number]
                assert provenance["gabarito_sha256"] == expected_hashes["gabarito"]
                for option in record["options"]:
                    assert option
                    assert any(block["type"] == "image" or block.get("content", "").strip() for block in option)
            else:
                assert record["type"] == "discursive"
                assert "options" not in record and "answer" not in record
                assert record["rubric"] == rubrics[number]
                assert provenance["padrao_sha256"] == expected_hashes["padrao"]
                rubric_provenance = report["official_discursive_rubrics"][number]
                assert rubric_provenance["record_id"] == record["id"]
                assert rubric_provenance["source_sha256"] == expected_hashes["padrao"]
                assert rubric_provenance["source_page"] == provenance["padrao_page"]

            for crop in item["crops"]:
                assert crop["page"] in item["source_pages"]
                x0, y0, x1, y1 = crop["bounds_normalized"]
                assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
                crop_path = root / crop["path"]
                assert crop_path.is_file()
                assert hashlib.sha256(crop_path.read_bytes()).hexdigest() == crop["sha256"]
                replay = ADAPTER.crop_png(
                    prova[crop["page"] - 1], tuple(crop["bounds_normalized"]), tmp_path / crop["path"]
                )
                assert replay["sha256"] == crop["sha256"]
                assert [replay["width"], replay["height"]] == [crop["width"], crop["height"]]
            image_sources = {
                block["src"]
                for block in record.get("stem", []) + [block for option in record.get("options", []) for block in option]
                if block["type"] == "image"
            }
            assert image_sources == {crop["path"] for crop in item["crops"]}

    assert_imported_reports_preserved(root, (2008,))


def test_enade_2005_full_report_is_source_backed_and_report_only(tmp_path, monkeypatch):
    root = ADAPTER.REPO_ROOT
    report = json.loads((root / "reports" / "enade-cc-2005-full.json").read_text(encoding="utf-8"))
    registered = load_registered_tags(root / "docs" / "tags.md")
    expected_objectives = list(range(41, 55)) + list(range(56, 70))
    expected_keys = {str(number) for number in expected_objectives} | {"55"}
    expected_pages = {
        **{str(number): 16 for number in (41, 42)},
        **{str(number): 17 for number in range(43, 48)},
        **{str(number): 18 for number in range(48, 53)},
        "53": 19, "54": 19, "55": 20,
        "56": 21, "57": 21, "58": 21, "59": 22,
        "60": 23, "61": 23, "62": 23,
        "63": 24, "64": 24, "65": 24, "66": 24,
        "67": 25, "68": 26, "69": 26,
    }
    expected_hashes = {
        "prova": "ba95b66e95b6a4071a970f794e0b0c71aeebf18740b95b6ca02dfcb72d0be76c",
        "gabarito": "8d06e732aa0e69dd82325adaec2f6200f664557d92df146af5ccf0cebd13ec09",
        "padrao": "f68a5fab4aa09c9875919a51e75b3b10e96e18b5b3ee9418267e425976686627",
    }
    assert report["inventory"]["eligible_total"] == 29
    assert report["inventory"]["eligible_objective"] == 28
    assert report["inventory"]["eligible_discursive"] == 1
    assert report["accounting"] == {
        "total": 29, "objective": 28, "discursive": 1,
        "parsed": 29, "suspended": 0, "voided": 1,
    }
    assert set(report["items"]) == expected_keys
    assert len({item["record"]["id"] for item in report["items"].values()}) == 29
    assert "70" not in report["items"]
    void = report["inventory"]["officially_voided_discursive"][0]
    assert (void["key"], void["status"], void["source_page"]) == ("70", "voided", 4)
    assert len(report["official_answer_key"]["verified_answers"]) == 28
    assert report["official_answer_key"]["verified_answers"] == {
        str(number): report["items"][str(number)]["record"]["answer"] for number in expected_objectives
    }
    assert report["official_discursive_rubric"]["record_id"] == "enade-2005-55"
    assert report["bank_records_written"] is False and report["import_ready"] is False

    for name, expected_hash in expected_hashes.items():
        source = root / "data" / "raw" / "enade-cc" / "2005" / f"{name}.pdf"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_hash
        assert report["source_pdfs"][name]["sha256"] == expected_hash

    for key, item in report["items"].items():
        record = item["record"]
        assert record["year"] == 2005
        assert record["component"] == "specific"
        assert record["course"] == "computer-science"
        assert item["source_page"] == expected_pages[key]
        assert item["source_page"] in item["source_pages"]
        assert f"page {item['source_page']}" in record["source"]
        assert record["tags"] and set(record["tags"]) <= registered
        stem_text = " ".join(block.get("content", "") for block in record["stem"] if block["type"] == "text")
        assert len(stem_text) > 80
        assert validate_question(record, root / "questions" / f"{record['id']}.json", registered).format_clean
        assert all((root / block["src"]).is_file() for block in record["stem"] if block["type"] == "image")
        if record["type"] == "mc":
            assert item["option_order"] == list("ABCDE")
            assert len(record["options"]) == 5
            assert record["answer"] == report["official_answer_key"]["verified_answers"][key]
            for option in record["options"]:
                assert option
                assert all((root / block["src"]).is_file() for block in option if block["type"] == "image")
                assert any(block["type"] == "image" or (block["type"] == "text" and block["content"].strip()) for block in option)
            option_crops = [crop for crop in item["crops"] if crop["kind"] == "option"]
            if option_crops:
                assert [crop["position"] for crop in option_crops] == list("ABCDE")
                assert [record["options"][n][-1]["src"] for n in range(5)] == [crop["path"] for crop in option_crops]
        else:
            assert key == "55" and record["type"] == "discursive"
            assert len(record["rubric"]) > 1000
            assert "options" not in record and "answer" not in record
            assert "item a)" not in stem_text.lower() and "rascunho" not in stem_text.lower()
        if key == "53":
            assert "signal(cheio), wait(cheio), wait(mutex)" in record["options"][0][0]["content"]
            assert "signal(vazio), wait(vazio), signal(mutex)" in record["options"][1][0]["content"]
        if key == "64":
            assert record["options"][2] == [{"type": "text", "content": "I, II e IV."}]
        for crop in item["crops"]:
            payload = (root / crop["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == crop["sha256"]
            assert crop["page"] == item["source_page"]
            assert len(crop["bounds_normalized"]) == 4

    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)
    with pymupdf.open(root / "data" / "raw" / "enade-cc" / "2005" / "prova.pdf") as source:
        for item in report["items"].values():
            for crop in item["crops"]:
                replay = ADAPTER.crop_png(
                    source[crop["page"] - 1], tuple(crop["bounds_normalized"]),
                    tmp_path / crop["path"],
                )
                assert replay["sha256"] == crop["sha256"]
                assert [replay["width"], replay["height"]] == [crop["width"], crop["height"]]

    assert_imported_reports_preserved(root, (2005,))


def test_enade_2011_full_report_has_exact_nonvoid_inventory_and_replayable_sources(tmp_path, monkeypatch):
    root = ADAPTER.REPO_ROOT
    report = json.loads((root / "reports" / "enade-cc-2011-full.json").read_text(encoding="utf-8"))
    registered = load_registered_tags(root / "docs" / "tags.md")
    expected_hashes = {
        "prova": "eb3b497f0d0967b1b6d063784c3012e719d1758ba182e4f6d6e6e47151934548",
        "gabarito": "e799cac6ced431c0e5341e583592568d28db66e0e0c43c2f2e7757bdd807577b",
        "padrao": "386353635a8e2fa8081dce177f37918bcaf9426d8ee6881b88aa739bdf0cd412",
    }
    expected_keys = {str(number) for number in (*range(9, 13), *range(14, 31), *range(36, 41))}
    expected_keys.update(("d3", "d4", "d5"))

    assert report["inventory"] == {
        "objective_items": 27, "discursive_entries": 3,
        "officially_voided_objective": [13], "officially_voided_discursive": [],
        "eligible_objective": 26, "eligible_discursive": 3, "eligible_total": 29,
    }
    assert set(report["items"]) == expected_keys
    assert "13" not in report["items"]
    assert report["official_void_evidence"]["answer_key_text"] == "13 ANULADA"
    assert report["official_void_evidence"]["answer_key_sha256"] == expected_hashes["gabarito"]
    assert report["accounting"] == {
        "total": 29, "objective": 26, "discursive": 3,
        "parsed": 29, "suspended": 0, "voided": 1,
    }
    assert report["emitted"] == 29 and report["pending"] == 0
    assert report["bank_records_written"] is False and report["import_ready"] is False
    assert {name: source["sha256"] for name, source in report["source_pdfs"].items()} == expected_hashes
    assert set(report["official_answer_key"]["verified_answers"]) == expected_keys - {"d3", "d4", "d5"}
    assert set(report["official_discursive_rubrics"]) == {"d3", "d4", "d5"}

    monkeypatch.setattr(ADAPTER, "REPO_ROOT", tmp_path)
    with pymupdf.open(root / "data" / "raw" / "enade-cc" / "2011" / "prova.pdf") as prova:
        for key, item in report["items"].items():
            record = item["record"]
            assert record["id"] == f"enade-2011-{key}"
            assert record["tags"] and set(record["tags"]) <= registered
            assert validate_question(
                record, root / "questions" / f"{record['id']}.json", registered
            ).format_clean
            assert item["provenance"]["prova_sha256"] == expected_hashes["prova"]
            if record["type"] == "mc":
                assert item["option_order"] == list("ABCDE")
                assert len(record["options"]) == 5
                assert record["answer"] == report["official_answer_key"]["verified_answers"][key]
                assert item["provenance"]["gabarito_sha256"] == expected_hashes["gabarito"]
            else:
                rubric = report["official_discursive_rubrics"][key]
                assert record["rubric"] and len(record["rubric"]) > 100
                assert item["provenance"]["padrao_page"] == rubric["source_page"]
                assert item["provenance"]["padrao_sha256"] == expected_hashes["padrao"]
            for crop in item["crops"]:
                payload = (root / crop["path"]).read_bytes()
                assert hashlib.sha256(payload).hexdigest() == crop["sha256"]
                assert crop["page"] in item["source_pages"]
                assert len(crop["bounds_normalized"]) == 4
                replay = ADAPTER.crop_png(
                    prova[crop["page"] - 1], tuple(crop["bounds_normalized"]), tmp_path / crop["path"]
                )
                assert replay["sha256"] == crop["sha256"]
                assert [replay["width"], replay["height"]] == [crop["width"], crop["height"]]

    assert_imported_reports_preserved(root, (2011,))
