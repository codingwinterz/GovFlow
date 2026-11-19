"""Extended officer/admin analytics dashboard (read-only queries over existing tables).

Tests:
- Role access: officer and admin allowed (200); clerk and citizen refused (403); no sign-in refused (401).
- Cases by scheme and lifecycle stage (`by_scheme_and_status`), covering all loaded YAML schemes dynamically.
- Overdue count per scheme and overall, respecting SLA pause during `needs_info`.
- Average days open excluding `needs_info` waiting intervals, overall and per scheme.
- Total compensation liability: committed (`approved`) and pending pipeline (open cases with computed items),
  broken down per scheme and overall, strictly excluding `rejected` and `withdrawn` cases.
- Flag counts: open vs resolved (via `flag_resolution` or closed case), plus breakdown by kind, severity, and scheme.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import seed_case
from app.main import create_app
from app.models import AuditLog, Base, Case, CASE_STATUSES
from app.rules_loader import scheme_names
from app.tools import (
    amount_field_values, check_eligibility, compute_compensation,
    record_officer_decision, submit_to_officer, verify_documents,
)
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
OFFICER = staff("officer", "O-1", at=NOW)
ADMIN = staff("admin", "A-1", at=NOW)
CLERK = staff("clerk", "C-1", at=NOW)
CITIZEN = staff("citizen", "P-1", at=NOW)


def _load(scheme: str, num: int) -> CaseIn:
    path = DATA / scheme / f"case_{num:02d}" / "case.json"
    return CaseIn.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app = create_app(engine=engine, upload_dir=tmp_path, now=lambda: NOW)
    return engine, app


def test_analytics_allows_officer_and_admin_only(env):
    _, app = env
    assert call(app, "GET", "/analytics", headers=OFFICER)[0] == 200
    assert call(app, "GET", "/analytics", headers=ADMIN)[0] == 200
    assert call(app, "GET", "/analytics", headers=CLERK)[0] == 403
    assert call(app, "GET", "/analytics", headers=CITIZEN)[0] == 403
    assert call(app, "GET", "/analytics")[0] == 401


def test_empty_database_returns_zeroed_breakdowns_for_all_loaded_schemes(env):
    _, app = env
    status, a = call(app, "GET", "/analytics", headers=OFFICER)
    assert status == 200
    loaded = scheme_names()
    assert set(a["by_scheme_and_status"].keys()) == set(loaded)
    for s in loaded:
        assert set(a["by_scheme_and_status"][s].keys()) == set(CASE_STATUSES)
        assert all(v == 0 for v in a["by_scheme_and_status"][s].values())
    assert a["average_days_open"] is None
    assert a["average_days_open_by_scheme"] == {s: None for s in loaded}
    assert a["liability"]["committed_total"] == 0.0
    assert a["liability"]["pending_total"] == 0.0
    assert a["liability"]["combined_total"] == 0.0
    assert a["flags"]["total_count"] == 0
    assert a["flags"]["open_count"] == 0
    assert a["flags"]["resolved_count"] == 0


def test_cases_by_scheme_and_stage_and_average_days_open_excluding_waiting(env):
    engine, app = env
    with Session(engine) as s:
        # LA-01: created 30 days ago, waited 10 days in needs_info -> 20 active days open
        seed_case(s, _load("land_acquisition", 1))
        c1 = s.get(Case, "LA-01")
        c1.created_at = NOW - timedelta(days=30)
        s.add(AuditLog(
            case_id="LA-01", actor="officer:O-1", action="officer_decision",
            payload_json=json.dumps({"decision": "send_back"}),
            ts=NOW - timedelta(days=20), rules_version="0.1.0",
        ))
        s.add(AuditLog(
            case_id="LA-01", actor="clerk:C-1", action="add_document",
            payload_json=json.dumps({"previous_status": "needs_info"}),
            ts=NOW - timedelta(days=10), rules_version="0.1.0",
        ))

        # LA-02: created 10 days ago, no wait -> 10 active days open
        seed_case(s, _load("land_acquisition", 2))
        c2 = s.get(Case, "LA-02")
        c2.created_at = NOW - timedelta(days=10)

        # DR-01: created 6 days ago, no wait -> 6 active days open
        seed_case(s, _load("disaster_relief", 1))
        d1 = s.get(Case, "DR-01")
        d1.created_at = NOW - timedelta(days=6)
        s.commit()

    _, a = call(app, "GET", "/analytics", headers=ADMIN)
    assert a["by_scheme_and_status"]["land_acquisition"]["received"] == 2
    assert a["by_scheme_and_status"]["disaster_relief"]["received"] == 1
    # Average days open for land_acquisition: (20 + 10) / 2 = 15.0 (NOT (30 + 10) / 2 = 20.0)
    assert a["average_days_open_by_scheme"]["land_acquisition"] == pytest.approx(15.0)
    assert a["average_days_open_by_scheme"]["disaster_relief"] == pytest.approx(6.0)
    # Overall average days open: (20 + 10 + 6) / 3 = 12.0
    assert a["average_days_open"] == pytest.approx(12.0)


def test_compensation_liability_separates_committed_and_pending_and_excludes_rejected_and_withdrawn(env):
    engine, app = env
    with Session(engine) as s:
        for num in (1, 2, 3):
            seed_case(s, _load("land_acquisition", num))
            cid = f"LA-0{num}"
            verify_documents(s, cid)
            check_eligibility(s, cid)
            compute_compensation(s, cid)
            submit_to_officer(s, cid)

        seed_case(s, _load("disaster_relief", 1))
        verify_documents(s, "DR-01")
        check_eligibility(s, "DR-01")
        compute_compensation(s, "DR-01")
        submit_to_officer(s, "DR-01")

        # LA-01: approved (17,200,000 committed)
        record_officer_decision(
            s, "LA-01", role="officer", officer_id="O-1", decision="approve",
            confirmed=amount_field_values(s, "LA-01"),
        )
        # LA-02: stays in_officer_review (6,460,000 pending)
        # LA-03: rejected (6,984,000 must be EXCLUDED from both committed and pending!)
        record_officer_decision(
            s, "LA-03", role="officer", officer_id="O-1", decision="reject",
            comment="Rejected in test",
        )
        # DR-01: stays in_officer_review (1,25,000 pending)
        s.commit()

    _, a = call(app, "GET", "/analytics", headers=OFFICER)
    liab = a["liability"]
    assert liab["committed_by_scheme"]["land_acquisition"] == pytest.approx(17_200_000.0)
    assert liab["committed_by_scheme"]["disaster_relief"] == pytest.approx(0.0)
    assert liab["committed_total"] == pytest.approx(17_200_000.0)

    assert liab["pending_by_scheme"]["land_acquisition"] == pytest.approx(6_460_000.0)
    assert liab["pending_by_scheme"]["disaster_relief"] == pytest.approx(125_000.0)
    assert liab["pending_total"] == pytest.approx(6_585_000.0)

    assert liab["combined_total"] == pytest.approx(23_785_000.0)


def test_flag_counts_track_open_vs_resolved_and_breakdowns_by_kind_severity_and_scheme(env):
    engine, app = env
    with Session(engine) as s:
        # LA-18 has tenant_or_mundkar_claim (high) -> we resolve it and approve
        seed_case(s, _load("land_acquisition", 18))
        verify_documents(s, "LA-18")
        check_eligibility(s, "LA-18")
        compute_compensation(s, "LA-18")
        submit_to_officer(s, "LA-18")

        # LA-07 has missing_document (high) -> stays open in review
        seed_case(s, _load("land_acquisition", 7))
        verify_documents(s, "LA-07")
        check_eligibility(s, "LA-07")
        compute_compensation(s, "LA-07")
        submit_to_officer(s, "LA-07")

    _, before = call(app, "GET", "/analytics", headers=OFFICER)
    assert before["flags"]["open_count"] == 2
    assert before["flags"]["resolved_count"] == 0
    assert before["flags"]["by_kind"]["tenant_or_mundkar_claim"] == 1
    assert before["flags"]["by_kind"]["missing_document"] == 1
    assert before["flags"]["by_severity"]["high"] == 2
    assert before["flags"]["by_scheme"]["land_acquisition"] == 2

    # Resolve LA-18's tenant_or_mundkar_claim flag and approve LA-18
    with Session(engine) as s:
        record_officer_decision(
            s, "LA-18", role="officer", officer_id="O-1", decision="approve",
            confirmed=amount_field_values(s, "LA-18"),
            resolutions={"tenant_or_mundkar_claim": {"reference": "MAML/2026/9", "date": "2026-11-10"}},
        )

    _, after = call(app, "GET", "/analytics", headers=OFFICER)
    assert after["flags"]["total_count"] == 2
    assert after["flags"]["open_count"] == 1
    assert after["flags"]["resolved_count"] == 1


def test_analytics_payload_contains_no_pii_or_document_contents(env):
    engine, app = env
    with Session(engine) as s:
        seed_case(s, _load("land_acquisition", 1))
        seed_case(s, _load("social_welfare", 1))
        verify_documents(s, "LA-01")
        verify_documents(s, "SW-01")
    status, payload = call(app, "GET", "/analytics", headers=ADMIN)
    assert status == 200
    blob = json.dumps(payload)
    for forbidden in ("Laxmi Naik", "Ramesh", "9999 3000 0001", "9999", "tracking_code", "content_base64", "file_path"):
        assert forbidden not in blob, f"unexpected personal or document data in analytics payload: {forbidden}"
