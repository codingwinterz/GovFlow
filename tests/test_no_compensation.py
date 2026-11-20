"""(c) A scheme with no compensation section calculates no amount: the pipeline skips the compensation step without
an error, the agent is not offered the tool (and gets a plain "not applicable" answer if it calls it anyway), the
officer side hides the amounts, summary total and award letter, and the citizen page has no "Why this amount".
Schemes with compensation are unchanged (see also test_regression_snapshots.py).

The scheme used here is land acquisition with its compensation section removed, written to a temporary rules
folder: no scheme name is added to app/."""

import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import rules_loader
from app.agent import AGENT_TOOL_NAMES, AgentReply, ToolCall, run_agent, run_pipeline
from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_view
from app.main import create_app
from app.models import AuditLog, Base, Case
from app.providers.fake import ScriptedAgentLLM
from app.rules_loader import RulesError, known_terms, load_scheme_by_name, parse_scheme
from app.tools import amount_field_values, record_officer_decision
from tests.asgi_client import call
from tests.auth_headers import staff

ROOT = Path(__file__).resolve().parent.parent
LAND = yaml.safe_load((ROOT / "rules" / "land_acquisition.yaml").read_text(encoding="utf-8"))
NAME = "land_no_amount"
OFFICER = staff("officer", "O-1")


def _no_amount_yaml() -> dict:
    data = copy.deepcopy(LAND)
    data.pop("compensation")
    data["scheme"] = NAME
    data["labels"] = {"title": "Land record (no amount)"}
    known = known_terms(parse_scheme({**data, "terms": {}}))
    data["terms"] = {k: v for k, v in data["terms"].items() if k in known}
    return data


@pytest.fixture(autouse=True)
def rules_dir(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", rules)
    (rules / f"{NAME}.yaml").write_text(yaml.safe_dump(_no_amount_yaml(), sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(rules_loader, "RULES_DIR", rules)
    return rules


def _case(case_id="NA-01", folder="case_01") -> CaseIn:
    case = CaseIn.model_validate_json((ROOT / "data" / "synthetic" / "land_acquisition" / folder / "case.json")
                                      .read_text(encoding="utf-8"))
    return case.model_copy(update={"case_id": case_id, "scheme": NAME})


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_case(s, _case())
        seed_case(s, CaseIn.model_validate_json((ROOT / "data" / "synthetic" / "land_acquisition" / "case_01" /
                                                 "case.json").read_text(encoding="utf-8")))
    return engine


def _actions(session, case_id="NA-01"):
    return [(a.action, json.loads(a.payload_json)) for a in session.query(AuditLog).filter_by(case_id=case_id)
            .order_by(AuditLog.id)]


# --- the scheme file ------------------------------------------------------------------------------------------

def test_a_scheme_without_compensation_needs_only_a_title_label():
    scheme = load_scheme_by_name(NAME)
    assert scheme.compensation is None and scheme.labels == {"title": "Land record (no amount)"}


def test_a_scheme_with_compensation_still_needs_the_amount_labels():
    data = copy.deepcopy(LAND)
    data["labels"] = {"title": "Land acquisition"}
    with pytest.raises(RulesError, match="labels missing"):
        parse_scheme(data)


def test_amount_labels_on_a_scheme_without_compensation_are_refused():
    data = _no_amount_yaml()
    data["labels"]["total"] = "Total"
    with pytest.raises(RulesError, match="no compensation"):
        parse_scheme(data)


# --- pipeline and agent ---------------------------------------------------------------------------------------

def test_pipeline_skips_the_compensation_step_without_an_error(engine):
    with Session(engine) as s:
        steps = run_pipeline(s, "NA-01")
        assert [st.tool for st in steps] == ["verify_documents", "check_eligibility", "submit_to_officer"]
        assert all(st.ok for st in steps)
        assert s.get(Case, "NA-01").status == "in_officer_review"
        actions = _actions(s)
        assert not [p for a, p in actions if a == "agent_tool_call" and not p["ok"]]
        assert "compute_compensation" not in [a for a, _ in actions]


def test_fallback_explanation_has_no_amount_and_no_error(engine):
    from tests.regression_snapshot import _NoLLM
    with Session(engine) as s:
        run = run_agent(s, "NA-01", _NoLLM())
        assert run.final_status == "in_officer_review"
        assert [st.tool for st in run.steps] == ["verify_documents", "check_eligibility", "submit_to_officer"]
        assert "Compensation" not in run.explanation and "Rs " not in run.explanation


def test_agent_is_not_offered_the_compensation_tool_for_such_a_scheme(engine):
    llm = ScriptedAgentLLM([AgentReply(text="done")])
    with Session(engine) as s:
        run_agent(s, "NA-01", llm)
    offered = {t.name for t in llm.calls[0]["tools"]}
    assert offered == set(AGENT_TOOL_NAMES) - {"compute_compensation"}


def test_agent_offered_every_tool_for_a_scheme_with_compensation(engine):
    llm = ScriptedAgentLLM([AgentReply(text="done")])
    with Session(engine) as s:
        run_agent(s, "LA-01", llm)
    assert {t.name for t in llm.calls[0]["tools"]} == set(AGENT_TOOL_NAMES)


def test_agent_calling_the_tool_anyway_gets_not_applicable_not_an_error(engine):
    calls = lambda *n: AgentReply(tool_calls=[ToolCall(id=f"c-{x}", name=x) for x in n])
    llm = ScriptedAgentLLM([calls("verify_documents"), calls("check_eligibility", "compute_compensation"),
                            calls("submit_to_officer"), AgentReply(text="Ready for notice. Officer to decide.")])
    with Session(engine) as s:
        run = run_agent(s, "NA-01", llm)
        comp = next(st for st in run.steps if st.tool == "compute_compensation")
        assert comp.ok and comp.error is None
        answer = llm.calls[2]["messages"][-1].content
        assert "no amount" in answer["not_applicable"].lower()
        assert run.final_status == "in_officer_review"
        assert not [p for a, p in _actions(s) if a == "agent_tool_call" and not p["ok"]]


# --- officer screens and citizen page -------------------------------------------------------------------------

def _approved(engine):
    with Session(engine) as s:
        run_pipeline(s, "NA-01")
        assert amount_field_values(s, "NA-01") == {}
        record_officer_decision(s, "NA-01", role="officer", officer_id="O-1", decision="approve", confirmed={},
                                today=date(2026, 11, 20))


def test_case_detail_says_the_scheme_has_no_amount(engine, tmp_path):
    app = create_app(engine=engine, upload_dir=tmp_path / "up")
    with Session(engine) as s:
        run_pipeline(s, "NA-01")
        run_pipeline(s, "LA-01")
    no_amount = call(app, "GET", "/cases/NA-01", headers=OFFICER)[1]
    land = call(app, "GET", "/cases/LA-01", headers=OFFICER)[1]
    assert no_amount["has_compensation"] is False and no_amount["confirm_fields"] == []
    assert no_amount["compensation"] == {"items": [], "total": None}
    assert land["has_compensation"] is True


def test_there_is_no_award_letter_for_such_a_scheme(engine, tmp_path):
    _approved(engine)
    app = create_app(engine=engine, upload_dir=tmp_path / "up")
    status, body = call(app, "GET", "/cases/NA-01/award", headers=OFFICER)
    assert status == 409 and "no amount" in body["detail"].lower()


def test_citizen_page_has_no_amounts_for_such_a_scheme(engine):
    _approved(engine)
    with Session(engine) as s:
        view = citizen_view(s, s.get(Case, "NA-01"))
    assert view["status"] == "approved" and view["amounts"] is None and view["decision"]["decision"] == "approve"
