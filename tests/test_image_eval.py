"""The image evaluation path, exercised with fake providers (no network, no binary)."""

import pytest

from app.evaluation import field_matches, run_messy_eval
from app.extraction import ProviderField
from app.providers.fake import FailingProvider


class ImageCheckingProvider:
    """Records whether it received images; returns nothing (so every field is missing)."""
    name = "image_check"

    def __init__(self):
        self.saw_images = []

    def extract(self, request):
        self.saw_images.append(all(p.image_bytes and p.media_type == "image/png" for p in request.pages))
        return []


@pytest.mark.parametrize("field, got, truth, expected", [
    ("area_unit", "sq. m.", "sqm", True),
    ("area_unit", "Sq Ft", "sq ft", True),
    ("area_unit", "Ha", "hectare", True),
    ("area_unit", "acre", "ha", False),
    ("area_unit", "bigha", "sqm", False),
    ("area", "0.40", 0.4, True),
    ("name", "PRAKASH KAMATH", "Prakash Kamath", True),
    ("name", "Lata Shirodkar", "L?ta Sh1rodkar", False),
    ("expiry_date", "2031-03-31", "2031-03-31", True),
    ("survey_number", "154/2", "145/2", False),
])
def test_field_matching(field, got, truth, expected):
    assert field_matches(field, got, truth) is expected


def test_image_variant_requires_a_real_provider():
    with pytest.raises(ValueError, match="provider"):
        run_messy_eval(variant="clean")


@pytest.mark.parametrize("variant", ["clean", "degraded"])
def test_image_variant_sends_png_pages(variant):
    provider = ImageCheckingProvider()
    report = run_messy_eval(provider=provider, variant=variant)
    assert provider.saw_images and all(provider.saw_images)
    assert report.variant == variant
    e = report.extraction
    assert e.correct == 0 and e.accuracy == 0.0 and e.routed_to_review == e.total


def test_provider_failures_are_reported_not_hidden():
    report = run_messy_eval(provider=FailingProvider(), variant="clean")
    assert len(report.errors) == 7 and "provider unavailable" in report.errors[0]
    assert report.extraction.accepted == 0


def test_fake_text_eval_still_reports_accuracy():
    report = run_messy_eval()
    assert report.variant == "text" and report.errors == []
    assert report.extraction.accuracy == pytest.approx(26 / 27, abs=0.001)   # garbled LA-11 name is wrong
