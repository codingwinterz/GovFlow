from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.models import AuditLog, Case, RuleResultRow, iso_utc, make_engine, make_session


@pytest.fixture
def session():
    engine = make_engine("sqlite://")   # in-memory
    with make_session(engine) as s:
        yield s


def test_case_defaults_to_received(session):
    session.add(Case(id="LA-01", scheme="land_acquisition", applicant_ref="APP-1"))
    session.commit()
    assert session.get(Case, "LA-01").status == "received"


def test_rule_result_stores_status_and_rules_version(session):
    session.add(Case(id="LA-01", scheme="land_acquisition", applicant_ref="APP-1"))
    session.add(RuleResultRow(case_id="LA-01", rule_id="valid_ownership", status="needs_review",
                              reason="r", clause="c", rules_version="0.1.0"))
    session.commit()
    assert session.query(RuleResultRow).one().status == "needs_review"


def _audit(session):
    session.add(AuditLog(case_id="LA-01", actor="agent", action="check_eligibility",
                         payload_json="{}", rules_version="0.1.0"))
    session.commit()


def test_audit_log_accepts_inserts(session):
    _audit(session)
    assert session.query(AuditLog).count() == 1


def test_audit_log_rejects_update(session):
    _audit(session)
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE audit_log SET actor = 'someone'"))


def test_audit_log_rejects_delete(session):
    _audit(session)
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("DELETE FROM audit_log"))


def test_iso_utc_always_ends_in_z():
    assert iso_utc(datetime(2026, 11, 16, 6, 51, 0)) == "2026-11-16T06:51:00Z"                 # naive from SQLite = UTC
    ist = timezone(timedelta(hours=5, minutes=30))
    assert iso_utc(datetime(2026, 11, 16, 12, 21, 0, tzinfo=ist)) == "2026-11-16T06:51:00Z"    # converted, not relabelled
    assert iso_utc(datetime(2026, 11, 16, 6, 51, 0, 5, tzinfo=timezone.utc)) == "2026-11-16T06:51:00.000005Z"
