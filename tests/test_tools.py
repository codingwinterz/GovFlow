"""DB-backed tools: extraction and verification write results and audit rows."""

import json

import pytest

from app.audit import log_action
from app.case_store import load_case, seed_case
from app.extraction import ProviderField
from app.models import AuditLog, Document, ExtractedField, VerificationFlag, make_engine, make_session
from app.models import Case as CaseRow
from app.providers.fake import FailingProvider, FakeOcr, FakeProvider
from app.tools import extract_document, verify_documents
from tests.test_verification import _case


@pytest.fixture
def session():
    with make_session(make_engine("sqlite://")) as s:
        yield s


def _audits(session, action):
    return [a for a in session.query(AuditLog).order_by(AuditLog.id) if a.action == action]


# --- audit ---------------------------------------------------------------------

def test_log_action_masks_identifiers_and_records_version(session):
    log_action(session, "LA-01", "agent", "x", {"id": "9876 5432 1098"}, "0.1.0")
    row = session.query(AuditLog).one()
    assert json.loads(row.payload_json) == {"id": "XXXX XXXX 1098"}
    assert row.rules_version == "0.1.0"


# --- seeding / loading -----------------------------------------------------------

def test_seeded_case_round_trips(session):
    case = _case(case_id="LA-01")
    case.inputs = {"market_value_per_sqm": 3000}
    seed_case(session, case)
    loaded = load_case(session, "LA-01")
    assert loaded.reference_date == case.reference_date
    assert loaded.inputs == {"market_value_per_sqm": 3000}
    assert loaded.documents["identity_proof"].fields["name"].value == "Asha Naik"
    assert loaded.documents["ownership_record"].fields["area"].value == 0.25   # numbers stay numbers


# --- extract_document ---------------------------------------------------------------

def _uploaded_identity_doc(session, tmp_path, case_id="LA-01"):
    case = _case(case_id=case_id, drop=("identity_proof",))
    seed_case(session, case)
    path = tmp_path / "identity.txt"
    path.write_text("NAME: Asha Naik\nID: 9876 5432 1098\nVALID UPTO: 2030-01-01", encoding="utf-8")
    doc = Document(case_id=case_id, doc_type="identity_proof", file_path=str(path))
    session.add(doc)
    session.commit()
    return doc


def _provider(doc_id, name_conf=0.96):
    return FakeProvider({(doc_id, "document"): [
        ProviderField(name="name", value="Asha Naik", confidence=name_conf, page=1),
        ProviderField(name="id_number", value="9876 5432 1098", confidence=0.95, page=1),
        ProviderField(name="expiry_date", value="2030-01-01", confidence=0.94, page=1),
    ]})


def test_extract_document_stores_fields_with_confidence_and_method(session, tmp_path):
    doc = _uploaded_identity_doc(session, tmp_path)
    provider = _provider(str(doc.id))
    result = extract_document(session, doc.id, provider)
    rows = {r.field: r for r in session.query(ExtractedField).filter_by(document_id=doc.id)}
    assert set(rows) == {"name", "id_number", "expiry_date"}
    assert rows["name"].confidence == 0.96 and rows["name"].method == "llm" and rows["name"].source_page == 1
    assert result.low_confidence == []
    assert provider.requests[0].pages[0].text.startswith("NAME: Asha Naik")   # file content was read
    assert session.get(CaseRow, "LA-01").status == "extracted"


def test_extract_document_writes_masked_audit_entry(session, tmp_path):
    doc = _uploaded_identity_doc(session, tmp_path)
    extract_document(session, doc.id, _provider(str(doc.id)))
    (audit,) = _audits(session, "extract_facts")
    assert audit.case_id == "LA-01" and audit.actor == "system" and audit.rules_version == "0.1.0"
    assert "9876 5432" not in audit.payload_json and "XXXX XXXX 1098" in audit.payload_json
    assert json.loads(audit.payload_json)["provider"] == "fake"


def test_re_extraction_replaces_fields_and_appends_audit(session, tmp_path):
    doc = _uploaded_identity_doc(session, tmp_path)
    extract_document(session, doc.id, _provider(str(doc.id)))
    extract_document(session, doc.id, _provider(str(doc.id), name_conf=0.5))
    assert session.query(ExtractedField).filter_by(document_id=doc.id, field="name").one().confidence == 0.5
    assert len(_audits(session, "extract_facts")) == 2


def test_provider_failure_is_audited_and_extracts_nothing(session, tmp_path):
    doc = _uploaded_identity_doc(session, tmp_path)
    result = extract_document(session, doc.id, FailingProvider())
    assert result.error and session.query(ExtractedField).filter_by(document_id=doc.id).count() == 0
    assert json.loads(_audits(session, "extract_facts")[0].payload_json)["error"]


def test_ocr_fallback_use_is_recorded(session, tmp_path):
    doc = _uploaded_identity_doc(session, tmp_path)
    did = str(doc.id)
    provider = FakeProvider({
        (did, "document"): [ProviderField(name="name", value="Asha Naik", confidence=0.6, page=1),
                            ProviderField(name="id_number", value="9876 5432 1098", confidence=0.95, page=1),
                            ProviderField(name="expiry_date", value="2030-01-01", confidence=0.94, page=1)],
        (did, "ocr_text"): [ProviderField(name="name", value="Asha Naik", confidence=0.93, page=1)],
    })
    extract_document(session, doc.id, provider, FakeOcr({did: ("NAME: Asha Naik", 0.96)}))
    payload = json.loads(_audits(session, "extract_facts")[0].payload_json)
    assert payload["used_fallback"] is True and payload["ocr_engine"] == "fake_ocr"
    assert session.query(ExtractedField).filter_by(document_id=doc.id, field="name").one().method == "ocr_fallback"


# --- verify_documents -------------------------------------------------------------------

def test_verify_documents_stores_flags_and_audits(session):
    seed_case(session, _case(case_id="LA-04", id_name="Vinod Shetty"))
    result = verify_documents(session, "LA-04")
    kinds = {f.kind for f in session.query(VerificationFlag).filter_by(case_id="LA-04")}
    assert "name_match" in kinds and {f.kind for f in result.flags} == kinds
    (audit,) = _audits(session, "verify_documents")
    assert audit.rules_version == "0.1.0"
    assert any(c["check_id"] == "name_match" and c["status"] == "fail"
               for c in json.loads(audit.payload_json)["checks"])
    row = session.get(CaseRow, "LA-04")
    assert row.status == "verified" and row.confidence_flag is True


def test_clean_case_verifies_without_flags(session):
    seed_case(session, _case(case_id="LA-01"))
    assert verify_documents(session, "LA-01").flags == []
    assert session.get(CaseRow, "LA-01").confidence_flag is False


def test_reverification_replaces_flags(session):
    seed_case(session, _case(case_id="LA-04", id_name="Vinod Shetty"))
    verify_documents(session, "LA-04")
    first = session.query(VerificationFlag).filter_by(case_id="LA-04").count()
    verify_documents(session, "LA-04")
    assert session.query(VerificationFlag).filter_by(case_id="LA-04").count() == first
    assert len(_audits(session, "verify_documents")) == 2


def test_duplicate_claim_uses_other_open_cases_in_db(session):
    seed_case(session, _case(case_id="LA-12", claimed_ha=0.6))
    seed_case(session, _case(case_id="LA-13", claimed_ha=0.6))
    seed_case(session, _case(case_id="LA-99", claimed_ha=0.6, status="rejected"))
    result = verify_documents(session, "LA-12")
    dup = next(c for c in result.checks if c.check_id == "duplicate_claim")
    assert dup.status == "needs_review" and "LA-13" in dup.detail and "LA-99" not in dup.detail


def test_low_confidence_extraction_routes_to_review_end_to_end(session, tmp_path):
    doc = _uploaded_identity_doc(session, tmp_path)
    extract_document(session, doc.id, _provider(str(doc.id), name_conf=0.5))
    result = verify_documents(session, "LA-01")
    assert next(c for c in result.checks if c.check_id == "name_match").status == "needs_review"
    assert any(f.kind == "low_confidence" and "identity_proof.name" in f.detail for f in result.flags)
