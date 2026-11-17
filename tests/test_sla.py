"""SLA timers: per-scheme days in YAML, days open and an overdue flag. A flag only: nothing changes."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import seed_case
from app.main import create_app
from app.models import AuditLog, Base, Case
from app.rules_loader import RULES_DIR, RulesError, load_scheme_by_name, parse_scheme
from app.tools import amount_field_values, check_eligibility, compute_compensation, record_officer_decision, submit_to_officer, verify_documents
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
NOW = datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)
OFFICER = staff("officer", "O-1", at=NOW)   # minted on the app's fixed clock


def test_each_scheme_declares_sla_days():
    assert load_scheme_by_name("land_acquisition").sla_days > 0
    assert load_scheme_by_name("disaster_relief").sla_days > 0


@pytest.mark.parametrize("bad", [0, -3, 2.5, "thirty"])
def test_sla_days_must_be_a_positive_whole_number(bad):
    data = yaml.safe_load((RULES_DIR / "disaster_relief.yaml").read_text(encoding="utf-8"))
    data["sla_days"] = bad
    with pytest.raises(RulesError, match="sla_days"):
        parse_scheme(data)


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for ref, scheme, days_ago in (("LA-01", "land_acquisition", 100), ("LA-02", "land_acquisition", 5),
                                      ("DR-01", "disaster_relief", 40), ("DR-02", "disaster_relief", 2)):
            folder = DATA / scheme / f"case_{ref[-2:]}"
            seed_case(s, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))
            s.get(Case, ref).created_at = NOW - timedelta(days=days_ago)
        s.commit()
    app = create_app(engine=engine, upload_dir=tmp_path, now=lambda: NOW)
    return engine, lambda path: call(app, "GET", path, headers=OFFICER)


def _queue(get):
    return {c["case_id"]: c for c in get("/cases")[1]}


def test_queue_shows_days_open_and_overdue_from_the_api(env):
    _, get = env
    q = _queue(get)
    la, dr = load_scheme_by_name("land_acquisition").sla_days, load_scheme_by_name("disaster_relief").sla_days
    assert q["LA-01"]["days_open"] == 100 and q["LA-01"]["sla_days"] == la and q["LA-01"]["overdue"] == (100 > la)
    assert q["LA-02"]["days_open"] == 5 and q["LA-02"]["overdue"] is False
    assert q["DR-01"]["overdue"] == (40 > dr) and q["DR-02"]["overdue"] is False


def test_decided_cases_stop_the_clock_and_are_never_overdue(env):
    engine, get = env
    with Session(engine) as s:
        s.get(Case, "LA-01").created_at = datetime.now(timezone.utc) - timedelta(days=200)   # far past the SLA
        s.commit()
        verify_documents(s, "LA-01"); check_eligibility(s, "LA-01"); compute_compensation(s, "LA-01")
        submit_to_officer(s, "LA-01")
        record_officer_decision(s, "LA-01", role="officer", officer_id="O-1", decision="approve",
                                confirmed=amount_field_values(s, "LA-01"))
    row = _queue(get)["LA-01"]
    assert row["status"] == "approved" and row["days_open"] > row["sla_days"]   # it took longer than the SLA...
    assert row["overdue"] is False                                             # ...but a closed case is never overdue
    assert 199 <= row["days_open"] <= 201  # counted to the decision (made in real time), not to NOW


def test_analytics_counts_overdue_by_status_and_scheme(env):
    _, get = env
    a = get("/analytics")[1]
    la, dr = load_scheme_by_name("land_acquisition").sla_days, load_scheme_by_name("disaster_relief").sla_days
    expected = [ref for ref, d, sla in (("LA-01", 100, la), ("LA-02", 5, la), ("DR-01", 40, dr), ("DR-02", 2, dr)) if d > sla]
    assert a["overdue_count"] == len(expected) and sorted(c["case_id"] for c in a["overdue_cases"]) == sorted(expected)
    assert a["overdue_by_status"] == ({"received": len(expected)} if expected else {})
    assert sum(a["overdue_by_scheme"].values()) == len(expected)
    assert "sla_days" in a["overdue_source"]


def test_overdue_is_a_flag_only(env):
    engine, get = env
    with Session(engine) as s:
        before = ({c.id: c.status for c in s.query(Case)}, s.scalar(select(func.count()).select_from(AuditLog)))
    returned = {c["case_id"]: c["status"] for c in get("/cases")[1]}
    get("/analytics")
    assert returned == before[0]                                   # the response does not change statuses either
    with Session(engine) as s:
        after = ({c.id: c.status for c in s.query(Case)}, s.scalar(select(func.count()).select_from(AuditLog)))
    assert after == before


# --- the clock pauses while the case waits for the citizen (needs_info) ------------------------------------------
# Waiting time comes from the audit log: a send-back decision or a deficiency notice starts it; the next document
# added (previous status needs_info) ends it. Rows are inserted at chosen times (the log is append-only).

import json as _json


def _event(s, case_id, action, at, **payload):
    s.add(AuditLog(case_id=case_id, actor="test", action=action, payload_json=_json.dumps(payload), ts=at,
                   rules_version="test"))


def _wait(engine, case_id, created_days_ago, start_days_ago, end_days_ago=None, via="officer_decision"):
    with Session(engine) as s:
        case = s.get(Case, case_id)
        case.created_at = NOW - timedelta(days=created_days_ago)
        start = {"decision": "send_back"} if via == "officer_decision" else {}
        _event(s, case_id, via, NOW - timedelta(days=start_days_ago), **start)
        if end_days_ago is None:
            case.status = "needs_info"
        else:
            _event(s, case_id, "add_document", NOW - timedelta(days=end_days_ago), previous_status="needs_info")
            case.status = "received"
        s.commit()


def test_a_case_that_waited_ten_days_shows_days_open_without_the_wait(env):
    engine, get = env
    _wait(engine, "LA-02", created_days_ago=30, start_days_ago=25, end_days_ago=15)
    assert _queue(get)["LA-02"]["days_open"] == 20                    # 30 days old, 10 of them waiting


def test_days_open_stops_while_waiting_and_resumes_when_documents_arrive(env):
    engine, get = env
    _wait(engine, "LA-02", created_days_ago=30, start_days_ago=12)    # waiting for the last 12 days
    assert _queue(get)["LA-02"]["days_open"] == 18                    # frozen at the 18 days before the wait


def test_a_deficiency_notice_also_pauses_the_clock(env):
    engine, get = env
    _wait(engine, "LA-02", created_days_ago=30, start_days_ago=25, end_days_ago=15, via="deficiency_notice_sent")
    assert _queue(get)["LA-02"]["days_open"] == 20


def test_overdue_does_not_fire_while_waiting_but_does_after_documents_arrive(env):
    engine, get = env
    la = load_scheme_by_name("land_acquisition").sla_days
    _wait(engine, "LA-01", created_days_ago=la + 40, start_days_ago=10)    # past the SLA, now waiting
    row = _queue(get)["LA-01"]
    assert row["days_open"] == la + 30 and row["overdue"] is False
    assert "LA-01" not in {c["case_id"] for c in get("/analytics")[1]["overdue_cases"]}
    with Session(engine) as s:                                             # documents arrive: the clock resumes
        _event(s, "LA-01", "add_document", NOW - timedelta(days=2), previous_status="needs_info")
        s.get(Case, "LA-01").status = "received"
        s.commit()
    row = _queue(get)["LA-01"]
    assert row["days_open"] == la + 32 and row["overdue"] is True          # 8 days of the 10 were waiting


def test_a_document_added_outside_a_wait_does_not_change_days_open(env):
    engine, get = env
    with Session(engine) as s:
        s.get(Case, "LA-02").created_at = NOW - timedelta(days=30)
        _event(s, "LA-02", "add_document", NOW - timedelta(days=5), previous_status="received")
        s.commit()
    assert _queue(get)["LA-02"]["days_open"] == 30


def test_the_real_tools_write_what_the_clock_reads(env, tmp_path):
    from app.sla import waiting_times
    from app.tools import add_document
    engine, _ = env
    path = tmp_path / "id.txt"
    path.write_text("Name: Prakash Kamat (synthetic)", encoding="utf-8")
    with Session(engine) as s:
        verify_documents(s, "LA-02"); check_eligibility(s, "LA-02"); compute_compensation(s, "LA-02")
        submit_to_officer(s, "LA-02")
        record_officer_decision(s, "LA-02", role="officer", officer_id="O-1", decision="send_back", comment="ID copy")
        open_wait = waiting_times(s, datetime.now(timezone.utc) + timedelta(days=3))["LA-02"]
        assert timedelta(days=3) <= open_wait < timedelta(days=3, minutes=5)    # still waiting: runs to "now"
        add_document(s, "LA-02", "identity_proof", str(path))
        closed = waiting_times(s, datetime.now(timezone.utc) + timedelta(days=3))["LA-02"]
        assert closed < timedelta(minutes=5)                                     # ended when the document arrived
