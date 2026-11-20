"""(d) Timelines (scrutiny, notice, disposal ...) as source-cited YAML data, shown on the case page. They are data
only: the queue clock is still driven by `sla_days` alone. At most one timeline may say it drives the clock, and
then its days must equal sla_days (calendar days)."""

import copy
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.case_model import CaseIn
from app.case_store import seed_case
from app.main import create_app
from app.models import Base
from app.rules_loader import RulesError, load_scheme_by_name, parse_scheme
from tests.asgi_client import call
from tests.auth_headers import staff

ROOT = Path(__file__).resolve().parent.parent
LAND = yaml.safe_load((ROOT / "rules" / "land_acquisition.yaml").read_text(encoding="utf-8"))
OFFICER = staff("officer", "O-1")
NOTICE = {"id": "public_notice", "label": "Public notice", "period": "15 days", "days": 15,
          "source_type": "ministerial_statement", "source": "Revenue Minister, as reported (press)", "verify": True,
          "verify_note": "against a notification or circular"}


def _with(*timelines, sla_days=None):
    data = copy.deepcopy(LAND)
    data["timelines"] = list(timelines)
    if sla_days is not None:
        data["sla_days"] = sla_days
    return data


def test_existing_schemes_have_no_timelines():
    for name in ("land_acquisition", "disaster_relief", "social_welfare"):
        assert load_scheme_by_name(name).timelines == []


def test_a_sourced_timeline_loads():
    t = parse_scheme(_with(NOTICE)).timelines[0]
    assert (t.id, t.days, t.working_days, t.verify, t.drives_sla) == ("public_notice", 15, False, True, False)


def test_a_period_without_a_day_count_is_allowed():
    """e.g. "Within three months" (rule 11(2)): printed as written, no number invented."""
    t = parse_scheme(_with({**NOTICE, "id": "objections", "period": "Within three months", "days": None,
                            "source_type": "official_document", "verify": False})).timelines[0]
    assert t.days is None and t.period == "Within three months"


@pytest.mark.parametrize("change, match", [
    ({"source": ""}, "source"),
    ({"source_type": "blog"}, "source_type"),
    ({"label": "public_notice"}, "human wording"),
    ({"period": ""}, "period"),
    ({"days": 0}, "days"),
    ({"working_days": True, "days": None}, "working_days"),
])
def test_invalid_timelines_are_refused(change, match):
    with pytest.raises(RulesError, match=match):
        parse_scheme(_with({**NOTICE, **change}))


def test_timeline_ids_are_unique():
    with pytest.raises(RulesError, match="duplicate"):
        parse_scheme(_with(NOTICE, NOTICE))


def test_a_verify_timeline_needs_a_verify_note():
    with pytest.raises(RulesError, match="verify_note"):
        parse_scheme(_with({**NOTICE, "verify_note": ""}))


def test_the_clock_timeline_must_match_sla_days():
    ok = parse_scheme(_with({**NOTICE, "days": 30, "drives_sla": True}, sla_days=30))
    assert ok.sla_days == 30 and ok.timelines[0].drives_sla
    with pytest.raises(RulesError, match="sla_days"):
        parse_scheme(_with({**NOTICE, "days": 15, "drives_sla": True}, sla_days=30))


def test_the_clock_timeline_counts_calendar_days():
    with pytest.raises(RulesError, match="calendar"):
        parse_scheme(_with({**NOTICE, "days": 30, "working_days": True, "drives_sla": True}, sla_days=30))


def test_only_one_timeline_drives_the_clock():
    a = {**NOTICE, "days": 30, "drives_sla": True}
    with pytest.raises(RulesError, match="one timeline"):
        parse_scheme(_with(a, {**a, "id": "other"}, sla_days=30))


def test_case_detail_sends_the_timelines(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_case(s, CaseIn.model_validate_json((ROOT / "data" / "synthetic" / "land_acquisition" / "case_01" /
                                                 "case.json").read_text(encoding="utf-8")))
    app = create_app(engine=engine, upload_dir=tmp_path / "up")
    status, detail = call(app, "GET", "/cases/LA-01", headers=OFFICER)
    assert status == 200 and detail["timelines"] == []
