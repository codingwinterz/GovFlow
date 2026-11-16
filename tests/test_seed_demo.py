"""The demo seed script builds a realistic, fully synthetic database without any network call."""

import json

import pytest
from sqlalchemy.orm import Session

from app.models import AuditLog, Case, Document, ExtractedField, make_engine
from scripts.seed_demo import seed


@pytest.fixture
def seeded(tmp_path):
    db = tmp_path / "demo.db"
    summary = seed(db)
    engine = make_engine(f"sqlite:///{db}")
    with Session(engine) as s:
        yield summary, s
    engine.dispose()


def test_seed_covers_the_dashboard_states(seeded):
    summary, s = seeded
    statuses = {c.id: c.status for c in s.query(Case)}
    assert len(statuses) == 30 and {c.scheme for c in s.query(Case)} == {"land_acquisition", "disaster_relief"}
    assert {"in_officer_review", "received", "approved", "needs_info"} <= set(statuses.values())
    assert summary["cases"] == 30 and summary["by_status"] == {
        k: list(statuses.values()).count(k) for k in set(statuses.values())}


def test_days_open_counts_from_the_submitted_date_for_every_open_submitted_case(seeded):
    """The queue's "Submitted" and "Days open" columns must agree: days open = now - submitted date."""
    from datetime import datetime, timezone
    from app.models import as_utc
    from app.sla import sla_view
    _, s = seeded
    now = datetime.now(timezone.utc)
    open_submitted = [c for c in s.query(Case) if c.submitted_at and c.status not in ("approved", "rejected", "withdrawn")]
    assert len(open_submitted) >= 10
    for c in open_submitted:
        assert sla_view(c, now, {})["days_open"] == (now - as_utc(c.submitted_at)).days, c.id
    assert len({as_utc(c.submitted_at).date() for c in open_submitted}) > 5      # spread, not all today


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
    assert seed(db, reset=True)["cases"] == 30


def test_reset_only_deletes_database_files(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError, match=".db"):
        seed(target, reset=True)
    assert target.read_text(encoding="utf-8") == "keep me"


def test_seed_lists_demo_citizen_codes_that_work(seeded):
    from app.citizen import DEMO_SECRET, citizen_code
    summary, _ = seeded
    codes = summary["citizen_codes"]
    assert {"LA-01", "LA-05", "LA-07", "DR-01"} <= set(codes)
    assert all(code == citizen_code(ref, DEMO_SECRET) for ref, code in codes.items())


def test_seed_spreads_intake_dates_so_some_cases_are_overdue(seeded):
    from datetime import datetime, timezone
    from app.analytics import analytics
    _, s = seeded
    result = analytics(s, now=datetime.now(timezone.utc))
    assert result["overdue_count"] >= 2
    assert set(result["overdue_by_scheme"]) == {"land_acquisition", "disaster_relief"}
    ages = {c.id: (datetime.now(timezone.utc) - c.created_at.replace(tzinfo=timezone.utc)).days for c in s.query(Case)}
    assert max(ages.values()) <= 90 and len(set(ages.values())) > 5
