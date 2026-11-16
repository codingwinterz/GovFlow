"""Cross-check (a second reader): fields two readers read differently go to review, whatever the confidence."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import load_case, seed_case
from app.cross_check import READERS_DISAGREE, canonical, readers_disagree
from app.extraction import DocumentInput, Page, ProviderError, ProviderField, extract_facts
from app.facts import build_facts
from app.main import create_app
from app.models import Base, ExtractedField, make_engine
from app.rules_loader import load_scheme_by_name
from app.tools import add_document, check_eligibility, extract_document, verify_documents
from tests.asgi_client import call
from tests.auth_headers import staff

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
DOC = DocumentInput(document_id="D-1", doc_type="identity_proof", pages=[Page(number=1, text="scan")])
FIELDS = ["name", "id_number", "expiry_date"]
TYPES = {"name": "text", "id_number": "text", "expiry_date": "date"}


class Reader:
    def __init__(self, name, fields=None, error=None):
        self.name, self.fields, self.error = name, fields or [], error

    def extract(self, request):
        if self.error:
            raise self.error
        return self.fields


def pf(name, value, confidence=0.99):
    return ProviderField(name=name, value=value, confidence=confidence, page=1)


GEMINI = Reader("gemini", [pf("name", "Asha Naik"), pf("id_number", "9999 0000 0001"), pf("expiry_date", "2031-03-31")])


# --- normalisation -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field_type, a, b", [
    ("text", "PRAKASH  KAMATH", "Prakash Kamath"),          # case and spacing
    ("number", "1,20,000", 120000),                         # Indian digit grouping
    ("number", "120,000", "120000.0"),                      # Western grouping, decimal form
    ("percent", "80%", 80),
    ("date", "01/10/2026", "2026-10-01"),                   # day-first print vs ISO
    ("date", "1-10-2026", "2026-10-01"),
    ("unit", "sq. m.", "sqm"),                              # unit synonyms
    ("unit", "ha", "hectare"),
])
def test_same_meaning_in_different_spelling_agrees(field_type, a, b):
    assert not readers_disagree(field_type, a, b), (canonical(field_type, a), canonical(field_type, b))


@pytest.mark.parametrize("field_type, a, b", [
    ("text", "Lata Shirodkar", "Lalita Shirodkar"),
    ("text", "L?ta Sh1rodkar", "Lata Shirodkar"),            # damaged characters are a difference, not noise
    ("number", "1,20,000", 12000),
    ("number", 900, "9?0"),
    ("date", "01/10/2026", "2026-01-10"),                   # day-first is not month-first
    ("unit", "sqm", "sq ft"),
])
def test_different_readings_disagree(field_type, a, b):
    assert readers_disagree(field_type, a, b)


# --- in extraction -----------------------------------------------------------------------------------------------

def _extract(second):
    return extract_facts(DOC, FIELDS, 0.85, GEMINI, None, cross_check=second, types=TYPES)


def test_agreement_leaves_fields_accepted():
    second = Reader("tesseract", [pf("name", "ASHA NAIK", 0.9), pf("id_number", "9999 0000 0001", 0.9),
                                  pf("expiry_date", "31/03/2031", 0.9)])
    result = _extract(second)
    assert result.disagree == [] and result.cross_check == "tesseract"
    assert all(f.review_reason is None for f in result.fields)


def test_disagreement_sends_the_field_to_review_even_at_confidence_099():
    result = _extract(Reader("tesseract", [pf("name", "Asha Nair", 0.9), pf("expiry_date", "2031-03-31", 0.9)]))
    name = next(f for f in result.fields if f.name == "name")
    assert name.confidence == 0.99 and name.review_reason == READERS_DISAGREE
    assert "tesseract read 'Asha Nair'" in name.note
    assert result.disagree == ["name"]


def test_a_field_the_second_reader_did_not_return_is_not_checked():
    result = _extract(Reader("tesseract", [pf("expiry_date", "2031-03-31", 0.9), pf("name", "", 0.9)]))
    assert result.disagree == []                               # name blank, id_number absent: both skipped
    assert all(f.review_reason is None for f in result.fields)


def test_a_failing_second_reader_skips_the_check_and_says_so():
    result = _extract(Reader("tesseract", error=ProviderError("no binary", kind="not_configured")))
    assert result.status == "ok" and result.disagree == []
    assert result.cross_check == "tesseract unavailable (not_configured)"


# --- through storage, facts, flags, rules and the API ---------------------------------------------------------

@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_case(s, CaseIn.model_validate_json((SET_DIR / "case_01" / "case.json").read_text(encoding="utf-8")))
    return engine


def _upload_and_extract(engine, tmp_path, second):
    path = tmp_path / "id.txt"
    path.write_text("Name: Asha Naik", encoding="utf-8")
    with Session(engine) as s:
        doc = add_document(s, "LA-01", "identity_proof", str(path))
        s.commit()
        return extract_document(s, doc.id, GEMINI, cross_check=second).model_dump(), doc.id


def test_a_disagreement_is_stored_withheld_flagged_and_sends_the_rule_to_review(engine, tmp_path):
    result, doc_id = _upload_and_extract(engine, tmp_path, Reader("tesseract", [pf("name", "Asha Nair", 0.9)]))
    assert result["disagree"] == ["name"]
    with Session(engine) as s:
        row = s.query(ExtractedField).filter_by(document_id=doc_id, field="name").one()
        assert row.review_reason == READERS_DISAGREE and row.confidence == 0.99
        case = load_case(s, "LA-01")
        facts = build_facts(load_scheme_by_name("land_acquisition"), case)
        assert facts.disagree == {"identity_proof.name": READERS_DISAGREE}
        assert "name" not in facts.names["identity_proof"]
        flags = verify_documents(s, "LA-01").flags
        assert any(f.kind == "readers_disagree" and "identity_proof.name" in f.detail for f in flags)
        rules = {r.rule_id: r.status for r in check_eligibility(s, "LA-01").results}
        assert rules["valid_ownership"] == "needs_review"


def test_the_case_page_api_shows_the_reason(engine, tmp_path):
    _, doc_id = _upload_and_extract(engine, tmp_path, Reader("tesseract", [pf("name", "Asha Nair", 0.9)]))
    app = create_app(engine=engine, upload_dir=tmp_path)
    detail = call(app, "GET", "/cases/LA-01", headers=staff("officer", "O-1"))[1]
    (doc,) = [d for d in detail["documents"] if d["id"] == doc_id]
    (name,) = [f for f in doc["fields"] if f["field"] == "name"]
    assert name["needs_review"] is True and name["review_reason"] == READERS_DISAGREE


def test_an_older_database_gains_the_column(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE extracted_fields (id INTEGER PRIMARY KEY, document_id INTEGER, field VARCHAR, "
                     "value VARCHAR, confidence FLOAT, source_page INTEGER, method VARCHAR, note VARCHAR)")
    engine = make_engine(f"sqlite:///{path}")
    assert "review_reason" in {c["name"] for c in inspect(engine).get_columns("extracted_fields")}
    engine.dispose()
