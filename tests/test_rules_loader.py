from pathlib import Path

import pytest
import yaml

from app.rules_loader import RulesError, load_scheme, parse_scheme

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


def _base() -> dict:
    return yaml.safe_load((RULES_DIR / "land_acquisition.yaml").read_text(encoding="utf-8"))


def test_loads_land_acquisition():
    scheme = load_scheme(RULES_DIR / "land_acquisition.yaml")
    assert scheme.scheme == "land_acquisition"
    assert scheme.version == "0.1.0"
    assert scheme.confidence_threshold == 0.85
    assert [c.id for c in scheme.compensation.components] == ["land_value", "assets_value", "solatium", "interest"]


def test_fuzzy_tolerance_is_parsed():
    scheme = parse_scheme(_base())
    name_match = next(c for c in scheme.verification_checks if c.id == "name_match")
    assert name_match.fuzzy_threshold == 0.9


def test_rejects_unsafe_rule_expression():
    data = _base()
    data["eligibility_rules"][0]["when"] = "__import__('os')"
    with pytest.raises(RulesError):
        parse_scheme(data)


def test_rejects_unknown_dependency():
    data = _base()
    data["eligibility_rules"][1]["depends_on"] = ["no_such_check"]
    with pytest.raises(RulesError):
        parse_scheme(data)


def test_rejects_check_across_undeclared_document():
    data = _base()
    data["verification_checks"][0]["across"] = ["application", "passport"]
    with pytest.raises(RulesError):
        parse_scheme(data)


def test_rejects_bad_tolerance():
    data = _base()
    data["verification_checks"][0]["tolerance"] = "roughly"
    with pytest.raises(RulesError):
        parse_scheme(data)


def test_rejects_rule_with_neither_when_nor_depends_on():
    data = _base()
    data["eligibility_rules"][0].pop("when")
    with pytest.raises(RulesError):
        parse_scheme(data)


def test_documents_declare_fields_to_extract():
    scheme = parse_scheme(_base())
    docs = {d.id: d for d in scheme.required_documents}
    assert docs["ownership_record"].fields == ["name", "survey_number", "area", "area_unit", "issue_date"]


def test_rejects_check_on_field_not_declared_for_document():
    data = _base()
    data["required_documents"][2]["fields"] = ["expiry_date"]   # identity_proof without `name`
    with pytest.raises(RulesError, match="name"):
        parse_scheme(data)


def test_rejects_validity_field_not_declared_for_document():
    data = _base()
    data["required_documents"][2]["fields"] = ["name"]          # identity_proof without expiry_date
    with pytest.raises(RulesError, match="expiry_date"):
        parse_scheme(data)
