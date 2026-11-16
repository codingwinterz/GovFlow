"""Self-check before applying: a dry run of the scheme's own eligibility conditions on answers to
the questions its YAML declares. Nothing is created or stored. The result is a guide, not a decision."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

from app.case_model import CaseIn, DocumentIn, FieldValue
from app.facts import build_facts
from app.rules_engine import evaluate_when
from app.rules_loader import Scheme

GUIDE_LABEL = "This is a guide, not a decision. Only an officer decides."
Outcome = Literal["likely_eligible", "likely_not_eligible", "need_more_information"]


class NoSelfCheck(ValueError):
    """The scheme declares no self-check questions."""


class RuleGuide(BaseModel):
    rule_id: str
    status: Literal["pass", "fail", "needs_review"]
    message: str


class SelfCheckResult(BaseModel):
    scheme: str
    outcome: Outcome
    rules: list[RuleGuide]
    documents_to_bring: list[str]
    checked_when_you_apply: list[str]   # cross-document checks that need the real documents
    guide_label: str = GUIDE_LABEL
    rules_version: str


def _hypothetical_case(scheme: Scheme, answers: dict[str, str]) -> CaseIn:
    documents: dict[str, DocumentIn] = {}
    for ref, value in answers.items():
        doc_id, field = ref.split(".", 1)
        documents.setdefault(doc_id, DocumentIn()).fields[field] = FieldValue(value=value, confidence=1.0)
    return CaseIn(case_id="SELF-CHECK", scheme=scheme.scheme, reference_date=date.today(), documents=documents)


def self_check(scheme: Scheme, answers: dict[str, str]) -> SelfCheckResult:
    if scheme.self_check is None:
        raise NoSelfCheck(f"Scheme {scheme.scheme} has no self-check")
    asked = {q.field for q in scheme.self_check.questions}
    unknown = sorted(set(answers) - asked)
    if unknown:
        raise ValueError(f"{unknown} is not a self-check question")
    given = {k: v for k, v in answers.items() if str(v).strip()}
    facts = build_facts(scheme, _hypothetical_case(scheme, given))
    rules = {r.id: r for r in scheme.eligibility_rules}
    guides: list[RuleGuide] = []
    for rule_id in scheme.self_check.rules:
        rule = rules[rule_id]
        status, reason = evaluate_when(rule.when, facts)
        unanswered = [q for q in sorted(asked) if q in rule.when and q not in given]
        if status == "needs_review":
            message = f"Please answer: {', '.join(unanswered)}" if unanswered else reason   # reason names the field
        else:
            message = rule.fail_reason if status == "fail" else "Looks fine from your answers."
        guides.append(RuleGuide(rule_id=rule_id, status=status, message=message))
    statuses = {g.status for g in guides}
    outcome: Outcome = ("likely_not_eligible" if "fail" in statuses
                        else "need_more_information" if "needs_review" in statuses else "likely_eligible")
    return SelfCheckResult(scheme=scheme.scheme, outcome=outcome, rules=guides,
                           documents_to_bring=scheme.document_ids,
                           checked_when_you_apply=[c.id for c in scheme.verification_checks],
                           rules_version=scheme.version)


def public_questions(scheme: Scheme) -> Optional[dict]:
    if scheme.self_check is None:
        return None
    types = {f"{d.id}.{f}": t for d in scheme.required_documents for f, t in d.types.items()}
    return {"scheme": scheme.scheme, "labels": scheme.labels, "guide_label": GUIDE_LABEL,
            "documents": scheme.document_ids, "terms": scheme.terms,
            "questions": [{"field": q.field, "prompt": q.prompt, "type": types[q.field], "choices": q.choices}
                          for q in scheme.self_check.questions]}
