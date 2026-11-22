from pathlib import Path

import pytest

from app.extraction import ExtractionRequest, Page
from app.providers.tesseract import (
    TesseractBaselineProvider, TesseractOcr, lines_from_data, parse_labelled_lines, tesseract_available,
)

IMAGE_PAGE = Page(number=1, image_bytes=b"png-bytes", media_type="image/png")


def _data(words):
    """Build a pytesseract image_to_data dict from (line_no, text, conf) tuples."""
    return {"block_num": [1] * len(words), "par_num": [1] * len(words),
            "line_num": [w[0] for w in words], "text": [w[1] for w in words], "conf": [w[2] for w in words]}


SURVEY_SHEET = _data([(1, "SURVEY", 95), (1, "PLAN", 93), (2, "Survey", 90), (2, "No.:", 88), (2, "154/2", 92),
                      (3, "Total", 91), (3, "area:", 90), (3, "3000", 85), (3, "sq.", 80), (3, "m.", 75),
                      (4, "", -1)])


def test_lines_group_words_and_average_confidence():
    lines = lines_from_data(SURVEY_SHEET)
    assert lines[1] == ("Survey No.: 154/2", pytest.approx(0.90))
    assert len(lines) == 3   # the empty -1 entry is dropped


def test_ocr_returns_text_and_mean_word_confidence():
    ocr = TesseractOcr(image_to_data=lambda image: SURVEY_SHEET, open_image=lambda b: b)
    result = ocr.ocr("D-1", IMAGE_PAGE)
    assert "Survey No.: 154/2" in result.text
    assert result.confidence == pytest.approx(sum([95, 93, 90, 88, 92, 91, 90, 85, 80, 75]) / 10 / 100)


def test_ocr_with_no_words_has_zero_confidence():
    ocr = TesseractOcr(image_to_data=lambda image: _data([]), open_image=lambda b: b)
    assert ocr.ocr("D-1", IMAGE_PAGE).confidence == 0.0


def test_text_page_passes_through_unchanged():
    ocr = TesseractOcr(image_to_data=lambda image: pytest.fail("should not OCR text"), open_image=lambda b: b)
    assert ocr.ocr("D-1", Page(number=1, text="Name: X")).text == "Name: X"


@pytest.mark.parametrize("line, field, value", [
    ("Occupant: Lata Shirodkar", "name", "Lata Shirodkar"),
    ("Name : PRAKASH KAMATH", "name", "PRAKASH KAMATH"),
    ("Name of holder: Rohan Naik", "name", "Rohan Naik"),        # Form I & XIV label (synthetic)
    ("Name of the occupant: Rohan Naik", "name", "Rohan Naik"),
    ("Survey No.: 154/2", "survey_number", "154/2"),
    ("Valid upto: 31/03/2031", "expiry_date", "2031-03-31"),
    ("Issued: 01/10/2026", "issue_date", "2026-10-01"),
    ("ID No: 9999 0000 0002", "id_number", "9999 0000 0002"),
])
def test_parses_labelled_lines(line, field, value):
    (got,) = [f for f in parse_labelled_lines([(line, 0.9)], [field]) if f.name == field]
    assert got.value == value and got.confidence == 0.9


def test_parses_area_and_unit_from_one_line():
    fields = {f.name: f.value for f in parse_labelled_lines([("Total area: 3000 sq. m.", 0.8)], ["area", "area_unit"])}
    assert fields == {"area": 3000.0, "area_unit": "sq. m."}


@pytest.mark.parametrize("line", ["Name of holder:", "Name of the occupant:", "Name:"])
def test_a_label_without_its_value_reads_nothing(line):
    # Two-column cards: Tesseract gives the label line alone; the label words are not the name.
    assert parse_labelled_lines([(line, 0.95)], ["name"]) == []


def test_unparseable_date_is_omitted_not_guessed():
    assert parse_labelled_lines([("Issued: 0?/1O/2026", 0.5)], ["issue_date"]) == []


def test_only_requested_fields_are_returned():
    assert {f.name for f in parse_labelled_lines([("Survey No.: 1/1", 0.9), ("Name: A B", 0.9)], ["name"])} == {"name"}


def test_baseline_provider_extracts_from_ocr():
    provider = TesseractBaselineProvider(TesseractOcr(image_to_data=lambda i: SURVEY_SHEET, open_image=lambda b: b))
    request = ExtractionRequest(document_id="D-1", doc_type="survey_sheet", fields=["survey_number", "area"],
                                pages=[IMAGE_PAGE], mode="document")
    assert {f.name: f.value for f in provider.extract(request)} == {"survey_number": "154/2", "area": 3000.0}


@pytest.mark.skipif(not tesseract_available(), reason="Tesseract binary not installed")
def test_real_tesseract_reads_clean_rendered_survey_sheet():
    image = Path(__file__).resolve().parent.parent / "data/synthetic/land_acquisition/case_08/images/survey_sheet_clean.png"
    page = Page(number=1, image_bytes=image.read_bytes(), media_type="image/png")
    request = ExtractionRequest(document_id="D-1", doc_type="survey_sheet", fields=["survey_number"],
                                pages=[page], mode="document")
    assert [f.value for f in TesseractBaselineProvider().extract(request)] == ["154/2"]
