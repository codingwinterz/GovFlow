"""Cross-document verification checks, driven entirely by the scheme YAML."""

import re
from itertools import combinations
from typing import Literal, Optional

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.case_model import CaseIn
from app.facts import CaseFacts, build_facts
from app.rules_loader import Scheme, VerificationCheck
from app.safe_eval import UnknownName, evaluate

Status = Literal["pass", "fail", "needs_review"]
CLOSED_STATUSES = {"approved", "rejected"}
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
            elif ref in facts.low_confidence:
                problems.append(f"{ref} is below the confidence threshold")
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

    score, worst = 1.0, ""
    for f, per_doc in values.items():
        for (d1, v1), (d2, v2) in combinations(per_doc.items(), 2):
            s = name_score(str(v1), str(v2))
            if s < score:
                score, worst = s, f"{d1}.{f}={v1!r} vs {d2}.{f}={v2!r}"
    if score >= check.fuzzy_threshold:
        status: Status = "pass"
    elif score >= threshold:
        status = "needs_review"
    else:
        status = "fail"
    detail = f"Lowest similarity {score:.3f}" + (f" ({worst})" if worst else "")
    return CheckResult(status=status, detail=detail, score=score, **base)


# --- built-in: duplicate_claim ----------------------------------------------------

def _try(expr: Optional[str], facts: CaseFacts) -> Optional[object]:
    if not expr:
        return None
    try:
        return evaluate(expr, facts.names)
    except UnknownName:
        return None


def _duplicate_check(check: VerificationCheck, scheme: Scheme, case: CaseIn,
                     facts: CaseFacts, other_cases: list[CaseIn]) -> CheckResult:
    base = {"check_id": check.id, "severity": check.severity,
            "sources": [e for e in (check.key, check.claimed_area, check.total_area) if e]}
    key = _try(check.key, facts)
    if key is None:
        return CheckResult(status="needs_review", detail=f"Cannot check duplicates: {check.key} unavailable", **base)

    competing: list[tuple[str, Optional[float]]] = []
    for other in other_cases:
        if other.case_id == case.case_id or other.status in CLOSED_STATUSES:
            continue
        other_facts = build_facts(scheme, other)
        other_key = _try(check.key, other_facts)
        if other_key is not None and _normalise_exact(other_key) == _normalise_exact(key):
            competing.append((other.case_id, _try(check.claimed_area, other_facts)))

    if not competing:
        return CheckResult(status="pass", detail=f"No other open case claims {key}.", **base)

    ids = ", ".join(cid for cid, _ in competing)
    mine = _try(check.claimed_area, facts)
    total = _try(check.total_area, facts)
    areas = [a for _, a in competing]
    if mine is None or total is None or None in areas:
        return CheckResult(status="needs_review",
                           detail=f"Open cases {ids} also claim {key}; areas unknown, cannot rule out overlap.", **base)
    combined = float(mine) + sum(float(a) for a in areas)
    if combined <= float(total) * (1 + AREA_TOLERANCE):
        return CheckResult(status="pass",
                           detail=f"Open cases {ids} also claim {key}, but combined area {combined:g} "
                                  f"fits within survey total {float(total):g} (co-owners).", **base)
    return CheckResult(status="needs_review",
                       detail=f"Open cases {ids} also claim {key}; combined area {combined:g} exceeds "
                              f"survey total {float(total):g}.", **base)


# --- entry point ---------------------------------------------------------------

def _flags(checks: list[CheckResult], facts: CaseFacts) -> list[Flag]:
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
    return flags


def verify_documents(scheme: Scheme, case: CaseIn, other_cases: Optional[list[CaseIn]] = None) -> VerificationResult:
    facts = build_facts(scheme, case)
    checks: list[CheckResult] = []
    for check in scheme.verification_checks:
        if check.builtin == "duplicate_claim":
            checks.append(_duplicate_check(check, scheme, case, facts, other_cases or []))
        else:
            checks.append(_field_check(check, facts, scheme.confidence_threshold))
    return VerificationResult(checks=checks, flags=_flags(checks, facts), rules_version=scheme.version)
