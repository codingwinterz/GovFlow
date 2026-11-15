"""Database-backed tools the agent will call. Each one writes an audit entry.

These wrap the pure functions (extraction, verification) that are tested
without a database. No tool here decides eligibility, money or approval.
"""

import json
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app import verification
from app.audit import log_action
from app.case_store import advance_status, load_case, open_cases
from app.extraction import DocumentInput, ExtractionProvider, ExtractionResult, OcrEngine, Page, extract_facts
from app.models import Case, Document, ExtractedField, VerificationFlag
from app.rules_loader import load_scheme_by_name

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}


def load_pages(file_path: str) -> list[Page]:
    path = Path(file_path)
    if path.suffix.lower() == ".txt":
        return [Page(number=1, text=path.read_text(encoding="utf-8"))]
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"Unsupported document type: {path.suffix}")
    return [Page(number=1, image_bytes=path.read_bytes(), media_type=media_type)]


def _store_fields(session: Session, document_id: int, result: ExtractionResult) -> None:
    session.query(ExtractedField).filter_by(document_id=document_id).delete()
    for f in result.fields:
        session.add(ExtractedField(document_id=document_id, field=f.name, value=json.dumps(f.value),
                                   confidence=f.confidence, source_page=f.source_page, method=f.method,
                                   note=f.note))


def extract_document(session: Session, document_id: int, provider: ExtractionProvider,
                     ocr: Optional[OcrEngine] = None, actor: str = "system") -> ExtractionResult:
    doc = session.get(Document, document_id)
    case = session.get(Case, doc.case_id)
    scheme = load_scheme_by_name(case.scheme)
    wanted = next(d.fields for d in scheme.required_documents if d.id == doc.doc_type)
    document = DocumentInput(document_id=str(doc.id), doc_type=doc.doc_type, pages=load_pages(doc.file_path))

    result = extract_facts(document, wanted, scheme.confidence_threshold, provider, ocr)
    _store_fields(session, doc.id, result)
    if result.error is None:
        advance_status(case, "extracted")
    log_action(session, case.id, actor, "extract_facts", result.model_dump(), scheme.version)
    session.commit()
    return result


def verify_documents(session: Session, case_id: str, actor: str = "system") -> verification.VerificationResult:
    case_in = load_case(session, case_id)
    scheme = load_scheme_by_name(case_in.scheme)
    result = verification.verify_documents(scheme, case_in, open_cases(session, case_in.scheme))

    session.query(VerificationFlag).filter_by(case_id=case_id).delete()
    for flag in result.flags:
        session.add(VerificationFlag(case_id=case_id, kind=flag.kind, detail=flag.detail, severity=flag.severity))
    case = session.get(Case, case_id)
    case.confidence_flag = bool(result.flags)
    advance_status(case, "verified")
    log_action(session, case_id, actor, "verify_documents", result.model_dump(), scheme.version)
    session.commit()
    return result
