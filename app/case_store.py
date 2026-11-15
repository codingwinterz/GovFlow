"""Convert between database rows and the CaseIn shape the pure tools use."""

import json

from sqlalchemy.orm import Session

from app.case_model import CaseIn, DocumentIn, FieldValue
from app.models import Case, Document, ExtractedField

NOT_COMPETING_STATUSES = ("rejected", "withdrawn")
STATUS_ORDER = ("received", "extracted", "verified", "assessed", "in_officer_review")


def advance_status(case: Case, new_status: str) -> None:
    """Move forward through the pipeline; never move backwards or out of an officer decision."""
    if case.status in STATUS_ORDER and STATUS_ORDER.index(new_status) > STATUS_ORDER.index(case.status):
        case.status = new_status


def seed_case(session: Session, case: CaseIn) -> None:
    """Store a case whose fields are already known (synthetic set, tests)."""
    session.add(Case(id=case.case_id, scheme=case.scheme, applicant_ref=case.case_id, status=case.status,
                     reference_date=case.reference_date, inputs_json=json.dumps(case.inputs)))
    for doc_type, doc in case.documents.items():
        row = Document(case_id=case.case_id, doc_type=doc_type, file_path=f"seed:{doc_type}")
        session.add(row)
        session.flush()
        for name, fv in doc.fields.items():
            session.add(ExtractedField(document_id=row.id, field=name, value=json.dumps(fv.value),
                                       confidence=fv.confidence, source_page=fv.source_page, method="seed"))
    session.commit()


def load_case(session: Session, case_id: str) -> CaseIn:
    case = session.get(Case, case_id)
    if case is None:
        raise KeyError(f"Unknown case {case_id}")
    documents: dict[str, DocumentIn] = {}
    for doc in session.query(Document).filter_by(case_id=case_id).order_by(Document.id):
        rows = session.query(ExtractedField).filter_by(document_id=doc.id)
        # latest upload of a document type wins
        documents[doc.doc_type] = DocumentIn(fields={
            r.field: FieldValue(value=json.loads(r.value), confidence=r.confidence, source_page=r.source_page)
            for r in rows
        })
    return CaseIn(case_id=case.id, scheme=case.scheme, status=case.status, reference_date=case.reference_date,
                  documents=documents, inputs=json.loads(case.inputs_json))


def competing_cases(session: Session, scheme: str) -> list[CaseIn]:
    """Cases whose claims count for duplicate checks: everything except rejected or withdrawn."""
    ids = [c.id for c in session.query(Case).filter(Case.scheme == scheme,
                                                    Case.status.not_in(NOT_COMPETING_STATUSES))]
    return [load_case(session, i) for i in ids]
