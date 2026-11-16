"""Runs every fixed synthetic case and compares with its hand-computed expected.json."""

import json
from pathlib import Path

import pytest

from app.assessment import assess_case
from app.case_model import CaseIn
from app.rules_loader import load_scheme_by_name

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
SCHEME = load_scheme_by_name("land_acquisition")


def _load_all() -> list[tuple[CaseIn, dict]]:
    pairs = []
    for folder in sorted(SET_DIR.glob("case_*")):
        case = CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8"))
        pairs.append((case, json.loads((folder / "expected.json").read_text(encoding="utf-8"))))
    return pairs


PAIRS = _load_all()
ALL_CASES = [c for c, _ in PAIRS]


def test_set_has_sixteen_cases():
    assert len(PAIRS) == 16


@pytest.mark.parametrize("case, expected", PAIRS, ids=[c.case_id for c, _ in PAIRS])
def test_case_matches_expected(case, expected):
    result = assess_case(SCHEME, case, ALL_CASES)

    assert {c.check_id: c.status for c in result.verification.checks} == expected["verification"]
    assert {r.rule_id: r.status for r in result.eligibility.results} == expected["eligibility"]["rules"]
    assert result.eligibility.overall == expected["eligibility"]["overall"]
    assert result.needs_human_review == expected["needs_human_review"]

    exp_comp = expected["compensation"]
    assert result.compensation.status == exp_comp["status"]
    assert {i.component: i.amount for i in result.compensation.items} == pytest.approx(exp_comp["items"], abs=0.005)
    if exp_comp["total"] is None:
        assert result.compensation.total is None
    else:
        assert result.compensation.total == pytest.approx(exp_comp["total"], abs=0.005)
