"""A reading at or below confidence_threshold (0.85) goes to review, at every place a reading is accepted:
facts, extraction (low_confidence and the OCR fallback), the case-page API, and the evaluation's "accepted"."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import seed_case
from app.confidence import needs_review_for_confidence
from app.evaluation import _rows
from app.extraction import DocumentInput, ExtractionResult, ExtractedFieldOut, Page, ProviderField, extract_facts
from app.main import create_app
from app.models import Base
from app.providers.fake import FakeOcr, FakeProvider
from app.rules_loader import load_scheme_by_name
from app.tools import add_document, extract_document
from app.verification import verify_documents
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
FIELDS = ["name", "survey_number", "area"]
DOC = DocumentInput(document_id="D-1", doc_type="ownership_record", pages=[Page(number=1, text="scan")])


def pf(name, value, confidence):
    return ProviderField(name=name, value=value, confidence=confidence, page=1)


@pytest.mark.parametrize("confidence, review", [(0.85, True), (0.8499, True), (0.8501, False), (0.99, False)])
def test_the_rule(confidence, review):
    assert needs_review_for_confidence(confidence, 0.85) is review


def test_a_weak_reading_at_the_threshold_triggers_the_ocr_fallback():
    provider = FakeProvider({("D-1", "document"): [pf("name", "Asha Naik", 0.85), pf("survey_number", "1", 0.95),
                                                   pf("area", 1, 0.95)], ("D-1", "ocr_text"): []})
    ocr = FakeOcr({"D-1": ("ocr text", 0.95)})
    result = extract_facts(DOC, FIELDS, 0.85, provider, ocr)
    assert ocr.calls == 1 and result.used_fallback is True


def test_an_ocr_fallback_reading_at_the_threshold_is_not_adopted():
    # Same value from both passes: a fallback above the threshold would be adopted (method ocr_fallback, its
    # confidence). At exactly 0.85 it is not trusted, so the primary reading stands, still low confidence.
    provider = FakeProvider({("D-1", "document"): [pf("name", "Asha Naik", 0.6), pf("survey_number", "1", 0.95),
                                                   pf("area", 1, 0.95)],
                             ("D-1", "ocr_text"): [pf("name", "Asha Naik", 0.85)]})
    result = extract_facts(DOC, FIELDS, 0.85, provider, FakeOcr({"D-1": ("ocr text", 0.95)}))
    name = next(f for f in result.fields if f.name == "name")
    assert (name.method, name.confidence) == ("llm", 0.6) and "name" in result.low_confidence


def test_evaluation_does_not_count_a_reading_at_the_threshold_as_accepted():
    result = ExtractionResult(document_id="D-1", doc_type="ownership_record", provider="fake", ocr_engine=None,
                              fields=[ExtractedFieldOut(name="name", value="Lata Shirodkar", confidence=0.85,
                                                        source_page=1, method="llm")],
                              low_confidence=["name"], missing=[], used_fallback=False)
    (row,) = _rows("case_11", "ownership_record", {"name": "Lata Shirodkar"}, result, 0.85, {"name": "text"})
    assert row.accepted is False and row.correct is True


def test_la11_name_copied_at_exactly_085_now_raises_low_confidence():
    # 17 Nov live eval: the model copied LA-11's damaged "L?ta Sh1rodkar" at confidence 0.85 and it was accepted.
    case = CaseIn.model_validate_json((DATA / "case_11" / "case.json").read_text(encoding="utf-8"))
    case.documents["ownership_record"].fields["name"].confidence = 0.85
    flags = verify_documents(load_scheme_by_name("land_acquisition"), case).flags
    assert any(f.kind == "low_confidence" and "ownership_record.name" in f.detail for f in flags)


def test_the_case_page_marks_a_field_at_the_threshold_for_review(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    path = tmp_path / "id.txt"
    path.write_text("Name: Asha Naik", encoding="utf-8")
    with Session(engine) as s:
        seed_case(s, CaseIn.model_validate_json((DATA / "case_01" / "case.json").read_text(encoding="utf-8")))
        doc = add_document(s, "LA-01", "identity_proof", str(path))
        s.commit()
        doc_id = doc.id
        reader = _Fixed([pf("name", "Asha Naik", 0.85)])
        extract_document(s, doc_id, reader)
    detail = call(create_app(engine=engine, upload_dir=tmp_path), "GET", "/cases/LA-01",
                  headers=staff("officer", "O-1"))[1]
    (d,) = [x for x in detail["documents"] if x["id"] == doc_id]
    (name,) = [f for f in d["fields"] if f["field"] == "name"]
    assert name["confidence"] == 0.85 and name["needs_review"] is True


class _Fixed:
    name = "fixed"

    def __init__(self, fields):
        self.fields = fields

    def extract(self, request):
        return self.fields
