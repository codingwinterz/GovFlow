"""Rule simulator: change one parameter or input default in memory, rerun the synthetic set, compare.
Read-only: the YAML is never written. Every amount comes from the existing calculator."""

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import AuditLog, Base
from app.rules_loader import RULES_DIR, load_scheme_by_name
from app.simulator import knobs, simulate
from tests.asgi_client import call

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"


def _expected(scheme):
    return {json.loads((f / "case.json").read_text(encoding="utf-8"))["case_id"]:
            json.loads((f / "expected.json").read_text(encoding="utf-8")) for f in sorted((DATA / scheme).glob("case_*"))}


def _row(result, case_id):
    return next(r for r in result.cases if r.case_id == case_id)


def test_knobs_list_parameters_and_input_defaults_with_current_values():
    land = {k.name: k for k in knobs(load_scheme_by_name("land_acquisition"))}
    assert land["multiplier"].kind == "input_default" and land["multiplier"].value == 1.0
    assert land["interest_rate"].kind == "parameter" and land["interest_rate"].value == 0.12
    relief = {k.name: k for k in knobs(load_scheme_by_name("disaster_relief"))}
    assert relief["partial_damage_threshold"].value == 15


@pytest.mark.parametrize("scheme", ["land_acquisition", "disaster_relief"])
def test_before_matches_the_hand_derived_expected_outcomes(scheme):
    name = knobs(load_scheme_by_name(scheme))[0].name
    result = simulate(scheme, name, knobs(load_scheme_by_name(scheme))[0].value)   # no actual change
    for case_id, exp in _expected(scheme).items():
        row = _row(result, case_id)
        assert row.before.overall == exp["eligibility"]["overall"]
        assert row.before.total == (None if exp["compensation"]["total"] is None
                                    else pytest.approx(exp["compensation"]["total"], abs=0.005))
        assert row.after == row.before and not row.changed


def test_multiplier_change_hand_derived_for_la01():
    row = _row(simulate("land_acquisition", "multiplier", 1.5), "LA-01")
    assert row.before.total == pytest.approx(17_200_000) and row.after.total == pytest.approx(25_600_000)
    assert row.after.items["land_value"] == pytest.approx(11_250_000)
    assert row.after.items["solatium"] == pytest.approx(11_450_000)
    assert row.after.items["interest"] == pytest.approx(2_700_000)
    assert row.total_change == pytest.approx(8_400_000) and row.changed


def test_threshold_change_moves_the_boundary_case():
    result = simulate("disaster_relief", "partial_damage_threshold", 10)
    row = _row(result, "DR-06")                                            # 14.9% damage
    assert (row.before.overall, row.before.total) == ("not_eligible", 0)
    assert (row.after.overall, row.after.total) == ("eligible", 13000)        # hut 8000 + 2500 + 2500
    assert result.changed_count >= 1 and result.case_count == 15


def test_simulation_never_writes_the_yaml():
    path = RULES_DIR / "land_acquisition.yaml"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    simulate("land_acquisition", "multiplier", 2.0)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert {k.name: k.value for k in knobs(load_scheme_by_name("land_acquisition"))}["multiplier"] == 1.0


@pytest.mark.parametrize("name, value, match", [("no_such_knob", 1, "no_such_knob"), ("multiplier", float("nan"), "finite")])
def test_bad_requests(name, value, match):
    with pytest.raises(ValueError, match=match):
        simulate("land_acquisition", name, value)


# --- API: officer/admin only, audited, amounts from the API ---------------------------------------

@pytest.fixture
def api(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app = create_app(engine=engine, upload_dir=tmp_path)
    return engine, lambda method, path, body=None, role="officer": call(app, method, path, body,
                                                                         headers={"X-Role": role, "X-User": "U-1"})


@pytest.mark.parametrize("role, status", [("officer", 200), ("admin", 200), ("clerk", 403), ("citizen", 403)])
def test_roles(api, role, status):
    _, request = api
    assert request("POST", "/simulate", {"scheme": "land_acquisition", "name": "multiplier", "value": 1.5}, role)[0] == status
    assert request("GET", "/simulate/land_acquisition", role=role)[0] == status


def test_api_result_and_audit(api):
    engine, request = api
    status, body = request("POST", "/simulate", {"scheme": "land_acquisition", "name": "multiplier", "value": 1.5})
    row = next(r for r in body["cases"] if r["case_id"] == "LA-01")
    assert status == 200 and row["after"]["total"] == pytest.approx(25_600_000) and row["total_change"] == pytest.approx(8_400_000)
    assert body["read_only"] is True and body["original_value"] == 1.0
    with Session(engine) as s:
        (audit,) = s.query(AuditLog).filter_by(action="rule_simulation").all()
    assert audit.actor == "officer:U-1" and json.loads(audit.payload_json)["name"] == "multiplier"


@pytest.mark.parametrize("body, status", [({"scheme": "nope", "name": "multiplier", "value": 1}, 404),
                                          ({"scheme": "land_acquisition", "name": "x", "value": 1}, 400),
                                          ({"scheme": "land_acquisition", "name": "multiplier", "value": "big"}, 422)])
def test_api_errors(api, body, status):
    _, request = api
    assert request("POST", "/simulate", body)[0] == status
