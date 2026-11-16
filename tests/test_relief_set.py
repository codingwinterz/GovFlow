"""The synthetic relief document set and the hard image variant (both schemes). ALL DATA SYNTHETIC."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from app.evaluation import SET_DIRS, field_matches, run_messy_eval
from app.extraction import ProviderField
from app.providers.tesseract import parse_labelled_lines
from scripts.render_images import HANDWRITTEN, render_document

RELIEF = SET_DIRS["disaster_relief"]
LABELS = json.loads((RELIEF / "messy_labels.json").read_text(encoding="utf-8"))


def test_relief_set_has_at_least_six_documents_of_all_three_kinds():
    docs = LABELS["documents"]
    assert len(docs) >= 6
    assert {d["doc_type"] for d in docs} == {"damage_assessment", "residence_proof", "identity_proof"}


@pytest.mark.parametrize("item", LABELS["documents"], ids=lambda d: f"{d['case']}.{d['doc_type']}")
def test_each_document_is_synthetic_and_matches_its_case(item):
    folder = RELIEF / item["case"]
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    stored = {k: v["value"] for k, v in case["documents"][item["doc_type"]]["fields"].items()}
    assert item["truth"] == stored                                      # the label is the case's own truth
    text = (folder / "documents" / f"{item['doc_type']}.txt").read_text(encoding="utf-8")
    assert "(SYNTHETIC)" in text.splitlines()[0]
    if "id_number" in item["truth"]:
        assert item["truth"]["id_number"].startswith("9999 ")         # fake ID numbers only


@pytest.mark.parametrize("scheme", ["land_acquisition", "disaster_relief"])
def test_every_labelled_document_has_clean_degraded_and_hard_images(scheme):
    labels = json.loads((SET_DIRS[scheme] / "messy_labels.json").read_text(encoding="utf-8"))
    for item in labels["documents"]:
        images = SET_DIRS[scheme] / item["case"] / "images"
        assert (images / f"{item['doc_type']}_clean.png").exists() and (images / f"{item['doc_type']}_degraded.png").exists()
        with Image.open(images / f"{item['doc_type']}_hard.jpg") as hard:
            assert hard.format == "JPEG"


# --- the hard variant ---------------------------------------------------------------------------------------------

TEXT = "DAMAGE ASSESSMENT REPORT (SYNTHETIC)\nHouse No.: H-56\nVillage: Parra\nDamage: 14.9%\nAssessed: 20/10/2026\n"


def _colours(img):
    raw = img.convert("RGB").tobytes()
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def _blue_ink(pixels):
    return sum(1 for r, g, b in pixels if b - r > 25 and b > g + 15)


def test_hard_variant_is_deterministic_and_has_a_stamp_and_handwriting():
    a, b = render_document(TEXT, "hard", HANDWRITTEN["damage_assessment"]), render_document(TEXT, "hard", "damage")
    assert hashlib.sha256(a.tobytes()).digest() == hashlib.sha256(b.tobytes()).digest()
    pixels = _colours(a)
    red = sum(1 for r, g, bl in pixels if r > 140 and g < 110 and bl < 120)            # the rubber stamp
    blue = _blue_ink(pixels)                                                            # the handwritten value
    assert red > 200 and blue > 60, (red, blue)
    assert _blue_ink(_colours(render_document(TEXT, "hard", None))) < 5               # no hand, no blue ink


def test_hard_variant_is_a_photo_not_the_flat_page():
    hard, clean = render_document(TEXT, "hard", "damage"), render_document(TEXT, "clean")
    assert hard.size != clean.size
    corner = hard.convert("RGB").getpixel((5, 5))
    assert max(corner) < 120                                       # the table around the page, not white paper


# --- reading the relief layouts and scoring them ----------------------------------------------------------------

@pytest.mark.parametrize("line, field, value", [
    ("House No.: H-56", "house_number", "H-56"), ("Village: Parra", "village", "Parra"),
    ("Damage: 14.9%", "damage_percent", "14.9"), ("House type: Hut", "house_type", "Hut"),
    ("Area type: Plain", "area_type", "Plain"), ("Notified area: Yes", "notified_area", "Yes"),
    ("Assessed: 20/10/2026", "assessment_date", "2026-10-20"),
])
def test_tesseract_baseline_reads_relief_labels(line, field, value):
    (got,) = parse_labelled_lines([(line, 0.9)], [field])
    assert (got.name, got.value) == (field, value)


def test_scoring_compares_meanings_by_field_type():
    assert field_matches("damage_percent", "14.9%", 14.9, "percent")
    assert field_matches("assessment_date", "20/10/2026", "2026-10-20", "date")
    assert field_matches("name", "ESTHER D'SOUZA", "Esther D'Souza", "text")
    assert not field_matches("damage_percent", "149", 14.9, "percent")


class PerfectReader:
    """Returns each image's truth values: checks the scoring and the hand-written expected flags, not a model."""
    name, model = "perfect", None

    def __init__(self, variant):
        self.truth = {}
        for item in LABELS["documents"]:
            path = RELIEF / item["case"] / "images" / f"{item['doc_type']}_{variant}.{'jpg' if variant == 'hard' else 'png'}"
            self.truth[hashlib.sha256(path.read_bytes()).hexdigest()] = item["truth"]

    def extract(self, request):
        truth = self.truth[hashlib.sha256(request.pages[0].image_bytes).hexdigest()]
        return [ProviderField(name=k, value=v, confidence=0.99, page=1) for k, v in truth.items() if k in request.fields]


@pytest.mark.parametrize("variant", ["clean", "hard"])
def test_a_perfect_reader_scores_full_marks_and_raises_exactly_the_expected_flags(variant):
    report = run_messy_eval(provider=PerfectReader(variant), variant=variant, scheme="disaster_relief")
    e, f = report.extraction, report.flags
    assert (e.accuracy, e.accepted_wrong, e.documents_answered) == (1.0, 0, len(LABELS["documents"]))
    assert (f.precision, f.recall, f.cases_scored) == (1.0, 1.0, len(LABELS["expected_flags"])), f.per_case
