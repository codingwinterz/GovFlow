"""Deterministic eligibility: evaluates the scheme's YAML rules for one case.

The result is a recommendation. `not_eligible` never rejects a case; only an
officer can do that.
"""

from typing import Literal

from pydantic import BaseModel

from app.case_model import CaseIn
from app.facts import build_facts
from app.rules_loader import EligibilityRule, Scheme
from app.safe_eval import UnknownName, evaluate
from app.verification import CheckResult, Status, VerificationResult

Overall = Literal["eligible", "not_eligible", "needs_review"]


class RuleResult(BaseModel):
    rule_id: str
    status: Status
    reason: str
    clause: str
    rules_version: str


class EligibilityResult(BaseModel):
    results: list[RuleResult]
    overall: Overall
    rules_version: str


def combine(statuses: list[Status]) -> Status:
    if "fail" in statuses:
        return "fail"
    if "needs_review" in statuses:
        return "needs_review"
    return "pass"


def overall_from(statuses: list[Status]) -> Overall:
    return {"pass": "eligible", "fail": "not_eligible", "needs_review": "needs_review"}[combine(statuses)]


def _evaluate_when(when: str, names: dict) -> tuple[Status, str]:
    try:
        value = bool(evaluate(when, names))
    except UnknownName as exc:
        return "needs_review", f"`{when}`: {exc.args[0]} unavailable or below confidence threshold"
    return ("pass" if value else "fail"), f"`{when}` is {str(value).lower()}"


def _evaluate_rule(rule: EligibilityRule, names: dict, checks: dict[str, CheckResult], version: str) -> RuleResult:
    parts: list[tuple[Status, str]] = [
        (checks[c].status, f"{c}: {checks[c].status} ({checks[c].detail})") for c in rule.depends_on
    ]
    if rule.when is not None:
        parts.append(_evaluate_when(rule.when, names))

    status = combine([s for s, _ in parts])
    relevant = [note for s, note in parts if s == status]
    if status == "pass":
        reason = "All conditions met: " + "; ".join(relevant)
    elif status == "fail":
        reason = f"{rule.fail_reason} [{'; '.join(relevant)}]"
    else:
        reason = "Needs human review: " + "; ".join(relevant)
    return RuleResult(rule_id=rule.id, status=status, reason=reason, clause=rule.clause, rules_version=version)


def check_eligibility(scheme: Scheme, case: CaseIn, verification: VerificationResult) -> EligibilityResult:
    names = build_facts(scheme, case).names
    checks = {c.check_id: c for c in verification.checks}
    results = [_evaluate_rule(r, names, checks, scheme.version) for r in scheme.eligibility_rules]
    return EligibilityResult(results=results, overall=overall_from([r.status for r in results]),
                             rules_version=scheme.version)
