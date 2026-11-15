from app.assessment import assess_case
from app.rules_loader import load_scheme_by_name
from tests.test_compensation import BASE_INPUTS
from tests.test_verification import _case

SCHEME = load_scheme_by_name("land_acquisition")


def _with_inputs(case):
    case.inputs = dict(BASE_INPUTS)
    return case


def test_clean_case_needs_no_human_review():
    result = assess_case(SCHEME, _with_inputs(_case()))
    assert result.eligibility.overall == "eligible"
    assert result.compensation.status == "computed"
    assert result.needs_human_review is False
    assert result.review_reasons == []


def test_any_flag_routes_to_human_review():
    result = assess_case(SCHEME, _with_inputs(_case(id_name="Vinod Shetty")))
    assert result.needs_human_review is True
    assert any("name_match" in r for r in result.review_reasons)


def test_compensation_gap_routes_to_human_review():
    case = _with_inputs(_case())
    del case.inputs["interest_start_date"]
    result = assess_case(SCHEME, case)
    assert result.eligibility.overall == "eligible"
    assert result.needs_human_review is True
