from datetime import date

from app.case_model import CaseIn
from app.facts import build_facts
from app.rules_loader import load_scheme_by_name

SCHEME = load_scheme_by_name("land_acquisition")


def _case(**docs) -> CaseIn:
    base = {
        "application": {"fields": {"name": {"value": "Asha Naik"}}},
        "ownership_record": {"fields": {
            "name": {"value": "Asha Naik", "confidence": 0.97},
            "area": {"value": 0.25, "confidence": 0.95},
            "area_unit": {"value": "hectare", "confidence": 0.95},
            "issue_date": {"value": "2026-10-01", "confidence": 0.95},
        }},
        "identity_proof": {"fields": {
            "name": {"value": "Asha Naik", "confidence": 0.96},
            "expiry_date": {"value": "2030-01-01", "confidence": 0.93},
        }},
        "survey_sheet": {"fields": {}},
        "mutation_record": {"fields": {"issue_date": {"value": "2026-06-01", "confidence": 0.9}}},
    }
    base.update(docs)
    base = {k: v for k, v in base.items() if v is not None}
    return CaseIn(case_id="T-1", scheme="land_acquisition", reference_date=date(2026, 11, 15), documents=base)


def test_present_documents_expose_confident_fields():
    facts = build_facts(SCHEME, _case())
    assert facts.names["ownership_record"]["present"] is True
    assert facts.names["ownership_record"]["name"] == "Asha Naik"


def test_low_confidence_field_is_withheld_and_recorded():
    case = _case(identity_proof={"fields": {
        "name": {"value": "Asha Naik", "confidence": 0.60},
        "expiry_date": {"value": "2030-01-01", "confidence": 0.93},
    }})
    facts = build_facts(SCHEME, case)
    assert "name" not in facts.names["identity_proof"]
    assert "identity_proof.name" in facts.low_confidence


def test_missing_document_is_marked_absent():
    facts = build_facts(SCHEME, _case(mutation_record=None))
    assert facts.names["mutation_record"] == {"present": False}
    assert facts.names["all_documents_present"] is False
    assert facts.missing_documents == ["mutation_record"]


def test_all_documents_present_when_complete():
    assert build_facts(SCHEME, _case()).names["all_documents_present"] is True


def test_area_is_normalised_to_square_metres():
    facts = build_facts(SCHEME, _case())
    assert facts.names["ownership_record"]["area_sqm"] == 2500


def test_unknown_area_unit_withholds_area_sqm():
    case = _case(ownership_record={"fields": {
        "name": {"value": "Asha Naik", "confidence": 0.97},
        "area": {"value": 3, "confidence": 0.95},
        "area_unit": {"value": "bigha", "confidence": 0.95},
        "issue_date": {"value": "2026-10-01", "confidence": 0.95},
    }})
    facts = build_facts(SCHEME, case)
    assert "area_sqm" not in facts.names["ownership_record"]


def test_all_documents_valid_when_dates_are_fine():
    facts = build_facts(SCHEME, _case())
    assert facts.names["all_documents_valid"] is True
    assert facts.validity == {"ownership_record": "valid", "identity_proof": "valid", "mutation_record": "valid"}


def test_expired_identity_proof_makes_documents_invalid():
    case = _case(identity_proof={"fields": {
        "name": {"value": "Asha Naik", "confidence": 0.96},
        "expiry_date": {"value": "2026-11-14", "confidence": 0.93},
    }})
    facts = build_facts(SCHEME, case)
    assert facts.validity["identity_proof"] == "expired"
    assert facts.names["all_documents_valid"] is False


def test_document_older_than_max_age_is_expired():
    case = _case(mutation_record={"fields": {"issue_date": {"value": "2025-11-01", "confidence": 0.9}}})
    assert build_facts(SCHEME, case).validity["mutation_record"] == "expired"


def test_expiry_on_reference_date_is_still_valid():
    case = _case(identity_proof={"fields": {
        "name": {"value": "Asha Naik", "confidence": 0.96},
        "expiry_date": {"value": "2026-11-15", "confidence": 0.93},
    }})
    assert build_facts(SCHEME, case).validity["identity_proof"] == "valid"


def test_unreadable_date_makes_validity_unknown_not_valid():
    case = _case(identity_proof={"fields": {
        "name": {"value": "Asha Naik", "confidence": 0.96},
        "expiry_date": {"value": "2030-01-01", "confidence": 0.50},
    }})
    facts = build_facts(SCHEME, case)
    assert facts.validity["identity_proof"] == "unknown"
    assert "all_documents_valid" not in facts.names


def test_expired_beats_unknown():
    case = _case(
        identity_proof={"fields": {"name": {"value": "Asha Naik"}, "expiry_date": {"value": "2020-01-01"}}},
        mutation_record={"fields": {}},
    )
    assert build_facts(SCHEME, case).names["all_documents_valid"] is False


def test_case_inputs_and_reference_date_are_available():
    case = _case()
    case.inputs = {"market_value_per_sqm": 3000}
    facts = build_facts(SCHEME, case)
    assert facts.names["case"]["market_value_per_sqm"] == 3000
    assert facts.names["reference_date"] == date(2026, 11, 15)
