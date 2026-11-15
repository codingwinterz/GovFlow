"""Runs the deterministic tools for one case: verify -> eligibility -> compensation."""

from typing import Optional

from pydantic import BaseModel

from app.case_model import CaseIn
from app.compensation import CompensationResult, compute_compensation
from app.rules_engine import EligibilityResult, check_eligibility
from app.rules_loader import Scheme
from app.verification import VerificationResult, verify_documents


class Assessment(BaseModel):
    case_id: str
    verification: VerificationResult
    eligibility: EligibilityResult
    compensation: Optional[CompensationResult]
    needs_human_review: bool
    review_reasons: list[str]
    rules_version: str


def _review_reasons(v: VerificationResult, e: EligibilityResult, c: Optional[CompensationResult]) -> list[str]:
    reasons = [f"{f.severity}: {f.kind}: {f.detail}" for f in v.flags]
    if e.overall != "eligible":
        reasons.append(f"eligibility: {e.overall}")
    if c is not None and c.status != "computed":
        reasons.append(f"compensation incomplete: {', '.join(c.missing)}")
    return reasons


def assess_case(scheme: Scheme, case: CaseIn, other_cases: Optional[list[CaseIn]] = None) -> Assessment:
    verification = verify_documents(scheme, case, other_cases)
    eligibility = check_eligibility(scheme, case, verification)
    compensation = compute_compensation(scheme, case) if scheme.compensation else None
    reasons = _review_reasons(verification, eligibility, compensation)
    return Assessment(case_id=case.case_id, verification=verification, eligibility=eligibility,
                      compensation=compensation, needs_human_review=bool(reasons),
                      review_reasons=reasons, rules_version=scheme.version)
