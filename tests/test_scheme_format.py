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
    assert {i.component: i.amount for i in result.compensation.items}["hut"] == 8000      # DR-06 is a hut


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


# --- 3. list membership and case-insensitive text --------------------------------------------

from app.safe_eval import UnsafeExpression, check_expression, evaluate, names_in


@pytest.mark.parametrize("expr, names, expected", [
    ("x in ['a', 'b']", {"x": "a"}, True), ("x in ['a', 'b']", {"x": "c"}, False),
    ("x not in ('a', 'b')", {"x": "c"}, True), ("x in [y, 'b']", {"x": 3, "y": 3}, True),
    ("lower(x) == 'yes'", {"x": "Yes"}, True), ("lower(x) == 'yes'", {"x": " YES "}, True),
    ("lower(x) in ['siolim', 'anjuna']", {"x": " Siolim "}, True), ("lower(x) == lower(y)", {"x": "Asha  Naik", "y": "asha naik"}, True),
])
def test_membership_and_lower(expr, names, expected):
    check_expression(expr)
    assert evaluate(expr, names) is expected


def test_in_needs_a_list_not_a_string():
    with pytest.raises(TypeError):
        evaluate("x in 'abc'", {"x": "a"})          # no accidental substring matching


def test_lower_only_accepts_text():
    with pytest.raises(TypeError):
        evaluate("lower(x) == 'yes'", {"x": 5})


@pytest.mark.parametrize("expr", ["upper(x)", "x.lower()", "lower(x, y)", "lower(x=1)", "lower(*x)", "open('f')",
                                  "[c for c in x]", "{'a': 1}", "lower(x)(y)"])
def test_other_calls_and_constructs_stay_forbidden(expr):
    with pytest.raises(UnsafeExpression):
        check_expression(expr)
    with pytest.raises(UnsafeExpression):
        evaluate(expr, {"x": "a", "y": "b", "lower": str.lower, "upper": str.upper, "open": open})


def test_function_names_are_not_reported_as_inputs():
    assert names_in("lower(a.b) == c") == ["a", "c"]


@pytest.mark.parametrize("value, status", [("yes", "pass"), ("Yes", "pass"), (" YES ", "pass"), ("no", "fail")])
def test_notified_area_compares_case_insensitively(value, status):
    case = _case("disaster_relief", 1)
    case.documents["damage_assessment"].fields["notified_area"].value = value
    result = assess_case(load_scheme_by_name("disaster_relief"), case, [])
    assert _rule(result, "residence_in_affected_area").status == status


# --- 4. derived fields are declared per scheme ------------------------------------------------

import ast as _ast

from app.facts import build_facts


def test_shared_facts_code_has_no_area_convention():
    tree = _ast.parse((Path(__file__).resolve().parent.parent / "app" / "facts.py").read_text(encoding="utf-8"))
    texts = {n.value for n in _ast.walk(tree) if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
    assert not texts & {"area", "area_unit", "area_sqm"}


def test_land_yaml_declares_area_sqm():
    for doc in ("ownership_record", "survey_sheet"):
        (d,) = [x for x in _yaml("land_acquisition")["required_documents"] if x["id"] == doc]
        assert d["derived"]["area_sqm"] == {"convert": "area", "unit_field": "area_unit", "to": "sqm"}


def test_area_sqm_is_not_derived_unless_declared():
    data = _yaml("land_acquisition")
    for d in data["required_documents"]:
        d.pop("derived", None)
        d.pop("plausible", None)        # its bounds are on the derived field, which no longer exists
    scheme = parse_scheme(data)
    facts = build_facts(scheme, _case("land_acquisition", 1))
    assert "area_sqm" not in facts.names["ownership_record"]
    assert assess_case(scheme, _case("land_acquisition", 1), []).compensation.status == "needs_review"


def test_declared_derived_field_is_computed():
    facts = build_facts(load_scheme_by_name("land_acquisition"), _case("land_acquisition", 1))
    assert facts.names["ownership_record"]["area_sqm"] == pytest.approx(2500.0)    # 0.25 ha


def test_bad_unit_reason_reaches_the_compensation_note_through_the_derived_field():
    case = _case("land_acquisition", 1)
    case.documents["ownership_record"].fields["area_unit"].value = "bigha"
    result = assess_case(load_scheme_by_name("land_acquisition"), case, [])
    assert any("ownership_record.area_unit" in n and "bigha" in n for n in result.compensation.review_notes)


@pytest.mark.parametrize("derived, match", [
    ({"convert": "acreage", "unit_field": "area_unit", "to": "sqm"}, "acreage"),
    ({"convert": "survey_number", "unit_field": "area_unit", "to": "sqm"}, "number"),
    ({"convert": "area", "unit_field": "issue_date", "to": "sqm"}, "unit"),
    ({"convert": "area", "unit_field": "area_unit", "to": "furlong"}, "furlong"),
])
def test_bad_derived_declarations_fail_at_load(derived, match):
    data = _yaml("land_acquisition")
    (d,) = [x for x in data["required_documents"] if x["id"] == "ownership_record"]
    d["derived"]["area_sqm"] = derived
    with pytest.raises(RulesError, match=match):
        parse_scheme(data)


# --- 5. display labels per scheme ----------------------------------------------------------------

def test_each_scheme_has_its_own_labels():
    assert load_scheme_by_name("land_acquisition").labels["amounts"] == "Compensation"
    assert load_scheme_by_name("disaster_relief").labels["amounts"] == "Relief"


def test_labels_are_required():
    data = _yaml("disaster_relief")
    del data["labels"]["total"]
    with pytest.raises(RulesError, match="total"):
        parse_scheme(data)


def test_unknown_label_is_rejected():
    data = _yaml("disaster_relief")
    data["labels"]["subtitle"] = "x"
    with pytest.raises(RulesError, match="subtitle"):
        parse_scheme(data)


def test_api_serves_labels_in_scheme_list_and_case_detail(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.case_store import seed_case
    from app.main import create_app
    from app.models import Base
    from tests.asgi_client import call
    from tests.auth_headers import staff
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_case(s, _case("disaster_relief", 1))
    app = create_app(engine=engine, upload_dir=tmp_path)
    officer = staff("officer", "O-1")
    schemes = {s["scheme"]: s for s in call(app, "GET", "/schemes", headers=officer)[1]}
    assert schemes["disaster_relief"]["labels"]["total"] == "Total relief"
    assert schemes["land_acquisition"]["labels"]["total"] == "Total compensation"
    assert call(app, "GET", "/cases/DR-01", headers=officer)[1]["labels"]["amounts"] == "Relief"
