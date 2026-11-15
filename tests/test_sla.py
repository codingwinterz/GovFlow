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
from app.tools import check_eligibility, compute_compensation, record_officer_decision, submit_to_officer, verify_documents
from tests.asgi_client import call

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
NOW = datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)
OFFICER = {"X-Role": "officer", "X-User": "O-1"}


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
        verify_documents(s, "LA-01"); check_eligibility(s, "LA-01"); compute_compensation(s, "LA-01")
        submit_to_officer(s, "LA-01")
        record_officer_decision(s, "LA-01", role="officer", officer_id="O-1", decision="approve")
    row = _queue(get)["LA-01"]
    assert row["overdue"] is False and row["status"] == "approved"
    assert row["days_open"] < 100          # counted to the decision (made "now" in real time), not to NOW


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
    get("/cases")
    get("/analytics")
    with Session(engine) as s:
        after = ({c.id: c.status for c in s.query(Case)}, s.scalar(select(func.count()).select_from(AuditLog)))
    assert after == before
