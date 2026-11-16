"""Cross-document verification checks, driven entirely by the scheme YAML."""

import re
from itertools import combinations
from typing import Literal, Optional

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.case_model import CaseIn
from app.extraction import EXTRACTION_UNAVAILABLE_MESSAGE
from app.facts import CaseFacts, build_facts
from app.rules_loader import Scheme, VerificationCheck
from app.safe_eval import UnknownName, evaluate

Status = Literal["pass", "fail", "needs_review"]
NOT_COMPETING_STATUSES = {"rejected", "withdrawn"}   # approved claims still compete for the same land
AREA_TOLERANCE = 1e-6  # relative, absorbs float rounding in unit conversion


class CheckResult(BaseModel):
    check_id: str
    status: Status
    detail: str
    severity: str
    score: Optional[float] = None
    sources: list[str] = []


class Flag(BaseModel):
    kind: str
    detail: str
    severity: str


class VerificationResult(BaseModel):
    checks: list[CheckResult]
    flags: list[Flag]
    rules_version: str


# --- comparison helpers -------------------------------------------------------

def _normalise_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(name).lower()).split())


def name_score(a: str, b: str) -> float:
    """0..1 similarity, robust to case, punctuation, word order and internal spacing."""
    na, nb = _normalise_name(a), _normalise_name(b)
    by_tokens = fuzz.token_sort_ratio(na, nb)
    no_spaces = fuzz.ratio(na.replace(" ", ""), nb.replace(" ", ""))
    return round(max(by_tokens, no_spaces) / 100, 3)


def dropped_middle_name(a: str, b: str) -> bool:
    """True if one name is the other with middle name(s) left out (same first and last name)."""
    ta, tb = _normalise_name(a).split(), _normalise_name(b).split()
    short, long_ = sorted((ta, tb), key=len)
    if len(short) < 2 or len(long_) <= len(short) or short[0] != long_[0] or short[-1] != long_[-1]:
        return False
    remaining = iter(long_)
    return all(token in remaining for token in short)   # ordered subsequence


_RANK = {"pass": 0, "needs_review": 1, "fail": 2}


def _fuzzy_status(score: float, fuzzy: float, review_floor: float) -> Status:
    if score >= fuzzy:
        return "pass"
    return "needs_review" if score >= review_floor else "fail"


def _normalise_exact(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).upper()


# --- field comparison checks ----------------------------------------------------

def _collect(check: VerificationCheck, facts: CaseFacts) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Values per field per document, plus reasons the comparison cannot be made."""
    values: dict[str, dict[str, object]] = {f: {} for f in check.fields}
    problems: list[str] = []
    for doc_id in check.across:
        doc = facts.names.get(doc_id, {"present": False})
        if not doc["present"]:
            problems.append(f"{doc_id} is missing")
            continue
        for f in check.fields:
            ref = f"{doc_id}.{f}"
            if f in doc:
                values[f][doc_id] = doc[f]
            elif ref in facts.invalid:
                problems.append(f"{ref}: {facts.invalid[ref]}")
            elif ref in facts.low_confidence:
                problems.append(f"{ref} is below the confidence threshold")
            elif ref in facts.disagree:
                problems.append(f"{ref}: {facts.disagree[ref]}")
            else:
                problems.append(f"{ref} was not found")
    return values, problems


def _field_check(check: VerificationCheck, facts: CaseFacts, threshold: float) -> CheckResult:
    sources = [f"{d}.{f}" for d in check.across for f in check.fields]
    base = {"check_id": check.id, "severity": check.severity, "sources": sources}
    values, problems = _collect(check, facts)
    if problems:
        return CheckResult(status="needs_review", detail="; ".join(problems), **base)

    if check.tolerance == "exact":
        for f, per_doc in values.items():
            if len({_normalise_exact(v) for v in per_doc.values()}) > 1:
                return CheckResult(status="fail", detail=f"{f} differs: {per_doc}", **base)
        return CheckResult(status="pass", detail="All values match exactly.", **base)

    worst: Optional[tuple[Status, float, str, bool]] = None
    for f, per_doc in values.items():
        for (d1, v1), (d2, v2) in combinations(per_doc.items(), 2):
            score = name_score(str(v1), str(v2))
            status = _fuzzy_status(score, check.fuzzy_threshold, threshold)
            middle = status != "needs_review" and dropped_middle_name(str(v1), str(v2))
            if middle:
                status = "needs_review"   # policy: a dropped middle name always goes to review, never fail
            pair = (status, score, f"{d1}.{f}={v1!r} vs {d2}.{f}={v2!r}", middle)
            if worst is None or (_RANK[status], -score) > (_RANK[worst[0]], -worst[1]):
                worst = pair
    status, score, where, middle = worst or ("pass", 1.0, "", False)
    detail = f"Lowest similarity {score:.3f}" + (f" ({where})" if where else "")
    if middle:
        detail += "; differs only by a dropped middle name, needs review"
    return CheckResult(status=status, detail=detail, score=score, **base)


# --- built-in: duplicate_claim ----------------------------------------------------

def _try(expr: Optional[str], facts: CaseFacts) -> Optional[object]:
    if not expr:
        return None
    try:
        return evaluate(expr, facts.names)
    except (UnknownName, TypeError, ValueError):
        return None


def _duplicate_check(check: VerificationCheck, scheme: Scheme, case: CaseIn,
                     facts: CaseFacts, other_cases: list[CaseIn]) -> CheckResult:
    """Another open case with the same key: needs_review, never fail. Wording comes from the YAML."""
    base = {"check_id": check.id, "severity": check.severity,
            "sources": [e for e in (check.key, check.claimed_area, check.total_area) if e]}
    say = check.messages
    key = _try(check.key, facts)
    if key is None:
        return CheckResult(status="needs_review", detail=say["key_unavailable"].format(key_expr=check.key), **base)

    competing: list[tuple[str, Optional[float]]] = []
    for other in other_cases:
        if other.case_id == case.case_id or other.status in NOT_COMPETING_STATUSES:
            continue
        other_facts = build_facts(scheme, other)
        other_key = _try(check.key, other_facts)
        if other_key is not None and _normalise_exact(other_key) == _normalise_exact(key):
            competing.append((other.case_id, _try(check.claimed_area, other_facts) if check.claimed_area else None))

    if not competing:
        return CheckResult(status="pass", detail=say["no_competitor"].format(key=key), **base)

    ids = ", ".join(cid for cid, _ in competing)
    if not (check.claimed_area and check.total_area):
        return CheckResult(status="needs_review", detail=say["competing"].format(ids=ids, key=key), **base)
    mine = _try(check.claimed_area, facts)
    total = _try(check.total_area, facts)
    amounts = [a for _, a in competing]
    if mine is None or total is None or None in amounts:
        return CheckResult(status="needs_review", detail=say["competing"].format(ids=ids, key=key), **base)
    combined = float(mine) + sum(float(a) for a in amounts)
    values = {"ids": ids, "key": key, "combined": f"{combined:g}", "total": f"{float(total):g}"}
    if combined <= float(total) * (1 + AREA_TOLERANCE):
        return CheckResult(status="pass", detail=say["within_total"].format(**values), **base)
    return CheckResult(status="needs_review", detail=say["exceeds_total"].format(**values), **base)


# --- entry point ---------------------------------------------------------------

def _flags(checks: list[CheckResult], facts: CaseFacts, case: CaseIn) -> list[Flag]:
    flags = [Flag(kind=c.check_id, detail=c.detail, severity=c.severity) for c in checks if c.status != "pass"]
    flags += [Flag(kind="missing_document", detail=f"{d} not submitted", severity="high")
              for d in facts.missing_documents]
    for doc_id, status in facts.validity.items():
        if status == "expired":
            flags.append(Flag(kind="document_expired", detail=f"{doc_id} is expired or too old", severity="high"))
        elif status == "unknown":
            flags.append(Flag(kind="validity_unknown", detail=f"{doc_id} date unreadable", severity="medium"))
    flags += [Flag(kind="low_confidence", detail=f"{ref} needs human review", severity="medium")
              for ref in facts.low_confidence]
    flags += [Flag(kind="invalid_value", detail=f"{ref}: {why}; needs human review", severity="medium")
              for ref, why in facts.invalid.items()]
    flags += [Flag(kind="readers_disagree", detail=f"{ref}: {why}; needs human review", severity="medium")
              for ref, why in facts.disagree.items()]
    flags += [Flag(kind="extraction_unavailable", detail=f"{doc_id}: {EXTRACTION_UNAVAILABLE_MESSAGE}",
                   severity="high")
              for doc_id, doc in case.documents.items() if doc.extraction_unavailable]
    return flags


def verify_documents(scheme: Scheme, case: CaseIn, other_cases: Optional[list[CaseIn]] = None) -> VerificationResult:
    facts = build_facts(scheme, case)
    checks: list[CheckResult] = []
    for check in scheme.verification_checks:
        if check.builtin == "duplicate_claim":
            checks.append(_duplicate_check(check, scheme, case, facts, other_cases or []))
        else:
            checks.append(_field_check(check, facts, scheme.confidence_threshold))
    return VerificationResult(checks=checks, flags=_flags(checks, facts, case), rules_version=scheme.version)
