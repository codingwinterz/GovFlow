"""(b) A rule option `on_false: needs_review`: a false `when` routes the case to review instead of `fail`, so a
requirement such as "notice to all co-owners" never reads as "Not eligible". The default stays `fail`, so every
existing scheme is unchanged. A failed verification check the rule depends on still fails."""

import copy
from pathlib import Path

import pytest
import yaml

from app.case_model import CaseIn
from app.rules_engine import check_eligibility
from app.rules_loader import RulesError, load_scheme_by_name, parse_scheme, scheme_names
from app.self_check import self_check
from app.verification import verify_documents

ROOT = Path(__file__).resolve().parent.parent
RELIEF = yaml.safe_load((ROOT / "rules" / "disaster_relief.yaml").read_text(encoding="utf-8"))
RULE = "damage_category_eligible"   # when: damage_assessment.damage_percent >= params.partial_damage_threshold


def _scheme(on_false=None, rule=RULE):
    data = copy.deepcopy(RELIEF)
    if on_false is not None:
        next(r for r in data["eligibility_rules"] if r["id"] == rule)["on_false"] = on_false
    return parse_scheme(data)


def _case(damage_percent):
    case = CaseIn.model_validate_json((ROOT / "data" / "synthetic" / "disaster_relief" / "case_01" / "case.json")
                                      .read_text(encoding="utf-8"))
    case.documents["damage_assessment"].fields["damage_percent"].value = damage_percent
    return case


def _result(scheme, case):
    result = check_eligibility(scheme, case, verify_documents(scheme, case))
    return result, next(r for r in result.results if r.rule_id == RULE)


def test_default_is_fail_and_no_existing_scheme_sets_it():
    for name in ("land_acquisition", "disaster_relief", "social_welfare"):
        assert {r.on_false for r in load_scheme_by_name(name).eligibility_rules} == {"fail"}


def test_without_the_option_a_false_condition_fails():
    result, rule = _result(_scheme(), _case(5))
    assert rule.status == "fail" and result.overall == "not_eligible"


def test_with_the_option_a_false_condition_needs_review_and_names_the_requirement():
    scheme = _scheme("needs_review")
    result, rule = _result(scheme, _case(5))
    fail_reason = next(r.fail_reason for r in scheme.eligibility_rules if r.id == RULE)
    assert rule.status == "needs_review" and result.overall == "needs_review"
    assert rule.reason.startswith("Needs human review: " + fail_reason)
    assert "is false" in rule.reason


def test_with_the_option_a_true_condition_still_passes():
    result, rule = _result(_scheme("needs_review"), _case(60))
    assert rule.status == "pass" and result.overall == "eligible"


def test_the_option_does_not_soften_a_failed_dependency():
    """Only the rule's own condition is routed; a verification check it depends on that fails still fails."""
    scheme = _scheme("needs_review", rule="identity_verified")
    case = _case(60)
    case.documents["identity_proof"].fields["name"].value = "Somebody Entirely Different"
    result = check_eligibility(scheme, case, verify_documents(scheme, case))
    assert next(r for r in result.results if r.rule_id == "identity_verified").status == "fail"


def test_an_unreadable_value_still_needs_review_as_before():
    case = _case(5)
    case.documents["damage_assessment"].fields["damage_percent"].confidence = 0.5
    _, rule = _result(_scheme("needs_review"), case)
    assert rule.status == "needs_review" and "is false" not in rule.reason


def test_only_fail_or_needs_review_are_allowed():
    with pytest.raises(RulesError):
        _scheme("pass")


def test_the_option_needs_a_when_condition():
    data = copy.deepcopy(RELIEF)
    rule = next(r for r in data["eligibility_rules"] if r.get("depends_on") and r.get("when") is None)
    rule["on_false"] = "needs_review"
    with pytest.raises(RulesError, match="on_false"):
        parse_scheme(data)


def test_self_check_reports_the_requirement_instead_of_likely_not_eligible():
    answers = {"damage_assessment.damage_percent": "5", "damage_assessment.notified_area": "yes"}
    assert self_check(_scheme(), answers).outcome == "likely_not_eligible"
    scheme = _scheme("needs_review")
    result = self_check(scheme, answers)
    fail_reason = next(r.fail_reason for r in scheme.eligibility_rules if r.id == RULE)
    guide = next(g for g in result.rules if g.rule_id == RULE)
    assert result.outcome == "need_more_information"
    assert guide.status == "needs_review" and guide.message == fail_reason
