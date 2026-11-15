"""The image evaluation path, exercised with fake providers (no network, no binary)."""

import pytest

from app.evaluation import field_matches, run_messy_eval, scoring_status
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
    assert flags.unscored["LA-02"] == "1 of 1 labelled documents unanswered"
    assert flags.cases_scored == flags.cases_total - 3          # LA-02, LA-05, and LA-07 (no documents)


@pytest.mark.parametrize("labelled, answered, reason", [
    (0, 0, "no labelled documents"),                 # the zero-document case: never "fully answered"
    (2, 0, "2 of 2 labelled documents unanswered"),
    (2, 1, "1 of 2 labelled documents unanswered"),
    (1, 1, None),
])
def test_scoring_status(labelled, answered, reason):
    assert scoring_status(labelled, answered) == reason


def test_case_with_no_labelled_documents_is_not_scored():
    flags = run_messy_eval().flags                   # recorded fakes: every document answers
    assert "LA-07" not in flags.per_case and flags.unscored == {"LA-07": "no labelled documents"}
    assert (flags.cases_scored, flags.cases_total) == (7, 8)


def test_flag_scores_are_not_applicable_when_no_answered_document_backs_them():
    flags = run_messy_eval(provider=FailingProvider(), variant="clean").flags
    assert flags.cases_scored == 0 and flags.precision is None and flags.recall is None


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


QUOTA = {"http_status": 429, "status": "RESOURCE_EXHAUSTED", "message": "You exceeded your current quota",
         "quota_id": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
         "quota_metric": "generate_content_free_tier_requests", "quota_value": "20", "retry_delay_seconds": 41.0}


class QuotaExhausted:
    name, model = "gemini", "test-model-1"

    def extract(self, request):
        raise ProviderError("Gemini HTTP 429", kind="rate_limited", retryable=True, details=dict(QUOTA))


def test_provider_error_details_are_stored_in_the_results():
    report = run_messy_eval(provider=QuotaExhausted(), variant="clean")
    assert report.provider_errors[0].details == QUOTA
    assert report.model_dump(mode="json")["provider_errors"][0]["details"]["quota_id"] == QUOTA["quota_id"]
