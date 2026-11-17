"""Database-backed tools the agent and the API call. Each one writes an audit entry.

They wrap the deterministic pure functions (extraction, verification, rules engine,
compensation) that are tested without a database. Eligibility and money come only
from those functions; approval or rejection only from record_officer_decision,
which requires the officer role (CLAUDE.md rules 1 and 2).
"""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import verification
from app.audit import log_action
from app.case_store import advance_status, load_case, competing_cases
from app.compensation import CompensationResult
from app.compensation import compute_compensation as compute_compensation_pure
from app.extraction import (
    EXTRACTION_UNAVAILABLE_MESSAGE, DocumentInput, ExtractionProvider, ExtractionResult, OcrEngine, Page,
    extract_facts,
)
from app.models import Case, CompensationItemRow, queue_key, Document, ExtractedField, RuleResultRow, VerificationFlag
from app.resolutions import open_resolution_flags, resolution_problem
from app.rules_engine import EligibilityResult, overall_from
from app.rules_engine import check_eligibility as check_eligibility_pure
from app.rules_loader import RULES_DIR, Scheme, amount_fields, load_scheme_by_name

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
                                   note=f.note, review_reason=f.review_reason))


def extract_document(session: Session, document_id: int, provider: ExtractionProvider,
                     ocr: Optional[OcrEngine] = None, actor: str = "system",
                     cross_check: Optional[ExtractionProvider] = None) -> ExtractionResult:
    doc = session.get(Document, document_id)
    case = session.get(Case, doc.case_id)
    scheme = load_scheme_by_name(case.scheme)
    wanted = next(d.fields for d in scheme.required_documents if d.id == doc.doc_type)
    document = DocumentInput(document_id=str(doc.id), doc_type=doc.doc_type, pages=load_pages(doc.file_path))

    types = next(d.types for d in scheme.required_documents if d.id == doc.doc_type)
    result = extract_facts(document, wanted, scheme.confidence_threshold, provider, ocr, cross_check, types)
    doc.extraction_status, doc.extraction_error_kind = result.status, result.error_kind
    if result.status == "ok":
        _store_fields(session, doc.id, result)
        advance_status(case, "extracted")
    # On extraction_unavailable: earlier fields are kept and the case does not advance, so it can be retried
    log_action(session, case.id, actor, "extract_facts", result.model_dump(), scheme.version)
    session.commit()
    return result


def verify_documents(session: Session, case_id: str, actor: str = "system") -> verification.VerificationResult:
    case_in = load_case(session, case_id)
    scheme = load_scheme_by_name(case_in.scheme)
    result = verification.verify_documents(scheme, case_in, competing_cases(session, case_in.scheme))

    session.query(VerificationFlag).filter_by(case_id=case_id).delete()
    for flag in result.flags:
        session.add(VerificationFlag(case_id=case_id, kind=flag.kind, detail=flag.detail, severity=flag.severity))
    case = session.get(Case, case_id)
    case.confidence_flag = bool(result.flags)
    advance_status(case, "verified")
    log_action(session, case_id, actor, "verify_documents", result.model_dump(), scheme.version)
    session.commit()
    return result


# --- assessment, submission, status, officer decision ------------------------------------

Decision = Literal["approve", "reject", "send_back"]
DECISION_STATUS = {"approve": "approved", "reject": "rejected", "send_back": "needs_info"}
CLOSED_STATUSES = ("approved", "rejected", "withdrawn")
NEXT_STEP = {
    "received": "extract documents",
    "extracted": "verify documents",
    "verified": "check eligibility and compute compensation",
    "assessed": "submit to officer",
    "in_officer_review": "awaiting officer decision",
    "needs_info": "applicant to provide the requested information, then re-run",
    "approved": "closed (approved by officer)",
    "rejected": "closed (rejected by officer)",
    "withdrawn": "closed (withdrawn)",
}


class ToolError(ValueError):
    """A tool refused to act because of the case's state. The message is safe to show the officer."""


class UnknownCase(ToolError):
    """No such case (or document in that case)."""


class InvalidInput(ToolError):
    """The request itself is invalid (unknown scheme or document type, bad value)."""


class SubmitResult(BaseModel):
    case_id: str
    status: str
    queue_position: int


class CaseStatus(BaseModel):
    case_id: str
    status: str
    next_step: str
    blockers: list[str]   # each names its source: a flag kind, a rule recommendation, a missing input


class DecisionResult(BaseModel):
    case_id: str
    decision: Decision
    status: str
    officer_id: str


def _case(session: Session, case_id: str) -> tuple[Case, Scheme]:
    case = session.get(Case, case_id)
    if case is None:
        raise UnknownCase(f"Unknown case {case_id}")
    return case, load_scheme_by_name(case.scheme)


def _mark_assessed_if_complete(session: Session, case: Case, scheme: Scheme) -> None:
    has_rules = session.query(RuleResultRow).filter_by(case_id=case.id).count() > 0
    has_money = (scheme.compensation is None
                 or session.query(CompensationItemRow).filter_by(case_id=case.id).count() > 0)
    if has_rules and has_money:
        advance_status(case, "assessed")


def check_eligibility(session: Session, case_id: str, actor: str = "system") -> EligibilityResult:
    case, scheme = _case(session, case_id)
    case_in = load_case(session, case_id)
    checks = verification.verify_documents(scheme, case_in, competing_cases(session, case_in.scheme))
    result = check_eligibility_pure(scheme, case_in, checks)
    session.query(RuleResultRow).filter_by(case_id=case_id).delete()
    for r in result.results:
        session.add(RuleResultRow(case_id=case_id, rule_id=r.rule_id, status=r.status, reason=r.reason,
                                  clause=r.clause, rules_version=r.rules_version))
    session.flush()
    _mark_assessed_if_complete(session, case, scheme)
    log_action(session, case_id, actor, "check_eligibility", result.model_dump(), scheme.version)
    session.commit()
    return result


def compute_compensation(session: Session, case_id: str, actor: str = "system") -> CompensationResult:
    case, scheme = _case(session, case_id)
    if scheme.compensation is None:
        raise ToolError(f"Scheme {scheme.scheme} has no compensation section")
    result = compute_compensation_pure(scheme, load_case(session, case_id))
    session.query(CompensationItemRow).filter_by(case_id=case_id).delete()
    for item in result.items:
        session.add(CompensationItemRow(case_id=case_id, component=item.component, amount=item.amount,
                                        formula_note=item.formula_note))
    session.flush()
    _mark_assessed_if_complete(session, case, scheme)
    log_action(session, case_id, actor, "compute_compensation", result.model_dump(), scheme.version)
    session.commit()
    return result


def _unavailable_documents(session: Session, case_id: str) -> list[str]:
    latest: dict[str, Document] = {}
    for doc in session.query(Document).filter_by(case_id=case_id).order_by(Document.id):
        latest[doc.doc_type] = doc
    return [f"{t}: {EXTRACTION_UNAVAILABLE_MESSAGE}" for t, d in latest.items()
            if d.extraction_status == "extraction_unavailable"]


def _queue_position(session: Session, case: Case) -> int:
    queue = session.query(Case).filter_by(status="in_officer_review").all()
    queue.sort(key=queue_key)
    return [c.id for c in queue].index(case.id) + 1


def submit_to_officer(session: Session, case_id: str, actor: str = "system") -> SubmitResult:
    """Put an assessed case in the officer queue. Every outcome is a recommendation; the officer decides."""
    case, scheme = _case(session, case_id)
    if case.status != "assessed":
        raise ToolError(f"Case {case_id} is {case.status}; assess it first "
                        "(check_eligibility and compute_compensation)")
    unavailable = _unavailable_documents(session, case_id)
    if unavailable:
        raise ToolError("Cannot submit: " + "; ".join(unavailable))
    case.status, case.submitted_at = "in_officer_review", datetime.now(timezone.utc)
    session.flush()
    result = SubmitResult(case_id=case_id, status=case.status, queue_position=_queue_position(session, case))
    log_action(session, case_id, actor, "submit_to_officer", result.model_dump(), scheme.version)
    session.commit()
    return result


def _blockers(session: Session, case_id: str) -> list[str]:
    blockers = _unavailable_documents(session, case_id)
    blockers += [f"{f.kind}: {f.detail}" for f in session.query(VerificationFlag).filter_by(case_id=case_id)
                 if f.kind != "extraction_unavailable"]
    rules = session.query(RuleResultRow).filter_by(case_id=case_id).all()
    if rules:
        overall = overall_from([r.status for r in rules])
        if overall != "eligible":
            failing = ", ".join(f"{r.rule_id} ({r.clause})" for r in rules if r.status != "pass")
            blockers.append(f"recommendation: {overall} - {failing}; the officer decides")
    return blockers


def get_case_status(session: Session, case_id: str, actor: str = "system") -> CaseStatus:
    case, scheme = _case(session, case_id)
    next_step = NEXT_STEP.get(case.status, "unknown")
    unavailable = _unavailable_documents(session, case_id)
    if unavailable and case.status in ("received", "extracted", "verified", "assessed"):
        next_step = "retry extraction for: " + ", ".join(u.split(":")[0] for u in unavailable)
    result = CaseStatus(case_id=case_id, status=case.status, next_step=next_step,
                        blockers=_blockers(session, case_id))
    log_action(session, case_id, actor, "get_case_status", result.model_dump(), scheme.version)
    session.commit()
    return result


def amount_field_values(session: Session, case_id: str) -> dict[str, Any]:
    """Current values of the document fields that drive an amount (from the scheme YAML), as read from the
    case's latest documents. The officer confirms exactly these values before approving."""
    case, scheme = _case(session, case_id)
    docs = load_case(session, case_id).documents
    out: dict[str, Any] = {}
    for ref in amount_fields(scheme):
        doc_id, name = ref.split(".", 1)
        if doc_id in docs and name in docs[doc_id].fields:
            out[ref] = docs[doc_id].fields[name].value
    return out


def _unconfirmed(session: Session, case_id: str, confirmed: dict[str, Any]) -> list[str]:
    """Amount-driving fields the officer has not confirmed at their current value."""
    return [ref for ref, value in amount_field_values(session, case_id).items()
            if ref not in confirmed or confirmed[ref] != value]


def record_officer_decision(session: Session, case_id: str, role: str, officer_id: str, decision: str,
                            comment: str = "", confirmed: Optional[dict[str, Any]] = None,
                            resolutions: Optional[dict[str, Any]] = None,
                            today: Optional[date] = None) -> DecisionResult:
    """The only way a case is approved, rejected or sent back. Not exposed to the agent.
    Approval needs `confirmed`: the officer's check of every amount-driving field at its current value, however
    confident the extraction was (a document must not be able to vouch for itself). It also needs, for every open
    flag the YAML marks approval_needs_resolution (e.g. a tenant or mundkar entry), the officer's resolution:
    a reference and a date. Each resolution is written to the audit log."""
    if role != "officer":
        raise PermissionError("Only the officer role can approve, reject or send back a case")
    case, scheme = _case(session, case_id)
    if decision not in DECISION_STATUS:
        raise ToolError(f"Unknown decision {decision!r}; use approve, reject or send_back")
    if case.status != "in_officer_review":
        raise ToolError(f"Case {case_id} is {case.status}; a decision needs status in_officer_review")
    if decision != "approve" and not comment.strip():
        raise ToolError(f"A {decision} decision needs a comment explaining why")
    confirmed = dict(confirmed or {})
    if decision == "approve":
        missing = _unconfirmed(session, case_id, confirmed)
        if missing:
            raise ToolError(f"Confirm these values against the documents before approving: {', '.join(missing)}")
    recorded = {}
    if decision == "approve":
        given = dict(resolutions or {})
        for check in open_resolution_flags(session, case_id, scheme):
            problem = resolution_problem(given.get(check.id), today or date.today())
            if problem:
                label = scheme.terms.get(check.id, check.id)
                raise ToolError(f"Record the resolution for “{label}” before approving: {problem}")
            recorded[check.id] = {"reference": str(given[check.id]["reference"]).strip(),
                                  "date": str(given[check.id]["date"])}
    for kind, res in recorded.items():
        log_action(session, case_id, f"officer:{officer_id}", "flag_resolution",
                   {"flag": kind, **res, "officer_id": officer_id}, scheme.version)
    case.status, case.officer_id = DECISION_STATUS[decision], officer_id
    result = DecisionResult(case_id=case_id, decision=decision, status=case.status, officer_id=officer_id)
    log_action(session, case_id, f"officer:{officer_id}", "officer_decision",
               {**result.model_dump(), "comment": comment, "confirmed_fields": confirmed, "resolutions": recorded},
               scheme.version)
    session.commit()
    return result


def add_document(session: Session, case_id: str, doc_type: str, file_path: str, actor: str = "system") -> Document:
    """Register an uploaded document. A case that was sent back or under review is reopened."""
    case, scheme = _case(session, case_id)
    if doc_type not in {d.id for d in scheme.required_documents}:
        raise InvalidInput(f"Unknown document type {doc_type!r} for scheme {scheme.scheme}")
    if case.status in CLOSED_STATUSES:
        raise ToolError(f"Case {case_id} is closed ({case.status}); no new documents")
    doc = Document(case_id=case_id, doc_type=doc_type, file_path=file_path)
    session.add(doc)
    previous, case.status = case.status, "received"   # new evidence: everything is re-run
    session.flush()
    log_action(session, case_id, actor, "add_document",
               {"document_id": doc.id, "doc_type": doc_type, "previous_status": previous}, scheme.version)
    session.commit()
    return doc


SCHEME_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")   # becomes a file name under rules/


def create_case(session: Session, case_id: str, scheme_name: str, reference_date: date,
                inputs: Optional[dict[str, Any]] = None, actor: str = "system") -> Case:
    if not SCHEME_NAME.match(scheme_name) or not (RULES_DIR / f"{scheme_name}.yaml").is_file():
        raise InvalidInput(f"Unknown scheme {scheme_name!r}")
    scheme = load_scheme_by_name(scheme_name)
    if session.get(Case, case_id) is not None:
        raise ToolError(f"Case {case_id} already exists")
    case = Case(id=case_id, scheme=scheme_name, applicant_ref=case_id, reference_date=reference_date,
                inputs_json=json.dumps(inputs or {}))
    session.add(case)
    session.flush()
    log_action(session, case_id, actor, "create_case",
               {"scheme": scheme_name, "reference_date": reference_date.isoformat(), "inputs": inputs or {}},
               scheme.version)
    session.commit()
    return case


def update_inputs(session: Session, case_id: str, inputs: dict[str, Any], actor: str = "system") -> dict[str, Any]:
    """Officer-entered values (market value, dates). Changing them after assessment requires re-assessment."""
    case, scheme = _case(session, case_id)
    if case.status in CLOSED_STATUSES:
        raise ToolError(f"Case {case_id} is closed ({case.status}); inputs cannot change")
    merged = {**json.loads(case.inputs_json), **inputs}
    case.inputs_json = json.dumps(merged)
    previous = case.status
    if case.status in ("assessed", "in_officer_review"):
        case.status = "verified"   # old rule results and amounts no longer match the inputs
    log_action(session, case_id, actor, "update_inputs",
               {"changed": inputs, "previous_status": previous, "status": case.status}, scheme.version)
    session.commit()
    return merged
