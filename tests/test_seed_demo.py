"""The demo seed script builds a realistic, fully synthetic database without any network call."""

import json
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import AuditLog, Case, Document, ExtractedField, make_engine
from scripts.seed_demo import seed
from tests.asgi_client import call            # imported at collection: its event loop predates the network guard
from tests.auth_headers import staff


CODE_SECRET = "test-code-secret"

@pytest.fixture
def seeded(tmp_path):
    db = tmp_path / "demo.db"
    summary = seed(db, code_secret=CODE_SECRET)
    engine = make_engine(f"sqlite:///{db}")
    with Session(engine) as s:
        yield summary, s
    engine.dispose()


def test_seed_covers_the_dashboard_states(seeded):
    summary, s = seeded
    statuses = {c.id: c.status for c in s.query(Case)}
    assert len(statuses) == 47 and {c.scheme for c in s.query(Case)} == {"land_acquisition", "disaster_relief", "social_welfare",
                                                                        "revenue_mutation"}
    assert {"in_officer_review", "received", "approved", "needs_info"} <= set(statuses.values())
    assert summary["cases"] == 47 and summary["by_status"] == {
        k: list(statuses.values()).count(k) for k in set(statuses.values())}


def test_days_open_counts_from_the_submitted_date_for_every_open_submitted_case(seeded):
    """The queue's "Submitted" and "Days open" columns must agree: days open = (now - submitted date) minus the time
    spent waiting for the citizen (needs_info), as read from the audit log."""
    from datetime import datetime, timezone
    from app.models import as_utc
    from app.sla import decision_times, sla_view, waiting_times
    _, s = seeded
    now = datetime.now(timezone.utc)
    decided, waited = decision_times(s), waiting_times(s, now)
    open_submitted = [c for c in s.query(Case) if c.submitted_at and c.status not in ("approved", "rejected", "withdrawn")]
    assert len(open_submitted) >= 10
    for c in open_submitted:
        expected = (now - as_utc(c.submitted_at) - waited.get(c.id, timedelta())).days
        assert sla_view(c, now, decided, waited)["days_open"] == expected, c.id
    assert len({as_utc(c.submitted_at).date() for c in open_submitted}) > 5      # spread, not all today


def test_the_demo_queue_pauses_the_sent_back_case(seeded, tmp_path):
    """LA-05 is sent back by the seed (needs_info). Its send-back is audit-logged at the real seed time, so five days
    later its days open must not have moved, while a case that is not waiting has moved on five days."""
    from datetime import datetime, timezone
    from app.main import create_app
    _, s = seeded
    assert s.get(Case, "LA-05").status == "needs_info"
    engine = s.get_bind()
    now = datetime.now(timezone.utc)
    queue_at = lambda at: {c["case_id"]: c for c in call(create_app(engine=engine, upload_dir=tmp_path, now=lambda: at),
                                                          "GET", "/cases", headers=staff("officer", "O-1", at=at))[1]}
    today, later = queue_at(now), queue_at(now + timedelta(days=5))
    assert later["LA-05"]["days_open"] == today["LA-05"]["days_open"]          # paused while waiting
    assert later["LA-05"]["overdue"] is False
    moving = next(cid for cid, c in today.items() if c["status"] == "in_officer_review")
    assert later[moving]["days_open"] == today[moving]["days_open"] + 5         # the clock still runs elsewhere


def test_seed_shows_low_confidence_fields_and_an_unavailable_document(seeded):
    _, s = seeded
    assert s.query(ExtractedField).filter(ExtractedField.confidence < 0.85).count() >= 1
    (doc,) = s.query(Document).filter_by(extraction_status="extraction_unavailable").all()
    assert doc.extraction_error_kind == "rate_limited"


def test_every_seeded_explanation_is_labelled_as_generated_without_the_llm(seeded):
    _, s = seeded
    rows = s.query(AuditLog).filter_by(action="agent_explanation").all()
    assert rows and all("generated without the LLM" in json.loads(r.payload_json)["text"] for r in rows)


def test_seeded_decisions_are_labelled_synthetic(seeded):
    _, s = seeded
    rows = s.query(AuditLog).filter_by(action="officer_decision").all()
    assert rows and all(r.actor == "officer:seed-demo" for r in rows)
    assert all("synthetic" in json.loads(r.payload_json)["comment"] for r in rows)


def test_seed_refuses_to_overwrite_without_reset(tmp_path):
    db = tmp_path / "demo.db"
    seed(db)
    with pytest.raises(FileExistsError):
        seed(db)
    assert seed(db, reset=True)["cases"] == 47


def test_reset_only_deletes_database_files(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError, match=".db"):
        seed(target, reset=True)
    assert target.read_text(encoding="utf-8") == "keep me"


def test_seed_lists_demo_citizen_codes_that_work(seeded):
    from app.citizen import citizen_code
    summary, _ = seeded
    codes = summary["citizen_codes"]
    assert {"LA-01", "LA-05", "LA-07", "DR-01"} <= set(codes)
    assert all(code == citizen_code(ref, CODE_SECRET) for ref, code in codes.items())


@pytest.mark.parametrize("name", ["GOVFLOW_CITIZEN_SECRET", "GOVFLOW_AUTH_SECRET"])
def test_seed_writes_a_random_secret_to_dotenv_once_and_then_reuses_it(tmp_path, monkeypatch, name):
    from scripts.seed_demo import ensure_dotenv_secret
    monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=keep-me", encoding="utf-8")       # no trailing newline
    first, created = ensure_dotenv_secret(dotenv, name)
    assert created and len(first) >= 40
    assert dotenv.read_text(encoding="utf-8") == f"GEMINI_API_KEY=keep-me\n{name}={first}\n"
    assert ensure_dotenv_secret(dotenv, name) == (first, False)          # reused, file unchanged
    assert ensure_dotenv_secret(tmp_path / "other.env", name)[0] != first  # random per machine, not in the source


def test_seed_spreads_intake_dates_so_some_cases_are_overdue(seeded):
    from datetime import datetime, timezone
    from app.analytics import analytics
    _, s = seeded
    result = analytics(s, now=datetime.now(timezone.utc))
    assert result["overdue_count"] >= 2
    assert set(result["overdue_by_scheme"]) == {"land_acquisition", "disaster_relief", "social_welfare"}
    ages = {c.id: (datetime.now(timezone.utc) - c.created_at.replace(tzinfo=timezone.utc)).days for c in s.query(Case)}
    assert max(ages.values()) <= 90 and len(set(ages.values())) > 5
