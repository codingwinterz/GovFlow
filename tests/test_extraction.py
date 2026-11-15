from app.extraction import DocumentInput, Page, ProviderField, extract_facts
from app.providers.fake import FakeOcr, FakeProvider, FailingProvider

FIELDS = ["name", "survey_number", "area"]
DOC = DocumentInput(document_id="D-1", doc_type="ownership_record", pages=[Page(number=1, text="scan")])


def pf(name, value, confidence, page=1):
    return ProviderField(name=name, value=value, confidence=confidence, page=page)


def _run(primary, ocr_fields=None, ocr_conf=0.95, with_ocr=True):
    provider = FakeProvider({("D-1", "document"): primary, ("D-1", "ocr_text"): ocr_fields or []})
    ocr = FakeOcr({"D-1": ("ocr text", ocr_conf)}) if with_ocr else None
    result = extract_facts(DOC, FIELDS, 0.85, provider, ocr)
    return result, provider, ocr


def _field(result, name):
    return next(f for f in result.fields if f.name == name)


def test_confident_fields_are_accepted_with_source():
    result, _, ocr = _run([pf("name", "Asha Naik", 0.97), pf("survey_number", "123/4", 0.95, page=2),
                           pf("area", 0.25, 0.93)])
    f = _field(result, "survey_number")
    assert (f.value, f.confidence, f.source_page, f.method) == ("123/4", 0.95, 2, "llm")
    assert result.document_id == "D-1" and result.low_confidence == [] and result.missing == []
    assert ocr.calls == 0 and result.used_fallback is False


def test_fields_not_requested_by_scheme_are_dropped():
    result, _, _ = _run([pf("name", "A", 0.9), pf("survey_number", "1", 0.9), pf("area", 1, 0.9),
                         pf("religion", "x", 0.99)])
    assert {f.name for f in result.fields} == set(FIELDS)


def test_missing_field_is_reported_not_invented():
    result, _, _ = _run([pf("name", "Asha Naik", 0.97), pf("area", 0.25, 0.93)], with_ocr=False)
    assert result.missing == ["survey_number"]
    assert "survey_number" not in {f.name for f in result.fields}


def test_low_confidence_without_ocr_is_kept_low_and_flagged():
    result, _, _ = _run([pf("name", "L?ta", 0.62), pf("survey_number", "1", 0.9), pf("area", 1, 0.9)],
                        with_ocr=False)
    assert _field(result, "name").confidence == 0.62
    assert result.low_confidence == ["name"]


def test_ocr_fallback_accepts_agreeing_confident_value():
    result, provider, ocr = _run(
        [pf("name", "Asha Naik", 0.70), pf("survey_number", "1", 0.9), pf("area", 1, 0.9)],
        ocr_fields=[pf("name", "ASHA  NAIK", 0.92)], ocr_conf=0.95)
    f = _field(result, "name")
    assert f.method == "ocr_fallback" and f.confidence == 0.92 and f.value == "Asha Naik"
    assert result.low_confidence == [] and result.used_fallback is True
    assert ocr.calls == 1
    assert provider.requests[-1].mode == "ocr_text" and provider.requests[-1].fields == ["name"]


def test_ocr_fallback_that_disagrees_is_not_accepted():
    result, _, _ = _run(
        [pf("name", "Asha Naik", 0.70), pf("survey_number", "1", 0.9), pf("area", 1, 0.9)],
        ocr_fields=[pf("name", "Usha Nair", 0.95)])
    f = _field(result, "name")
    assert f.value == "Asha Naik" and f.confidence == 0.70 and f.method == "llm"
    assert "Usha Nair" in f.note
    assert result.low_confidence == ["name"]


def test_low_quality_ocr_caps_fallback_confidence():
    result, _, _ = _run(
        [pf("name", "Asha Naik", 0.70), pf("survey_number", "1", 0.9), pf("area", 1, 0.9)],
        ocr_fields=[pf("name", "Asha Naik", 0.95)], ocr_conf=0.60)
    assert result.low_confidence == ["name"]
    assert _field(result, "name").confidence == 0.70   # best available stays below threshold


def test_ocr_fills_a_missing_field_when_confident():
    result, _, _ = _run([pf("name", "Asha Naik", 0.97), pf("area", 1, 0.9)],
                        ocr_fields=[pf("survey_number", "123/4", 0.93)])
    f = _field(result, "survey_number")
    assert f.value == "123/4" and f.method == "ocr_fallback"
    assert result.missing == []


def test_numeric_values_agree_across_representations():
    result, _, _ = _run([pf("name", "A", 0.9), pf("survey_number", "1", 0.9), pf("area", "0.25", 0.7)],
                        ocr_fields=[pf("area", 0.25, 0.9)])
    assert _field(result, "area").method == "ocr_fallback"


def test_out_of_range_confidence_is_treated_as_zero():
    result, _, _ = _run([pf("name", "A", 1.7), pf("survey_number", "1", 0.9), pf("area", 1, 0.9)],
                        with_ocr=False)
    assert _field(result, "name").confidence == 0.0
    assert result.low_confidence == ["name"]


def test_provider_failure_routes_everything_to_review():
    result = extract_facts(DOC, FIELDS, 0.85, FailingProvider(), None)
    assert result.error and result.fields == [] and result.missing == FIELDS
