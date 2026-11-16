"""Public citizen status lookup: minimal data, verification code, rate limit, no internal detail."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_code
from app.main import create_app
from app.models import AuditLog, Base
from app.tools import (add_document, amount_field_values, check_eligibility, compute_compensation, record_officer_decision,
                       submit_to_officer, verify_documents)
from tests.asgi_client import call

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
SECRET = "test-secret"
ALLOWED_KEYS = {"case_ref", "scheme", "status", "next_step", "missing", "decision", "amounts"}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for scheme in ("land_acquisition", "disaster_relief"):
            for p in sorted((DATA / scheme).glob("case_*/case.json")):
                seed_case(s, CaseIn.model_validate_json(p.read_text(encoding="utf-8")))
    clock = Clock()
    app = create_app(engine=engine, upload_dir=tmp_path, citizen_secret=SECRET, clock=clock)

    def lookup(ref, code=None, client="1.2.3.4"):
        body = {"case_ref": ref, "code": citizen_code(ref, SECRET) if code is None else code}
        return call(app, "POST", "/public/status", body, client=client)   # the real peer address, not a header
    return engine, lookup, clock


def _decide(engine, case_id, decision, comment=""):
    with Session(engine) as s:
        verify_documents(s, case_id)
        check_eligibility(s, case_id)
        compute_compensation(s, case_id)
        submit_to_officer(s, case_id)
        record_officer_decision(s, case_id, role="officer", officer_id="O-1", decision=decision, comment=comment,
                                confirmed=amount_field_values(s, case_id))


def test_code_is_deterministic_six_digits_and_secret_dependent():
    assert citizen_code("LA-01", "a") == citizen_code("LA-01", "a")
    assert len(citizen_code("LA-01", "a")) == 6 and citizen_code("LA-01", "a").isdigit()
    assert citizen_code("LA-01", "a") != citizen_code("LA-01", "b")
    assert citizen_code("LA-01", "a") != citizen_code("LA-02", "a")


def test_lookup_needs_no_login_and_returns_only_citizen_fields(env):
    _, lookup, _ = env
    status, body = lookup("LA-01")
    assert status == 200 and set(body) == ALLOWED_KEYS
    assert body["status"] == "received" and body["next_step"] == "processing"


def test_unknown_and_mismatched_references_get_the_same_answer(env):
    _, lookup, _ = env
    unknown = lookup("LA-99", code="123456")
    wrong_code = lookup("LA-01", code="000000" if citizen_code("LA-01", SECRET) != "000000" else "111111")
    assert unknown == wrong_code == (404, {"detail": "not_found"})


def test_reference_alone_never_returns_case_details(env):
    _, lookup, _ = env
    other_case_code = citizen_code("LA-02", SECRET)
    assert other_case_code != citizen_code("LA-01", SECRET)
    for code in ["", "   ", other_case_code]:                     # blank, or a valid code for a different case
        assert lookup("LA-01", code=code) == (404, {"detail": "not_found"})
    status, body = lookup("LA-01")                                  # the right pair still works
    assert status == 200 and body["case_ref"] == "LA-01"


def test_reference_without_a_code_field_is_rejected_without_details(env):
    engine, _, _ = env
    app = create_app(engine=engine, citizen_secret=SECRET)
    status, body = call(app, "POST", "/public/status", {"case_ref": "LA-01"}, client="1.2.3.4")
    assert status == 422 and "status" not in body and "amounts" not in json.dumps(body)


def test_lookups_are_rate_limited_per_client(env):
    _, lookup, clock = env
    for i in range(10):                                         # distinct refs: only the client limit applies
        assert lookup(f"XX-{i}", code="123456", client="9.9.9.9")[0] == 404
    assert lookup("LA-01", client="9.9.9.9") == (429, {"detail": "too_many_attempts"})
    assert lookup("LA-01", client="8.8.8.8")[0] == 200          # other clients unaffected
    clock.now += 15 * 60 + 1
    assert lookup("LA-01", client="9.9.9.9")[0] == 200          # window passed


def test_wrong_codes_for_one_case_are_limited_across_clients(env):
    _, lookup, _ = env
    for i in range(5):
        lookup("LA-02", code="999999" if citizen_code("LA-02", SECRET) != "999999" else "888888", client=f"10.0.0.{i}")
    assert lookup("LA-02", client="10.0.0.99") == (429, {"detail": "too_many_attempts"})


def test_internal_detail_never_reaches_the_citizen(env):
    engine, lookup, _ = env
    _decide(engine, "LA-07", "send_back", comment="internal: officer suspects forged mutation record")
    raw = json.dumps(lookup("LA-07")[1])
    for leaked in ("internal", "forged", "flag", "documents_complete", "clause", "O-1", "9999 0000"):
        assert leaked not in raw


def test_missing_documents_are_listed_for_the_citizen(env):
    engine, lookup, _ = env
    _decide(engine, "LA-07", "send_back", comment="please upload")
    body = lookup("LA-07")[1]
    assert body["status"] == "needs_info" and body["next_step"] == "provide_documents"
    assert {"document": "mutation_record", "reason": "missing"} in body["missing"]


def test_expired_document_is_listed_as_expired(env):
    _, lookup, _ = env
    body = lookup("DR-08")[1]
    assert {"document": "identity_proof", "reason": "expired"} in body["missing"]


def test_decision_and_amounts_appear_only_once_approved(env):
    engine, lookup, _ = env
    before = lookup("LA-01")[1]
    assert before["decision"] is None and before["amounts"] is None
    _decide(engine, "LA-01", "approve")
    after = lookup("LA-01")[1]
    assert after["status"] == "approved" and after["decision"]["decision"] == "approve" and after["decision"]["date"]
    items = {i["component"]: i for i in after["amounts"]["items"]}
    assert items["land_value"]["amount"] == pytest.approx(7500000)
    assert items["land_value"]["source"].startswith("area_sqm * market_value_per_sqm * multiplier with")
    assert after["amounts"]["total"] == pytest.approx(17200000)
    assert after["amounts"]["rules_version"] == "0.1.0"


def test_rejection_shows_the_decision_but_no_amounts(env):
    engine, lookup, _ = env
    _decide(engine, "LA-07", "reject", comment="documents incomplete")
    body = lookup("LA-07")[1]
    assert body["status"] == "rejected" and body["decision"]["decision"] == "reject" and body["amounts"] is None


def test_citizen_sources_match_the_officer_view(env):
    engine, lookup, _ = env
    _decide(engine, "DR-01", "approve")
    citizen = {i["component"]: i["source"] for i in lookup("DR-01")[1]["amounts"]["items"]}
    with Session(engine) as s:
        from app.models import CompensationItemRow
        officer = {r.component: r.formula_note for r in s.query(CompensationItemRow).filter_by(case_id="DR-01")}
    assert citizen == officer


def test_successful_lookups_are_audited_without_the_code(env):
    engine, lookup, _ = env
    lookup("LA-01")
    with Session(engine) as s:
        from app.models import AuditLog
        rows = s.query(AuditLog).filter_by(case_id="LA-01", action="citizen_status_viewed").all()
    assert len(rows) == 1 and citizen_code("LA-01", SECRET) not in rows[0].payload_json


def test_a_spoofed_forwarded_for_header_does_not_bypass_the_limit(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app = create_app(engine=engine, upload_dir=tmp_path, citizen_secret=SECRET, clock=Clock())
    for i in range(10):
        call(app, "POST", "/public/status", {"case_ref": "X", "code": "1"}, headers={"X-Forwarded-For": f"5.5.5.{i}"},
             client="7.7.7.7")
    status, _ = call(app, "POST", "/public/status", {"case_ref": "X", "code": "1"},
                     headers={"X-Forwarded-For": "6.6.6.6"}, client="7.7.7.7")
    assert status == 429


def _decision_at(engine, case_id, ts):
    """Append one more officer_decision row at a chosen instant (the audit log is append-only; the latest row wins)."""
    with Session(engine) as s:
        s.add(AuditLog(case_id=case_id, actor="officer:O-1", action="officer_decision", ts=ts,
                       payload_json=json.dumps({"decision": "approve"})))
        s.commit()


def test_decision_date_is_the_date_in_india_not_utc(env):
    engine, lookup, _ = env
    _decide(engine, "LA-01", "approve")
    _decision_at(engine, "LA-01", datetime(2026, 11, 19, 19, 0, tzinfo=timezone.utc))   # 00:30 IST on 20 Nov
    assert lookup("LA-01")[1]["decision"]["date"] == "2026-11-20"
