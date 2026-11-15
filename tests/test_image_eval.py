"""The image evaluation path, exercised with fake providers (no network, no binary)."""

import pytest

from app.evaluation import field_matches, run_messy_eval
from app.extraction import ProviderError, ProviderField
from app.providers.fake import FailingProvider
from app.providers.tesseract import TesseractBaselineProvider, TesseractOcr


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
    assert len(report.provider_errors) == 7 and "provider unavailable" in report.provider_errors[0].message
    assert report.provider_errors[0].kind == "unavailable"
    e = report.extraction
    assert e.accepted == 0 and e.documents_answered == 0 and e.fields_answered == 0
    assert e.accuracy is None                       # nothing answered: no accuracy, not 0.0
    assert e.unavailable == e.total and e.routed_to_review == 0


class PartlyFailing:
    """Reads the text documents with the label parser, but is rate-limited on identity proofs."""
    name = "partly_failing"
    model = "test-model-1"

    def __init__(self):
        self.inner = TesseractBaselineProvider(TesseractOcr(image_to_data=None, open_image=None))

    def extract(self, request):
        if request.doc_type == "identity_proof":
            raise ProviderError("HTTP 429: quota", kind="rate_limited", retryable=True)
        return self.inner.extract(request)


def test_accuracy_counts_only_documents_the_provider_answered():
    report = run_messy_eval(provider=PartlyFailing(), variant="text")
    e = report.extraction
    assert (e.documents_answered, e.documents_total) == (5, 7)
    assert [(f.document, f.kind) for f in report.provider_errors] == [
        ("case_02.identity_proof", "rate_limited"), ("case_05.identity_proof", "rate_limited")]
    answered = [r for r in e.rows if r.answered]
    assert e.fields_answered == len(answered) and e.unavailable == e.total - len(answered)
    assert e.accuracy == round(sum(r.correct for r in answered) / len(answered), 3)
    assert e.accepted + e.routed_to_review == e.fields_answered
    assert e.reading_errors == sum(not r.correct for r in answered)


def test_flags_are_scored_only_on_cases_whose_documents_all_answered():
    flags = run_messy_eval(provider=PartlyFailing(), variant="text").flags
    assert "LA-02" not in flags.per_case and "LA-05" not in flags.per_case
    assert flags.cases_scored == flags.cases_total - 2


def test_report_names_the_model():
    assert run_messy_eval(provider=PartlyFailing(), variant="text").model == "test-model-1"
    assert run_messy_eval().model is None          # recorded fakes have no model


def test_progress_callback_sees_every_document():
    seen = []
    run_messy_eval(on_document=lambda label, result: seen.append((label, result.status)))
    assert len(seen) == 7 and seen[0] == ("case_02.identity_proof", "ok")


def test_fake_text_eval_still_reports_accuracy():
    report = run_messy_eval()
    assert report.variant == "text" and report.provider_errors == []
    assert report.extraction.accuracy == pytest.approx(26 / 27, abs=0.001)   # garbled LA-11 name is wrong
    assert (report.extraction.documents_answered, report.extraction.documents_total) == (7, 7)
