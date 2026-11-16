"""Worked hand calculations for one case per scheme, checked input by input and line by line.

The numbers below were derived by hand from the YAML, not produced by app code.
"""

from pathlib import Path

import pytest

from app.assessment import assess_case
from app.case_model import CaseIn
from app.rules_loader import load_scheme_by_name

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"


def _load(scheme, n):
    return CaseIn.model_validate_json((DATA / scheme / f"case_{n}" / "case.json").read_text(encoding="utf-8"))


def _comp(scheme, n):
    return assess_case(load_scheme_by_name(scheme), _load(scheme, n), []).compensation


def test_la03_every_input_and_line():
    """LA-03 (land_acquisition.yaml 0.1.0)

    Inputs
      area_sqm             = 800        ownership_record.area 800, area_unit sqm -> 800 sqm
      market_value_per_sqm = 4000       case input
      assets_total         = 100000     case input
      multiplier           = 1.0        not supplied -> YAML default 1.0 (VERIFY)
      years                = 1.0        start sia_notification_date 2024-11-15;
                                        end = earliest of award 2026-11-15, possession 2025-11-15
                                            = 2025-11-15; 365 days / 365 = 1.0
    Parameters: solatium_rate 1.0, interest_rate 0.12

    land_value   = 800 x 4000 x 1.0                 = 3,200,000
    assets_value = 100,000                          =   100,000
    solatium     = (3,200,000 + 100,000) x 1.0      = 3,300,000
    interest     = 3,200,000 x 0.12 x 1.0           =   384,000
    total                                           = 6,984,000
    """
    comp = _comp("land_acquisition", "03")
    inputs = {i.name: i for i in comp.inputs}
    assert {n: i.value for n, i in inputs.items()} == pytest.approx(
        {"area_sqm": 800, "market_value_per_sqm": 4000, "assets_total": 100_000,
         "multiplier": 1.0, "years_since_notification": 1.0})
    assert "default 1" in inputs["multiplier"].source and "VERIFY" in inputs["multiplier"].source
    years = inputs["years_since_notification"].source
    assert "possession_date=2025-11-15" in years and "award_date=2026-11-15" in years and "= 365/365" in years
    assert {i.component: i.amount for i in comp.items} == {
        "land_value": 3_200_000, "assets_value": 100_000, "solatium": 3_300_000, "interest": 384_000}
    assert comp.total == 6_984_000


def test_dr03_every_input_and_line():
    """DR-03 (disaster_relief.yaml 0.1.0): kutcha house, hilly area, damage exactly 75%

    Inputs (damage_assessment, all read at confidence 0.97 >= 0.85)
      damage_percent = 75, house_type = kutcha, area_type = hilly
    Parameters: full_damage_threshold 75, partial_damage_threshold 15
    A comparison counts 1 when true, 0 when false.

    house_full_plain     = 120000 x (75>=75)=1 x (kutcha!=hut)=1 x (hilly==plain)=0  =       0
    house_full_hilly     = 130000 x (75>=75)=1 x (kutcha!=hut)=1 x (hilly==hilly)=1  = 130,000
    house_partial_pucca  =   6500 x (75>=15)=1 x (75<75)=0 x (kutcha==pucca)=0       =       0
    house_partial_kutcha =   4000 x (75>=15)=1 x (75<75)=0 x (kutcha==kutcha)=1      =       0
    hut                  =   8000 x (75>=15)=1 x (kutcha==hut)=0                     =       0
    clothing             =   2500 x (75>=15)=1                                       =   2,500
    utensils             =   2500 x (75>=15)=1                                       =   2,500
    total                                                                            = 135,000
    """
    comp = _comp("disaster_relief", "03")
    assert {i.name: i.value for i in comp.inputs} == {"damage_percent": 75, "house_type": "kutcha",
                                                     "area_type": "hilly"}
    assert {i.name: i.source for i in comp.inputs} == {n: f"damage_assessment.{n}" for n in
                                                      ("damage_percent", "house_type", "area_type")}
    assert {i.component: i.amount for i in comp.items} == {
        "house_full_plain": 0, "house_full_hilly": 130_000, "house_partial_pucca": 0,
        "house_partial_kutcha": 0, "hut": 0, "clothing": 2500, "utensils": 2500}
    assert comp.total == 135_000
