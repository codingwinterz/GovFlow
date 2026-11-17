"""Tenant / mundkar / other-rights entry on the record of rights (Form I & XIV), land acquisition.

The model copies the two columns as printed; the YAML's recorded_entry check decides. An entry -> a high-severity
flag tenant_or_mundkar_claim, valid_ownership needs review (no single-owner recommendation), the total is
labelled as the holding's, approval needs the officer's resolution (reference + date, audit-logged), and the
citizen page shows only a plain notice key. Blank, dash, Nil, NA, none and Devanagari forms are empty."""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_view
from app.main import create_app
from app.models import AuditLog, Base, Case, make_engine
from app.rules_loader import load_scheme_by_name
from app.tools import (ToolError, amount_field_values, check_eligibility, compute_compensation,
                       record_officer_decision, submit_to_officer, verify_documents)
from app.verification import entry_is_empty, verify_documents as verify_pure
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
LA = load_scheme_by_name("land_acquisition")
CHECK = next(c for c in LA.verification_checks if c.id == "tenant_or_mundkar_claim")
TODAY = date(2026, 11, 17)
GOOD = {"tenant_or_mundkar_claim": {"reference": "Tenancy file TNC/123 (synthetic)", "date": "2026-11-10"}}


def _case(n):
    return CaseIn.model_validate_json((DATA / f"case_{n:02d}" / "case.json").read_text(encoding="utf-8"))


def _with(tenant, other, confidence=0.95):
    case = _case(20)
    fields = case.documents["ownership_record"].fields
    fields["tenant_entry"].value, fields["tenant_entry"].confidence = tenant, confidence
    fields["other_rights_entry"].value = other
    return case


def _check(case):
    result = verify_pure(LA, case)
    return next(c for c in result.checks if c.check_id == CHECK.id), result.flags


# --- empty normalisation ------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["", "   ", " \t ", "-", "—", "–", "Nil", "NIL.", "nil", "NA", "N.A.", "n/a",
                                   "None", "- nil -", "निल", "शून्य", "निरंक", "नाही", "नहीं", "काही नाही", "कोई नहीं"])
def test_empty_forms_count_as_nothing_recorded(value):
    assert entry_is_empty(value, CHECK.empty_values)


@pytest.mark.parametrize("value", ["Ramesh Gawde", "Mundkar: Joaquim D'Costa", "Tenant", "Nilesh Naik", "Nana Kamat",
                                   "रमेश गावडे"])
def test_a_named_entry_is_not_empty(value):
    assert not entry_is_empty(value, CHECK.empty_values)


# --- the rule -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n, field", [(18, "tenant_entry"), (19, "other_rights_entry")])
def test_a_named_tenant_or_mundkar_raises_a_high_severity_flag(n, field):
    check, flags = _check(_case(n))
    assert check.status == "needs_review" and f"ownership_record.{field}" in check.detail
    (flag,) = [f for f in flags if f.kind == "tenant_or_mundkar_claim"]
    assert flag.severity == "high" and "Agricultural Tenancy Act, 1964" in flag.detail and "Mundkars" in flag.detail


@pytest.mark.parametrize("n", [20, 21])
def test_nil_dash_and_whitespace_do_not_flag_and_are_not_invalid_values(n):
    check, flags = _check(_case(n))
    assert check.status == "pass"
    assert not [f for f in flags if f.kind in ("tenant_or_mundkar_claim", "invalid_value", "low_confidence")]


def test_an_entry_read_at_or_below_the_threshold_goes_to_review_not_pass():
    check, _ = _check(_with("Nil", "Nil", confidence=0.85))
    assert check.status == "needs_review" and "could not be read reliably" in check.detail


def test_an_entry_the_reader_did_not_return_is_not_checked():
    case = _case(20)
    del case.documents["ownership_record"].fields["tenant_entry"]
    del case.documents["ownership_record"].fields["other_rights_entry"]
    assert _check(case)[0].status == "pass"          # documented limitation: looks the same as a blank column


def test_the_rule_is_declared_in_the_yaml_with_its_basis_and_options():
    assert CHECK.builtin == "recorded_entry" and CHECK.severity == "high" and CHECK.approval_needs_resolution
    assert CHECK.basis == ("The Goa, Daman and Diu Agricultural Tenancy Act, 1964; "
                           "The Goa, Daman and Diu Mundkars (Protection from Eviction) Act, 1975")
    assert LA.terms["tenant_or_mundkar_claim"] == "Tenant or mundkar entry on the record of rights"
    assert "tenant_or_mundkar_claim" in next(r for r in LA.eligibility_rules if r.id == "valid_ownership").depends_on


# --- approval block, label, citizen notice (database) --------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for n in (18, 20):
            seed_case(s, _case(n))
            s.commit()
            case_id = f"LA-{n}"
            for step in (verify_documents, check_eligibility, compute_compensation, submit_to_officer):
                step(s, case_id)
    return engine


def _approve(s, case_id, resolutions=None):
    return record_officer_decision(s, case_id, role="officer", officer_id="O-1", decision="approve",
                                   confirmed=amount_field_values(s, case_id), resolutions=resolutions, today=TODAY)


@pytest.mark.parametrize("resolutions, why", [
    (None, "a reference and a date are required"),
    ({"tenant_or_mundkar_claim": {"reference": "   ", "date": "2026-11-10"}}, "a reference is required"),
    ({"tenant_or_mundkar_claim": {"reference": "TNC/1", "date": "10/11/2026"}}, "YYYY-MM-DD"),
    ({"tenant_or_mundkar_claim": {"reference": "TNC/1", "date": "2026-12-01"}}, "in the future"),
])
def test_approval_is_refused_without_a_valid_resolution(engine, resolutions, why):
    with Session(engine) as s:
        with pytest.raises(ToolError, match=why):
            _approve(s, "LA-18", resolutions)
        assert s.get(Case, "LA-18").status == "in_officer_review"
        assert not s.query(AuditLog).filter_by(case_id="LA-18", action="flag_resolution").count()


def test_approval_with_a_resolution_records_it_in_the_audit_log(engine):
    with Session(engine) as s:
        assert _approve(s, "LA-18", GOOD).status == "approved"
        (row,) = s.query(AuditLog).filter_by(case_id="LA-18", action="flag_resolution").all()
        payload = json.loads(row.payload_json)
        assert payload == {"flag": "tenant_or_mundkar_claim", "reference": "Tenancy file TNC/123 (synthetic)",
                           "date": "2026-11-10", "officer_id": "O-1"}
        decision = s.query(AuditLog).filter_by(case_id="LA-18", action="officer_decision").one()
        assert json.loads(decision.payload_json)["resolutions"] == {
            "tenant_or_mundkar_claim": {"reference": "Tenancy file TNC/123 (synthetic)", "date": "2026-11-10"}}


def test_reject_and_send_back_need_no_resolution(engine):
    with Session(engine) as s:
        result = record_officer_decision(s, "LA-18", role="officer", officer_id="O-1", decision="send_back",
                                         comment="Tenant entry: bring the tenancy papers")
        assert result.status == "needs_info"


def test_a_case_without_an_entry_is_approved_without_a_resolution(engine):
    with Session(engine) as s:
        assert _approve(s, "LA-20").status == "approved"


def test_the_case_page_labels_the_holding_total_and_asks_for_the_resolution(engine, tmp_path):
    app = create_app(engine=engine, upload_dir=tmp_path)
    flagged = call(app, "GET", "/cases/LA-18", headers=staff("officer", "O-1"))[1]
    assert flagged["labels"]["total"] == "Total for the holding, not the owner's share"
    assert flagged["compensation"]["total"] == 4_340_000          # 2,000,000 + 50,000 + 2,050,000 + 240,000
    assert [r["flag"] for r in flagged["resolutions_needed"]] == ["tenant_or_mundkar_claim"]
    assert flagged["recommendation"] == "needs_review"
    clean = call(app, "GET", "/cases/LA-20", headers=staff("officer", "O-1"))[1]
    assert clean["labels"]["total"] == LA.labels["total"] and clean["resolutions_needed"] == []


def test_the_decision_api_refuses_approval_without_the_resolution(engine, tmp_path):
    app = create_app(engine=engine, upload_dir=tmp_path)
    with Session(engine) as s:
        confirmed = amount_field_values(s, "LA-18")
    status, body = call(app, "POST", "/cases/LA-18/decision", headers=staff("officer", "O-1"),
                        body={"decision": "approve", "confirmed_fields": confirmed, "confirmed_case": "LA-18"})
    assert status == 409 and "resolution" in body["detail"]
    status, _ = call(app, "POST", "/cases/LA-18/decision", headers=staff("officer", "O-1"),
                     body={"decision": "approve", "confirmed_fields": confirmed, "resolutions": GOOD,
                           "confirmed_case": "LA-18"})
    assert status == 200


def test_the_citizen_page_shows_only_a_plain_notice_key(engine):
    with Session(engine) as s:
        view = citizen_view(s, s.get(Case, "LA-18"))
        assert view["notices"] == ["rights_verification"]
        text = json.dumps(view)
        assert "Ramesh" not in text and "tenant" not in text.lower() and "Act" not in text
        assert citizen_view(s, s.get(Case, "LA-20"))["notices"] == []


def test_the_notice_and_the_label_go_once_the_resolution_is_recorded(engine, tmp_path):
    with Session(engine) as s:
        _approve(s, "LA-18", GOOD)
        assert citizen_view(s, s.get(Case, "LA-18"))["notices"] == []
    detail = call(create_app(engine=engine, upload_dir=tmp_path), "GET", "/cases/LA-18",
                  headers=staff("officer", "O-1"))[1]
    assert detail["labels"]["total"] == LA.labels["total"]
