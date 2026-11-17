"""Build the evaluation namespace for one case.

Low-confidence fields are withheld from the namespace, so any rule or formula
that needs them hits UnknownName and is routed to human review. Fields with a declared
type are coerced here, once (extraction returns strings); a value that cannot be coerced
is withheld the same way, with its reason kept in `invalid`.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Optional

from app.case_model import CaseIn, DocumentIn
from app.confidence import needs_review_for_confidence
from app.field_types import coerce
from app.rules_loader import RequiredDocument, Scheme, Validity
from app.units import to_sqm

ValidityStatus = Literal["valid", "expired", "unknown"]


@dataclass
class CaseFacts:
    names: dict[str, Any]
    low_confidence: list[str] = field(default_factory=list)   # "doc_id.field"
    invalid: dict[str, str] = field(default_factory=dict)     # "doc_id.field" -> why it could not be coerced
    disagree: dict[str, str] = field(default_factory=dict)    # "doc_id.field" -> review reason (readers disagree)
    derived_from: dict[str, list[str]] = field(default_factory=dict)   # "doc.derived" -> its source refs
    missing_documents: list[str] = field(default_factory=list)
    validity: dict[str, ValidityStatus] = field(default_factory=dict)


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _confident_fields(req: RequiredDocument, doc: DocumentIn, threshold: float, facts: CaseFacts) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, fv in doc.fields.items():
        ref = f"{req.id}.{name}"
        if needs_review_for_confidence(fv.confidence, threshold):
            facts.low_confidence.append(ref)
            continue
        if fv.review_reason:                # e.g. two readers disagree: withheld whatever the confidence
            facts.disagree[ref] = fv.review_reason
            continue
        if name not in req.types:           # not declared by the scheme: passed through unchanged
            fields[name] = fv.value
            continue
        value, error = coerce(req.types[name], fv.value, req.options.get(name))
        if error:
            facts.invalid[ref] = error
            continue
        fields[name] = value
    return fields


def missing_reason(expr: str, facts: CaseFacts) -> Optional[str]:
    """Why an expression could not use a document field: invalid value or low confidence."""
    def used(ref: str) -> bool:
        return ref in expr or any(ref in sources and derived in expr
                                  for derived, sources in facts.derived_from.items())
    reasons = [f"{ref}: {why}" for ref, why in facts.invalid.items() if used(ref)]
    reasons += [f"{ref}: at or below the confidence threshold" for ref in facts.low_confidence if used(ref)]
    reasons += [f"{ref}: {why}" for ref, why in facts.disagree.items() if used(ref)]
    return "; ".join(reasons) or None


def _add_derived(req: RequiredDocument, fields: dict[str, Any], facts: CaseFacts) -> None:
    """Fields the scheme YAML declares as derived (units were validated during coercion)."""
    for name, d in req.derived.items():
        facts.derived_from[f"{req.id}.{name}"] = [f"{req.id}.{d.convert}", f"{req.id}.{d.unit_field}"]
        if d.convert in fields and d.unit_field in fields:
            fields[name] = to_sqm(float(fields[d.convert]), str(fields[d.unit_field]))


def _check_plausible(req: RequiredDocument, fields: dict[str, Any], facts: CaseFacts) -> None:
    """Withhold a value outside the YAML's plausible range, as for an unreadable one: rules that need it go to
    review. Confidence is irrelevant here, so a document cannot talk its way past the check."""
    for name, (lo, hi) in req.plausible.items():
        if name in fields and not lo <= float(fields[name]) <= hi:
            facts.invalid[f"{req.id}.{name}"] = f"outside the plausible range {lo:g} to {hi:g}"
            del fields[name]


def _validity(fields: dict[str, Any], rule: Validity, ref: date) -> ValidityStatus:
    if rule.expiry_field:
        expiry = _parse_date(fields.get(rule.expiry_field))
        if expiry is None:
            return "unknown"
        return "valid" if ref <= expiry else "expired"
    issued = _parse_date(fields.get(rule.date_field))
    if issued is None or issued > ref:
        return "unknown"
    return "valid" if (ref - issued).days <= rule.max_age_days else "expired"


def _overall_validity(validity: dict[str, ValidityStatus]) -> Optional[bool]:
    if "expired" in validity.values():
        return False
    if "unknown" in validity.values():
        return None
    return True


def build_facts(scheme: Scheme, case: CaseIn) -> CaseFacts:
    params = dict(scheme.compensation.parameters) if scheme.compensation else {}
    facts = CaseFacts(names={"case": dict(case.inputs), "reference_date": case.reference_date, "params": params})
    for req in scheme.required_documents:
        doc = case.documents.get(req.id)
        if doc is None:
            facts.names[req.id] = {"present": False}
            facts.missing_documents.append(req.id)
            continue
        fields = _confident_fields(req, doc, scheme.confidence_threshold, facts)
        _add_derived(req, fields, facts)
        _check_plausible(req, fields, facts)
        if req.validity:
            facts.validity[req.id] = _validity(fields, req.validity, case.reference_date)
        facts.names[req.id] = {"present": True, **fields}

    facts.names["all_documents_present"] = not facts.missing_documents
    overall = _overall_validity(facts.validity)
    if overall is not None:   # unknown validity is withheld -> rules route to review
        facts.names["all_documents_valid"] = overall
    return facts
