import pytest

from app.compensation import compute_compensation
from app.rules_loader import load_scheme_by_name
from tests.test_verification import _case

SCHEME = load_scheme_by_name("land_acquisition")

BASE_INPUTS = {
    "market_value_per_sqm": 3000,
    "assets_total": 200_000,
    "interest_start_date": "2024-11-15",
    "interest_end_date": "2026-11-15",
}


def _compute(inputs=None, **case_kwargs):
    case = _case(**case_kwargs)
    case.inputs = BASE_INPUTS if inputs is None else inputs
    return compute_compensation(SCHEME, case)


def _amounts(result):
    return {i.component: i.amount for i in result.items}


def test_itemised_breakdown_in_yaml_order():
    result = _compute()
    assert result.status == "computed"
    assert [i.component for i in result.items] == ["land_value", "assets_value", "solatium", "interest"]
    assert _amounts(result) == {
        "land_value": 7_500_000,
        "assets_value": 200_000,
        "solatium": 7_700_000,      # uses land_value + assets_value computed above
        "interest": 1_800_000,      # 12% x 2.0 years on land_value
    }
    assert result.total == 17_200_000


def test_formula_note_shows_formula_and_values():
    note = next(i for i in _compute().items if i.component == "land_value").formula_note
    assert "area_sqm * market_value_per_sqm * multiplier" in note
    assert "area_sqm=2500" in note and "multiplier=1" in note


def test_inputs_cite_their_sources():
    inputs = {i.name: i for i in _compute().inputs}
    assert inputs["area_sqm"].source == "ownership_record.area_sqm"
    assert inputs["market_value_per_sqm"].source == "case.market_value_per_sqm"
    assert "default" in inputs["multiplier"].source and "VERIFY" in inputs["multiplier"].source


def test_case_multiplier_overrides_default():
    result = _compute({**BASE_INPUTS, "multiplier": 2.0})
    assert _amounts(result)["land_value"] == 15_000_000


def test_zero_assets():
    result = _compute({**BASE_INPUTS, "assets_total": 0})
    amounts = _amounts(result)
    assert amounts["assets_value"] == 0
    assert amounts["solatium"] == amounts["land_value"]


def test_interest_over_multiple_years_counts_leap_days():
    # 2023-11-15 -> 2026-11-15 is 1096 days (includes 29 Feb 2024); convention days/365
    result = _compute({**BASE_INPUTS, "interest_start_date": "2023-11-15"})
    assert _amounts(result)["interest"] == pytest.approx(7_500_000 * 0.12 * 1096 / 365, abs=0.01)


def test_missing_end_date_defaults_to_reference_date():
    inputs = {k: v for k, v in BASE_INPUTS.items() if k != "interest_end_date"}
    result = _compute(inputs)
    assert _amounts(result)["interest"] == 1_800_000   # reference date is 2026-11-15
    source = next(i for i in result.inputs if i.name == "years_since_notification").source
    assert "reference_date" in source


def test_missing_start_date_needs_review_and_is_never_guessed():
    inputs = {k: v for k, v in BASE_INPUTS.items() if k != "interest_start_date"}
    result = _compute(inputs)
    assert result.status == "needs_review"
    assert result.total is None
    assert "years_since_notification" in result.missing
    assert any("case.interest_start_date unavailable" in n for n in result.review_notes)
    assert "interest" not in _amounts(result)
    assert _amounts(result)["land_value"] == 7_500_000   # what can be computed still is


def test_end_before_start_needs_review():
    result = _compute({**BASE_INPUTS, "interest_end_date": "2024-01-01"})
    assert result.status == "needs_review"


def test_low_confidence_area_needs_review():
    case = _case()
    case.documents["ownership_record"].fields["area"].confidence = 0.5
    case.inputs = BASE_INPUTS
    result = compute_compensation(SCHEME, case)
    assert result.status == "needs_review"
    assert "area_sqm" in result.missing


def test_area_in_square_feet_gives_same_land_value():
    case = _case()
    case.documents["ownership_record"].fields["area"].value = 2500 / 0.09290304
    case.documents["ownership_record"].fields["area_unit"].value = "sq ft"
    case.inputs = BASE_INPUTS
    assert _amounts(compute_compensation(SCHEME, case))["land_value"] == pytest.approx(7_500_000, abs=0.01)


def test_amounts_are_rounded_to_paise():
    result = _compute({**BASE_INPUTS, "market_value_per_sqm": 1000.333})
    assert _amounts(result)["land_value"] == 2_500_832.5
