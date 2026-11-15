"""Build the evaluation namespace for one case.

Low-confidence fields are withheld from the namespace, so any rule or formula
that needs them hits UnknownName and is routed to human review.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Optional

from app.case_model import CaseIn, DocumentIn
from app.rules_loader import Scheme, Validity
from app.units import UnknownUnit, to_sqm

ValidityStatus = Literal["valid", "expired", "unknown"]


@dataclass
class CaseFacts:
    names: dict[str, Any]
    low_confidence: list[str] = field(default_factory=list)   # "doc_id.field"
    missing_documents: list[str] = field(default_factory=list)
    validity: dict[str, ValidityStatus] = field(default_factory=dict)


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _confident_fields(doc_id: str, doc: DocumentIn, threshold: float, low: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, fv in doc.fields.items():
        if fv.confidence >= threshold:
            fields[name] = fv.value
        else:
            low.append(f"{doc_id}.{name}")
    return fields


def _add_area_sqm(fields: dict[str, Any]) -> None:
    if "area" in fields and "area_unit" in fields:
        try:
            fields["area_sqm"] = to_sqm(float(fields["area"]), str(fields["area_unit"]))
        except (UnknownUnit, ValueError):
            pass


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
    facts = CaseFacts(names={"case": dict(case.inputs), "reference_date": case.reference_date})
    for req in scheme.required_documents:
        doc = case.documents.get(req.id)
        if doc is None:
            facts.names[req.id] = {"present": False}
            facts.missing_documents.append(req.id)
            continue
        fields = _confident_fields(req.id, doc, scheme.confidence_threshold, facts.low_confidence)
        _add_area_sqm(fields)
        if req.validity:
            facts.validity[req.id] = _validity(fields, req.validity, case.reference_date)
        facts.names[req.id] = {"present": True, **fields}

    facts.names["all_documents_present"] = not facts.missing_documents
    overall = _overall_validity(facts.validity)
    if overall is not None:   # unknown validity is withheld -> rules route to review
        facts.names["all_documents_valid"] = overall
    return facts
