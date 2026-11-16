"""Disaster relief amounts per MHA SDRF norms 2022-26, by house type, area type and damage."""

from pathlib import Path

import pytest
import yaml

from app.assessment import assess_case
from app.case_model import CaseIn
from app.field_types import coerce
from app.rules_loader import RULES_DIR, RulesError, load_scheme_by_name, parse_scheme

DR = load_scheme_by_name("disaster_relief")
DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "disaster_relief"
ZERO = {"house_full_plain": 0, "house_full_hilly": 0, "house_partial_pucca": 0, "house_partial_kutcha": 0,
        "hut": 0, "clothing": 0, "utensils": 0}
ITEMS = {"clothing": 2500, "utensils": 2500}


def _case(damage, house, area):
    case = CaseIn.model_validate_json((DATA / "case_01" / "case.json").read_text(encoding="utf-8"))
    f = case.documents["damage_assessment"].fields
    f["damage_percent"].value, f["house_type"].value, f["area_type"].value = damage, house, area
    return case


def _amounts(damage, house, area):
    result = assess_case(DR, _case(damage, house, area), [])
    return result, {i.component: i.amount for i in result.compensation.items}


def test_source_is_labelled_with_the_norms_and_their_status():
    assert DR.source == "MHA norms 2022-26; current schedule to be confirmed"


@pytest.mark.parametrize("damage, house, area, expected", [
    (80, "pucca", "plain", {"house_full_plain": 120000, **ITEMS}),
    (80, "kutcha", "plain", {"house_full_plain": 120000, **ITEMS}),
    (75, "pucca", "hilly", {"house_full_hilly": 130000, **ITEMS}),         # 75% boundary is full damage
    (74.9, "pucca", "plain", {"house_partial_pucca": 6500, **ITEMS}),
    (40, "pucca", "hilly", {"house_partial_pucca": 6500, **ITEMS}),        # partial amounts do not vary by area
    (15, "kutcha", "plain", {"house_partial_kutcha": 4000, **ITEMS}),      # 15% boundary is partial
    (60, "hut", "plain", {"hut": 8000, **ITEMS}),
    (90, "hut", "hilly", {"hut": 8000, **ITEMS}),                          # a hut never gets the house amount,
    (80, "hut", "plain", {"hut": 8000, **ITEMS}),                          # in a hilly or a plain area
    (14.9, "pucca", "plain", {}),                                          # below the minimum: nothing
])
def test_relief_amounts_by_category(damage, house, area, expected):
    _, amounts = _amounts(damage, house, area)
    assert amounts == {**ZERO, **expected}


@pytest.mark.parametrize("house, area", [("Pucca", "Plain"), (" HUT ", " hilly ")])
def test_categories_are_matched_case_insensitively(house, area):
    result, _ = _amounts(60, house, area)
    assert result.compensation.status == "computed"


@pytest.mark.parametrize("field, value", [("house_type", "concrete"), ("area_type", "coastal"), ("house_type", "")])
def test_unknown_category_goes_to_review_never_zero_relief(field, value):
    case = _case(80, "pucca", "plain")
    case.documents["damage_assessment"].fields[field].value = value
    result = assess_case(DR, case, [])
    assert result.compensation.status == "needs_review" and result.compensation.total is None
    (flag,) = [f for f in result.verification.flags if f.kind == "invalid_value"]
    assert f"damage_assessment.{field}" in flag.detail


@pytest.mark.parametrize("raw, value", [("Pucca", "pucca"), (" HUT ", "hut"), ("kutcha", "kutcha")])
def test_one_of_coercion_returns_the_canonical_option(raw, value):
    assert coerce("one_of", raw, ["pucca", "kutcha", "hut"]) == (value, None)


def test_one_of_rejects_other_values_with_the_options():
    value, error = coerce("one_of", "concrete", ["pucca", "kutcha", "hut"])
    assert value is None and "concrete" in error and "pucca, kutcha, hut" in error


def test_one_of_needs_options_in_the_yaml():
    data = yaml.safe_load((RULES_DIR / "disaster_relief.yaml").read_text(encoding="utf-8"))
    data["required_documents"][3]["fields"]["house_type"] = {"one_of": []}
    with pytest.raises(RulesError, match="house_type"):
        parse_scheme(data)


def _synthetic(n):
    return CaseIn.model_validate_json((DATA / f"case_{n}" / "case.json").read_text(encoding="utf-8"))


COMPONENTS = list(ZERO)


def test_dr09_no_assessment_means_no_relief_line_is_computed():
    """No damage assessment: none of the three inputs exists, every component needs damage_percent,
    so no line is computed and the total is withheld (never zero)."""
    comp = assess_case(DR, _synthetic("09"), []).compensation
    assert comp.status == "needs_review" and comp.items == [] and comp.total is None and comp.inputs == []
    assert comp.missing == ["damage_percent", "house_type", "area_type", *COMPONENTS]
    assert "damage_percent: damage_assessment.damage_percent unavailable" in comp.review_notes


def test_dr14_low_confidence_damage_withholds_relief_but_not_the_other_inputs():
    """damage_percent 60 read at confidence 0.6 (< 0.85): withheld; house_type and area_type still resolve."""
    comp = assess_case(DR, _synthetic("14"), []).compensation
    assert comp.status == "needs_review" and comp.items == [] and comp.total is None
    assert {i.name: i.value for i in comp.inputs} == {"house_type": "pucca", "area_type": "plain"}
    assert comp.missing == ["damage_percent", *COMPONENTS]
    assert "damage_assessment.damage_percent: below the confidence threshold" in comp.review_notes[0]


def test_dr14_once_the_damage_reading_is_confirmed_gets_partial_pucca_relief():
    """Hand-derived: 60% pucca plain is >= 15 and < 75, so partial pucca 6500 + clothing 2500 + utensils 2500."""
    case = _synthetic("14")
    case.documents["damage_assessment"].fields["damage_percent"].confidence = 0.97
    comp = assess_case(DR, case, []).compensation
    assert {i.component: i.amount for i in comp.items} == {**ZERO, "house_partial_pucca": 6500, **ITEMS}
    assert comp.total == 11500


def test_norm_amounts_are_parameters():
    p = DR.compensation.parameters
    assert (p["full_house_plain"], p["full_house_hilly"], p["partial_pucca"], p["partial_kutcha"], p["hut"],
            p["clothing"], p["utensils"]) == (120000, 130000, 6500, 4000, 8000, 2500, 2500)
