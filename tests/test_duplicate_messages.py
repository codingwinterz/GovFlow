"""The duplicate-claim check's wording comes from each scheme's YAML; shared code has none."""

import ast
import copy
import json
from pathlib import Path

import pytest
import yaml

from app.assessment import assess_case
from app.case_model import CaseIn
from app.rules_loader import RULES_DIR, RulesError, load_scheme_by_name, parse_scheme

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"


def _yaml(scheme):
    return yaml.safe_load((RULES_DIR / f"{scheme}.yaml").read_text(encoding="utf-8"))


def _dup(data):
    return next(c for c in data["verification_checks"] if c.get("builtin") == "duplicate_claim")


def _cases(scheme):
    return [CaseIn.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted((DATA / scheme).glob("case_*/case.json"))]


def _detail(scheme, case_id, scheme_obj=None):
    cases = _cases(scheme)
    case = next(c for c in cases if c.case_id == case_id)
    result = assess_case(scheme_obj or load_scheme_by_name(scheme), case, cases)
    return next(c.detail for c in result.verification.checks if c.check_id == "duplicate_claim")


def test_shared_verification_code_has_no_scheme_wording():
    tree = ast.parse((ROOT / "app" / "verification.py").read_text(encoding="utf-8"))
    texts = [n.value.lower() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for word in ("survey", "co-owner", "areas unknown", "overlap", "house", "relief"):
        assert not [t for t in texts if word in t], word


def test_disaster_relief_wording_comes_from_its_yaml():
    template = _dup(_yaml("disaster_relief"))["messages"]["competing"]
    assert _detail("disaster_relief", "DR-10") == template.format(ids="DR-11", key="Morjim/H-7")
    assert "area" not in _detail("disaster_relief", "DR-10").lower()


def test_disaster_relief_no_longer_needs_an_area_stand_in():
    assert "claimed_area" not in _dup(_yaml("disaster_relief"))


def test_land_wording_is_unchanged_but_now_lives_in_yaml():
    assert "co-owners" in _dup(_yaml("land_acquisition"))["messages"]["within_total"]
    assert _detail("land_acquisition", "LA-01") == "No other open case claims 123/4."


def test_changing_the_yaml_template_changes_the_message():
    data = _yaml("disaster_relief")
    _dup(data)["messages"]["competing"] = "Same house {key} also in {ids}."
    assert _detail("disaster_relief", "DR-10", parse_scheme(data)) == "Same house Morjim/H-7 also in DR-11."


@pytest.mark.parametrize("scheme", ["land_acquisition", "disaster_relief"])
def test_duplicate_check_without_messages_is_rejected(scheme):
    data = _yaml(scheme)
    del _dup(data)["messages"]
    with pytest.raises(RulesError, match="messages"):
        parse_scheme(data)


def test_missing_required_message_is_rejected():
    data = _yaml("land_acquisition")
    del _dup(data)["messages"]["within_total"]
    with pytest.raises(RulesError, match="within_total"):
        parse_scheme(data)


def test_unknown_placeholder_is_rejected():
    data = _yaml("disaster_relief")
    _dup(data)["messages"]["competing"] = "Duplicate of {case_number}"
    with pytest.raises(RulesError, match="case_number"):
        parse_scheme(data)


def test_total_without_claimed_amount_is_rejected():
    data = _yaml("land_acquisition")
    del _dup(data)["claimed_area"]
    with pytest.raises(RulesError, match="claimed_area"):
        parse_scheme(data)
