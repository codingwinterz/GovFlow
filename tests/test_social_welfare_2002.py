"""Social welfare rebuilt from the published DSSS notification No. 50/354/02-03/HC/part-I/4247 dated 02/10/2002
(Directorate of Social Welfare, Goa: https://socialwelfare.goa.gov.in/?p=2518).

Every expected value here is derived by hand from that page, as summarised in the request of 2026-11-19:
residence by birth or 15 years of domicile; income limit Rs 24,000 a year; senior citizen 60+ at Rs 2,000 a month;
adult with a disability Rs 2,000 a month, 90 to 100% Rs 3,500 a month; widows and single women below 60 Rs 2,500 a
month. Annual amounts are the monthly amount x 12. The 80+ and minor-child supplements are gone.
"""
from pathlib import Path

import pytest

from app.assessment import assess_case
from app.case_model import CaseIn
from app.rules_loader import load_scheme_by_name
from app.self_check import self_check

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic" / "social_welfare"
YAML_TEXT = (ROOT / "rules" / "social_welfare.yaml").read_text(encoding="utf-8")
NOTE = ("2002 notification as published on the department site; later amendments not confirmed. A state commission "
        "has recommended raising the income limit, which is a recommendation, not law.")


def _flat(text: str) -> str:
    return " ".join(line.strip().lstrip("#").strip() for line in text.splitlines())


@pytest.fixture(scope="module")
def scheme():
    return load_scheme_by_name("social_welfare")


def _case(n: int) -> CaseIn:
    return CaseIn.model_validate_json((DATA / f"case_{n:02d}" / "case.json").read_text(encoding="utf-8"))


def _with(case: CaseIn, **changes) -> CaseIn:
    """A copy of the case with document fields changed: changes are doc__field=value."""
    data = case.model_dump()
    for key, value in changes.items():
        doc, field = key.split("__")
        data["documents"][doc]["fields"][field]["value"] = value
    return CaseIn.model_validate(data)


# --- the YAML carries the published values, its source and the note --------------------------------------------

def test_parameters_are_the_published_values(scheme):
    p = scheme.compensation.parameters
    assert p["min_residency_years"] == 15
    assert p["max_annual_income"] == 24000
    assert p["senior_min_age"] == 60
    assert p["senior_monthly"] == 2000
    assert p["adult_min_age"] == 18
    assert p["disability_monthly"] == 2000
    assert p["severe_disability_min_percent"] == 90
    assert p["severe_disability_monthly"] == 3500
    assert p["single_woman_monthly"] == 2500
    assert p["single_woman_max_age"] == 60
    assert p["single_woman_min_age"] == 18
    assert p["months_per_year"] == 12


def test_invented_supplements_are_gone(scheme):
    p = scheme.compensation.parameters
    for gone in ("high_age_bonus_annual", "minor_child_supplement_annual", "senior_base_annual", "widow_base_annual"):
        assert gone not in p
    assert [c.id for c in scheme.compensation.components] == ["base_pension"]
    category = next(d for d in scheme.required_documents if d.id == "category_proof")
    assert "minor_child_count" not in category.fields
    assert "minor_child_count" not in YAML_TEXT


def test_source_and_note(scheme):
    assert "4247" in scheme.source and "02/10/2002" in scheme.source
    flat = _flat(YAML_TEXT)
    assert NOTE in flat
    assert "socialwelfare.goa.gov.in/?p=2518" in flat
    assert scheme.sla_days == 30
    assert "VERIFY: 30-day SLA" in flat
    assert "VERIFY CONFLICT" in flat and "above 50" in flat          # single women: 18+ vs unmarried above 50


# --- the six synthetic cases, totals by hand ---------------------------------------------------------------------

EXPECTED = {   # case: (overall, base_pension = monthly x 12)
    1: ("eligible", 24000),       # senior 68, Rs 2,000 x 12
    2: ("eligible", 30000),       # widow 45, born in Goa, Rs 2,500 x 12
    3: ("not_eligible", 24000),   # senior, income Rs 36,000 > 24,000
    4: ("not_eligible", 42000),   # disability 92 %, 9 years in Goa (and shares SW-05's ID): Rs 3,500 x 12
    5: ("needs_review", 42000),   # same person, 18 years: duplicate ID only
    6: ("needs_review", 24000),   # senior 82 (no 80+ supplement), income read at 0.75
}


@pytest.mark.parametrize("n", sorted(EXPECTED))
def test_synthetic_case_outcome_and_amount(scheme, n):
    others = [_case(i) for i in sorted(EXPECTED)]
    result = assess_case(scheme, _case(n), others)
    overall, amount = EXPECTED[n]
    assert result.eligibility.overall == overall
    assert {i.component: i.amount for i in result.compensation.items} == {"base_pension": amount}


# --- boundaries -----------------------------------------------------------------------------------------------------

def _rule(scheme, case, rule_id):
    return {r.rule_id: r.status for r in assess_case(scheme, case, [case]).eligibility.results}[rule_id]


def _amount(scheme, case):
    return assess_case(scheme, case, [case]).compensation.total


@pytest.mark.parametrize("income, status", [(24000, "pass"), (24001, "fail"), (0, "pass")])
def test_income_limit_boundary(scheme, income, status):
    assert _rule(scheme, _with(_case(1), income_certificate__annual_income=income), "income_within_limit") == status


@pytest.mark.parametrize("born, years, status", [("no", 15, "pass"), ("no", 14, "fail"), ("yes", 3, "pass"), ("yes", 0, "pass")])
def test_residence_by_birth_or_15_years(scheme, born, years, status):
    case = _with(_case(1), residence_proof__born_in_goa=born, residence_proof__years_in_goa=years)
    assert _rule(scheme, case, "goa_residency_eligible") == status


@pytest.mark.parametrize("age, status", [(60, "pass"), (59, "fail")])
def test_senior_age_boundary(scheme, age, status):
    assert _rule(scheme, _with(_case(1), category_proof__age_years=age), "category_threshold_met") == status


@pytest.mark.parametrize("percent, amount", [(89, 24000), (90, 42000), (100, 42000), (40, 24000)])
def test_disability_rate_boundary(scheme, percent, amount):
    case = _with(_case(5), category_proof__disability_percent=percent)
    assert _amount(scheme, case) == amount


@pytest.mark.parametrize("age, status", [(18, "pass"), (17, "fail")])
def test_disability_is_for_adults(scheme, age, status):
    assert _rule(scheme, _with(_case(5), category_proof__age_years=age), "category_threshold_met") == status


@pytest.mark.parametrize("age, status, amount", [(59, "pass", 30000), (60, "fail", 0), (18, "pass", 30000), (17, "fail", 30000)])
def test_widow_below_60(scheme, age, status, amount):
    case = _with(_case(2), category_proof__age_years=age)
    assert _rule(scheme, case, "category_threshold_met") == status
    assert _amount(scheme, case) == amount


def test_self_check_uses_the_published_limit(scheme):
    base = {"residence_proof.born_in_goa": "no", "residence_proof.years_in_goa": "20",
            "category_proof.applicant_category": "senior_citizen"}
    assert self_check(scheme, {**base, "income_certificate.annual_income": "24000"}).outcome == "likely_eligible"
    assert self_check(scheme, {**base, "income_certificate.annual_income": "24001"}).outcome == "likely_not_eligible"
    born = {**base, "residence_proof.born_in_goa": "yes", "residence_proof.years_in_goa": "2",
            "income_certificate.annual_income": "12000"}
    assert self_check(scheme, born).outcome == "likely_eligible"
