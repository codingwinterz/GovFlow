"""Config-format features: parameters in rules, list membership, case-insensitive text,
declared derived fields, and display labels. Each keeps scheme specifics in YAML."""

from pathlib import Path

import pytest
import yaml

from app.assessment import assess_case
from app.case_model import CaseIn
from app.rules_loader import RULES_DIR, RulesError, load_scheme_by_name, parse_scheme

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"


def _yaml(name):
    return yaml.safe_load((RULES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def _case(scheme, n):
    return CaseIn.model_validate_json((DATA / scheme / f"case_{n:02d}" / "case.json").read_text(encoding="utf-8"))


def _rule(result, rule_id):
    return next(r for r in result.eligibility.results if r.rule_id == rule_id)


# --- 2. rules read scheme parameters --------------------------------------------------------

def test_minimum_damage_has_one_source_of_truth():
    data = _yaml("disaster_relief")
    (rule,) = [r for r in data["eligibility_rules"] if r["id"] == "damage_category_eligible"]
    assert "params.partial_damage_threshold" in rule["when"] and "15" not in rule["when"]


def test_changing_the_parameter_moves_both_the_rule_and_the_relief():
    data = _yaml("disaster_relief")
    data["compensation"]["parameters"]["partial_damage_threshold"] = 10
    result = assess_case(parse_scheme(data), _case("disaster_relief", 6), [])      # 14.9% damage
    assert _rule(result, "damage_category_eligible").status == "pass"
    assert {i.component: i.amount for i in result.compensation.items}["house_partial"] == 10000


def test_rule_reason_shows_the_parameter_it_used():
    result = assess_case(load_scheme_by_name("disaster_relief"), _case("disaster_relief", 6), [])
    assert "params.partial_damage_threshold" in _rule(result, "damage_category_eligible").reason


def test_unknown_parameter_fails_at_load():
    data = _yaml("disaster_relief")
    (rule,) = [r for r in data["eligibility_rules"] if r["id"] == "damage_category_eligible"]
    rule["when"] = "damage_assessment.damage_percent >= params.minimum_damage"
    with pytest.raises(RulesError, match="minimum_damage"):
        parse_scheme(data)


def test_params_is_reserved_as_a_document_id():
    data = _yaml("disaster_relief")
    data["required_documents"][0]["id"] = "params"
    with pytest.raises(RulesError, match="params"):
        parse_scheme(data)
