"""Revenue mutation (rules/revenue_mutation.yaml): YAML only, no amount, recommends "Ready for notice" or
"Needs review", never decides title. Outcomes for the five synthetic cases are in data/synthetic/revenue_mutation
(checked by test_all_schemes.py); this file covers the boundaries, flags and screens. Values are hand-derived."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent import run_pipeline
from app.analytics import analytics
from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_view
from app.main import create_app
from app.models import Base, Case
from app.rules_engine import check_eligibility
from app.rules_loader import load_scheme_by_name, parse_scheme, scheme_names
from app.self_check import self_check
from app.tools import ToolError, record_officer_decision
from app.verification import verify_documents
from tests.asgi_client import call
from tests.auth_headers import staff

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic" / "revenue_mutation"
RM = load_scheme_by_name("revenue_mutation")
OFFICER = staff("officer", "O-1")
DISPUTE_WORDS = "Refer; this system does not decide title."


def _case(n: int) -> CaseIn:
    return CaseIn.model_validate_json((DATA / f"case_{n:02d}" / "case.json").read_text(encoding="utf-8"))


def _all() -> list[CaseIn]:
    return [_case(n) for n in range(1, 6)]


def _rules(case: CaseIn, scheme=RM, others=None) -> dict[str, str]:
    result = check_eligibility(scheme, case, verify_documents(scheme, case, others or [case]))
    return {r.rule_id: r.status for r in result.results} | {"overall": result.overall}


def _set(case: CaseIn, doc: str, field: str, value, confidence=0.95) -> CaseIn:
    case.documents[doc].fields[field].value = value
    case.documents[doc].fields[field].confidence = confidence
    return case


# --- the scheme file -------------------------------------------------------------------------------------------

def test_no_scheme_name_in_app_code():
    assert "revenue_mutation" in scheme_names()
    offending = [p.name for p in sorted((ROOT / "app").rglob("*.py")) if "revenue_mutation" in p.read_text(encoding="utf-8")
                 or "mutation" in p.read_text(encoding="utf-8").lower().replace("mutation_record", "")]
    assert offending == []


def test_no_amount_and_its_own_recommendation_words():
    assert RM.compensation is None and RM.labels == {"title": "Revenue mutation (Form I and XIV)"}
    assert RM.recommendation_labels == {"eligible": "Ready for notice", "needs_review": "Needs review",
                                        "not_eligible": "Not ready for notice"}


def test_every_timeline_carries_the_design_note_source_label():
    note = (ROOT / "docs" / "FUTURE_MUTATION_SCHEME.md").read_text(encoding="utf-8")
    by_id = {t.id: t for t in RM.timelines}
    expected = {   # id: (source type, days, working days, verify) from docs/FUTURE_MUTATION_SCHEME.md section 1
        "application_to_talathi": ("official_document", None, False, True),
        "form_x_notice": ("official_document", 15, False, True),
        "scrutiny": ("ministerial_statement", 7, True, True),
        "public_notice": ("ministerial_statement", 15, False, True),
        "disposal_no_objections": ("ministerial_statement", 30, False, True),
        "disposal_with_objections": ("ministerial_statement", 90, False, True),
        "objections_decided": ("official_document", None, False, False),
        "co_owner_notice": ("lead_only", None, False, True),
        "civil_title_disputes": ("lead_only", None, False, True),
        "application_window": ("commercial_guide", 90, False, True),
    }
    assert {i: (t.source_type, t.days, t.working_days, t.verify) for i, t in by_id.items()} == expected
    for name in ("Collectorate citizen charter (2016)", "goemkarponn.com", "rule 11(2)", "35551211",
                 "Prime Builders v. Roque Freddie Meninon Exano Pereira", "commercial"):
        assert name in note and any(name in t.source for t in RM.timelines), name


def test_only_the_30_day_disposal_drives_the_clock():
    assert [t.id for t in RM.timelines if t.drives_sla] == ["disposal_no_objections"] and RM.sla_days == 30


# --- co-owner notice: boundaries (hand-derived) ----------------------------------------------------------------

@pytest.mark.parametrize("holders, named, partitioned, expected", [
    (1, 1, "no", "pass"),            # sole owner, named
    (3, 3, "no", "pass"),            # every holder named: equal is enough
    (3, 4, "no", "pass"),            # more names than holders (e.g. a witness counted): still all named
    (3, 2, "no", "needs_review"),    # one holder short: notice required
    (3, 0, "no", "needs_review"),
    (3, 1, "yes", "pass"),           # partitioned holding: no co-owner notice
    (3, 1, "YES", "pass"),           # compared case-insensitively
])
def test_co_owner_notice_boundaries(holders, named, partitioned, expected):
    case = _set(_set(_case(1), "ownership_record", "holder_count", holders), "deed", "holders_named", named)
    case = _set(case, "ownership_record", "partitioned", partitioned)
    assert _rules(case)["co_owner_notice"] == expected


def test_co_owner_notice_is_never_not_eligible_and_says_what_is_required():
    case = _set(_case(1), "ownership_record", "holder_count", 4)
    result = check_eligibility(RM, case, verify_documents(RM, case, [case]))
    rule = next(r for r in result.results if r.rule_id == "co_owner_notice")
    assert rule.status == "needs_review" and result.overall == "needs_review"
    assert "Notice to all co-owners required" in rule.reason


def test_co_owner_notice_with_an_unreadable_count_needs_review():
    case = _set(_case(1), "ownership_record", "holder_count", 1, confidence=0.6)
    assert _rules(case)["co_owner_notice"] == "needs_review"


def test_sabotaged_co_owner_rule_fails_this_test():
    """Without on_false: needs_review the same case would read as not eligible: the YAML option is what keeps it out."""
    data = yaml.safe_load((ROOT / "rules" / "revenue_mutation.yaml").read_text(encoding="utf-8"))
    sabotaged = copy.deepcopy(data)
    next(r for r in sabotaged["eligibility_rules"] if r["id"] == "co_owner_notice").pop("on_false")
    case = _set(_case(1), "ownership_record", "holder_count", 4)
    assert _rules(case, parse_scheme(sabotaged))["overall"] == "not_eligible"
    assert _rules(case)["overall"] == "needs_review"


# --- transferor, survey number, dispute, tenant ----------------------------------------------------------------

def test_transferor_differing_from_the_form_i_owner_fails():
    case = _set(_case(1), "deed", "owner_name", "Someone Else Entirely")
    assert _rules(case)["transferor_is_recorded_owner"] == "fail"


def test_survey_number_differing_on_the_deed_fails():
    case = _set(_case(1), "deed", "survey_number", "210/9")
    assert _rules(case)["land_identified"] == "fail"


def test_a_recorded_dispute_says_refer_and_never_decides_title():
    case = _set(_case(1), "ownership_record", "dispute_entry", "Civil suit 45/2026 pending (synthetic)")
    v = verify_documents(RM, case, [case])
    check = next(c for c in v.checks if c.check_id == "recorded_dispute")
    assert check.status == "needs_review" and DISPUTE_WORDS in check.detail
    flag = next(f for f in v.flags if f.kind == "recorded_dispute")
    assert flag.severity == "high" and DISPUTE_WORDS in flag.detail
    rules = _rules(case)
    assert rules["no_recorded_dispute"] == "needs_review" and rules["overall"] == "needs_review"


@pytest.mark.parametrize("empty", ["", "  ", "-", "Nil", "N.A.", "निरंक"])
def test_an_empty_dispute_column_is_no_dispute(empty):
    case = _set(_case(1), "ownership_record", "dispute_entry", empty)
    assert _rules(case)["no_recorded_dispute"] == "pass"


def test_tenant_entry_needs_review_never_fail():
    assert _rules(_case(3))["rights_recorded_clear"] == "needs_review"


# --- duplicate pending mutation --------------------------------------------------------------------------------

def _db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for case in _all():
            seed_case(s, case)
    return engine


def _verdict(s, case_id, check):
    from app.tools import verify_documents as verify_db
    return next(c.status for c in verify_db(s, case_id).checks if c.check_id == check)


def test_only_open_mutations_compete():
    with Session(_db()) as s:
        assert _verdict(s, "RM-05", "duplicate_mutation") == "needs_review"   # RM-02 is open on 214/2
        s.get(Case, "RM-02").status = "approved"
        s.commit()
        assert _verdict(s, "RM-05", "duplicate_mutation") == "pass"           # a decided mutation does not compete


def test_other_schemes_do_not_compete():
    with Session(_db()) as s:
        la = CaseIn.model_validate_json((ROOT / "data" / "synthetic" / "land_acquisition" / "case_01" / "case.json")
                                        .read_text(encoding="utf-8"))
        seed_case(s, la)
        assert _verdict(s, "RM-01", "duplicate_mutation") == "pass"


# --- pipeline, officer screens, citizen page, analytics ---------------------------------------------------------

def test_pipeline_has_no_compensation_step_and_reaches_the_officer():
    with Session(_db()) as s:
        steps = run_pipeline(s, "RM-01")
        assert [st.tool for st in steps] == ["verify_documents", "check_eligibility", "submit_to_officer"]
        assert all(st.ok for st in steps) and s.get(Case, "RM-01").status == "in_officer_review"


def test_case_page_data(tmp_path):
    engine = _db()
    with Session(engine) as s:
        run_pipeline(s, "RM-01")
    detail = call(create_app(engine=engine, upload_dir=tmp_path / "up"), "GET", "/cases/RM-01", headers=OFFICER)[1]
    assert detail["recommendation"] == "eligible"
    assert detail["recommendation_labels"]["eligible"] == "Ready for notice"
    assert detail["has_compensation"] is False and detail["confirm_fields"] == []
    assert [t["id"] for t in detail["timelines"]][:3] == ["application_to_talathi", "form_x_notice", "scrutiny"]


def test_approval_with_a_dispute_needs_the_officers_resolution():
    engine = _db()
    with Session(engine) as s:
        case = s.get(Case, "RM-01")
        from app.models import Document, ExtractedField
        doc = s.query(Document).filter_by(case_id="RM-01", doc_type="ownership_record").one()
        row = s.query(ExtractedField).filter_by(document_id=doc.id, field="dispute_entry").one()
        row.value = json.dumps("Civil suit 45/2026 pending (synthetic)")
        s.commit()
        run_pipeline(s, "RM-01")
        assert case.status == "in_officer_review"
        with pytest.raises(ToolError, match="Dispute recorded on the record of rights"):
            record_officer_decision(s, "RM-01", role="officer", officer_id="O-1", decision="approve", confirmed={},
                                    today=date(2026, 11, 20))
        view = citizen_view(s, case)
        assert view["notices"] == ["claim_verification"]            # a key only: no detail reaches the public
        assert "45/2026" not in json.dumps(view)


def test_citizen_page_for_an_approved_mutation_has_no_amounts():
    with Session(_db()) as s:
        run_pipeline(s, "RM-01")
        record_officer_decision(s, "RM-01", role="officer", officer_id="O-1", decision="approve", confirmed={},
                                today=date(2026, 11, 20))
        view = citizen_view(s, s.get(Case, "RM-01"))
    assert view["status"] == "approved" and view["amounts"] is None


def test_self_check_names_the_co_owner_notice():
    ok = self_check(RM, {"ownership_record.holder_count": "3", "deed.holders_named": "3",
                         "ownership_record.partitioned": "no"})
    assert ok.outcome == "likely_eligible"
    short = self_check(RM, {"ownership_record.holder_count": "3", "deed.holders_named": "1",
                            "ownership_record.partitioned": "no"})
    assert short.outcome == "need_more_information"
    assert short.rules[0].message.startswith("Notice to all co-owners required")


def test_analytics_counts_mutations_but_lists_no_liability_for_them():
    engine = _db()
    with Session(engine) as s:
        run_pipeline(s, "RM-01")
        a = analytics(s)
    assert sum(a["by_scheme_and_status"]["revenue_mutation"].values()) == 5
    for key in ("committed_by_scheme", "pending_by_scheme", "combined_by_scheme"):
        assert "revenue_mutation" not in a["liability"][key]
        assert {"land_acquisition", "disaster_relief", "social_welfare"} <= set(a["liability"][key])
