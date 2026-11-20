"""(a) Optional per-scheme recommendation labels in the YAML, e.g. eligible shown as "Ready for notice".
The engine's three outcomes do not change; only the words on screen do. Existing schemes set none."""

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import rules_loader
from app.case_model import CaseIn
from app.case_store import seed_case
from app.main import create_app
from app.models import Base
from app.rules_loader import RulesError, load_scheme_by_name, parse_scheme, scheme_names
from tests.asgi_client import call
from tests.auth_headers import staff

RULES = Path(__file__).resolve().parent.parent / "rules"
DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
LAND = yaml.safe_load((RULES / "land_acquisition.yaml").read_text(encoding="utf-8"))
OFFICER = staff("officer", "O-1")


def _with(labels):
    data = copy.deepcopy(LAND)
    data["recommendation_labels"] = labels
    return data


def test_labels_are_optional_and_empty_for_the_existing_schemes():
    for name in ("land_acquisition", "disaster_relief", "social_welfare"):
        assert load_scheme_by_name(name).recommendation_labels == {}


def test_a_scheme_may_relabel_any_of_the_three_outcomes():
    scheme = parse_scheme(_with({"eligible": "Ready for notice", "needs_review": "Needs review"}))
    assert scheme.recommendation_labels == {"eligible": "Ready for notice", "needs_review": "Needs review"}
    assert scheme.recommendation_label("eligible") == "Ready for notice"
    assert scheme.recommendation_label("not_eligible") is None     # falls back to the app-wide label


def test_unknown_outcome_is_rejected():
    with pytest.raises(RulesError, match="unknown outcomes"):
        parse_scheme(_with({"ready": "Ready for notice"}))


@pytest.mark.parametrize("bad", ["", "   ", "ready_for_notice"])
def test_label_must_be_human_wording(bad):
    with pytest.raises(RulesError, match="human wording"):
        parse_scheme(_with({"eligible": bad}))


@pytest.mark.parametrize("bad", ["Approved", "Ready to approve", "Rejected", "Sanctioned", "Reject"])
def test_label_may_not_state_a_decision(bad):
    """Only an officer decides (CLAUDE.md rule 2): a recommendation must never read as a decision."""
    with pytest.raises(RulesError, match="decision"):
        parse_scheme(_with({"eligible": bad}))


# --- API ---------------------------------------------------------------------------------------------------

def _app(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_case(s, CaseIn.model_validate_json((DATA / "case_01" / "case.json").read_text(encoding="utf-8")))
    return create_app(engine=engine, upload_dir=tmp_path / "uploads")


def test_case_detail_sends_an_empty_map_for_a_scheme_without_labels(tmp_path):
    status, detail = call(_app(tmp_path), "GET", "/cases/LA-01", headers=OFFICER)
    assert status == 200 and detail["recommendation_labels"] == {}


def test_case_detail_sends_the_scheme_labels(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    data = _with({"eligible": "Ready for notice"})
    (rules / "land_acquisition.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(rules_loader, "RULES_DIR", rules)
    assert "land_acquisition" in scheme_names()
    status, detail = call(_app(tmp_path), "GET", "/cases/LA-01", headers=OFFICER)
    assert status == 200 and detail["recommendation_labels"] == {"eligible": "Ready for notice"}
