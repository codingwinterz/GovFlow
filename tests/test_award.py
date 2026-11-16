"""Award letter / case summary: officer only, approved cases only, every value from stored results."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import seed_case
from app.main import create_app
from app.models import AuditLog, Base, CompensationItemRow, RuleResultRow
from app.tools import (check_eligibility, compute_compensation, record_officer_decision, submit_to_officer,
                       verify_documents)
from tests.asgi_client import call

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for scheme in ("land_acquisition", "disaster_relief"):
            for p in sorted((DATA / scheme).glob("case_*/case.json")):
                seed_case(s, CaseIn.model_validate_json(p.read_text(encoding="utf-8")))
    app = create_app(engine=engine, upload_dir=tmp_path)
    return engine, lambda path, role="officer": call(app, "GET", path, headers={"X-Role": role, "X-User": "O-7"})


def _to_review(engine, case_id):
    with Session(engine) as s:
        verify_documents(s, case_id); check_eligibility(s, case_id); compute_compensation(s, case_id)
        submit_to_officer(s, case_id)


def _decide(engine, case_id, decision, comment="ok"):
    _to_review(engine, case_id)
    with Session(engine) as s:
        record_officer_decision(s, case_id, role="officer", officer_id="O-7", decision=decision, comment=comment)


def test_award_for_an_approved_case(env):
    engine, get = env
    _decide(engine, "LA-01", "approve")
    status, a = get("/cases/LA-01/award")
    assert status == 200 and a["case_id"] == "LA-01" and a["demo"] is True
    assert a["decision"]["officer_id"] == "O-7" and a["decision"]["date"] and a["rules_version"] == "0.1.0"
    assert a["labels"]["amounts"] == "Compensation" and a["applicant_name"] == "Asha Naik"
    with Session(engine) as s:
        stored = {r.component: (r.amount, r.formula_note) for r in s.query(CompensationItemRow).filter_by(case_id="LA-01")}
        rules = {r.rule_id: (r.status, r.clause) for r in s.query(RuleResultRow).filter_by(case_id="LA-01")}
    assert {i["component"]: (i["amount"], i["formula_note"]) for i in a["items"]} == stored
    assert a["total"] == pytest.approx(17_200_000)
    assert {r["rule_id"]: (r["status"], r["clause"]) for r in a["rule_results"]} == rules


def test_identifiers_are_masked(env):
    # DR cases hold raw synthetic ids; the land set stores ids pre-masked, so it cannot test masking
    engine, get = env
    _decide(engine, "DR-01", "approve")
    a = get("/cases/DR-01/award")[1]
    with Session(engine) as s:
        from app.case_store import load_case
        raw = load_case(s, "DR-01").documents["identity_proof"].fields["id_number"].value
    assert raw == "9999 2000 0001"                                  # the test really has a raw id to leak
    assert a["applicant_id"] == "XXXX XXXX 0001" and raw not in json.dumps(a)


@pytest.mark.parametrize("decision", [None, "reject", "send_back"])
def test_only_approved_cases_get_an_award(env, decision):
    engine, get = env
    if decision is None:
        _to_review(engine, "LA-02")
    else:
        _decide(engine, "LA-02", decision, comment="reason")
    status, body = get("/cases/LA-02/award")
    assert status == 409 and "approved" in body["detail"]


@pytest.mark.parametrize("role", ["clerk", "citizen", "admin"])
def test_officer_only(env, role):
    engine, get = env
    _decide(engine, "LA-01", "approve")
    assert get("/cases/LA-01/award", role=role)[0] == 403


def test_award_view_is_audited(env):
    engine, get = env
    _decide(engine, "DR-01", "approve")
    a = get("/cases/DR-01/award")[1]
    assert a["labels"]["amounts"] == "Relief" and a["total"] == pytest.approx(125000)   # full house, plain 120000 + 2500 + 2500
    with Session(engine) as s:
        (row,) = s.query(AuditLog).filter_by(case_id="DR-01", action="award_letter_viewed").all()
    assert row.actor == "officer:O-7"


def test_unknown_case_is_404(env):
    _, get = env
    assert get("/cases/LA-99/award")[0] == 404
