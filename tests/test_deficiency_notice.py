"""Deficiency notice ("Request documents"): built from the open problems a citizen can fix, with fixed templates
filled from YAML labels. Officer only, only during officer review; sending stores it, audit-logs it and moves the
case to needs_info. It never approves, rejects or computes anything."""

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_view
from app.deficiency import build_items, render, templates
from app.facts import build_facts
from app.main import create_app
from app.models import AuditLog, Base, Case, CompensationItemRow, DeficiencyNotice, RuleResultRow, VerificationFlag
from app.models import make_engine
from app.rules_loader import load_scheme_by_name
from app.tools import (ToolError, add_document, check_eligibility, compute_compensation, preview_notice,
                       send_notice, submit_to_officer, verify_documents)
from app.verification import verify_documents as verify_pure
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
LA, DR = load_scheme_by_name("land_acquisition"), load_scheme_by_name("disaster_relief")


def _case(scheme, n):
    return CaseIn.model_validate_json((DATA / scheme / f"case_{n:02d}" / "case.json").read_text(encoding="utf-8"))


def _items(scheme, case):
    checks = verify_pure(scheme, case).checks
    return [(i.kind, i.document, i.fields) for i in build_items(scheme, checks, build_facts(scheme, case))]


# --- content per flag type (pure) ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, expected", [
    (7, [("missing", "mutation_record", [])]),                                     # mutation record not submitted
    (5, [("expired", "identity_proof", [])]),                                      # identity proof expired
    (11, [("unreadable", "ownership_record", ["name", "area"])]),                  # low-quality scan
    (4, [("name_mismatch", "identity_proof", [])]),                                # name does not match: fail
    (3, [("name_mismatch", "identity_proof", [])]),                                # review band (0.889)
    (1, []),                                                                       # clean case: nothing to ask
])
def test_land_notice_lists_exactly_these_documents(n, expected):
    assert _items(LA, _case("land_acquisition", n)) == expected


def test_a_missing_field_is_asked_for_on_its_document():
    case = _case("land_acquisition", 1)
    del case.documents["survey_sheet"].fields["area"]
    assert _items(LA, case) == [("missing_field", "survey_sheet", ["area"])]


@pytest.mark.parametrize("n, why", [(18, "tenant entry"), (19, "mundkar entry"), (8, "survey number mismatch"),
                                    (12, "overlapping claim")])
def test_problems_with_no_citizen_action_are_left_out(n, why):
    case = _case("land_acquisition", n)
    others = [_case("land_acquisition", 13)] if n == 12 else []
    assert verify_pure(LA, case, others).flags, f"LA-{n} should have an open flag ({why})"
    checks = verify_pure(LA, case, others).checks
    assert build_items(LA, checks, build_facts(LA, case)) == []


def test_an_implausible_value_is_not_asked_for_but_an_unreadable_date_is():
    # LA-17: the area is outside the plausible range (an officer matter); the issue date holds injected text.
    assert _items(LA, _case("land_acquisition", 17)) == [("unreadable", "ownership_record", ["issue_date"])]


def test_relief_name_mismatch_and_expired_document():
    kinds_07 = {(k, d) for k, d, _ in _items(DR, _case("disaster_relief", 7))}
    assert {k for k, _ in kinds_07} == {"name_mismatch"}
    assert ("expired", "identity_proof", []) in _items(DR, _case("disaster_relief", 8))


# --- templates and languages --------------------------------------------------------------------------------

def _notice(n, lang):
    case = _case("land_acquisition", n)
    items = build_items(LA, verify_pure(LA, case).checks, build_facts(LA, case))
    return render(items, lang, LA, case.case_id, "17 Nov 2026")


def test_english_notice_text_is_the_fixed_template_filled_with_labels():
    assert _notice(11, "en") == [
        "Documents needed",
        "To continue with application LA-11, please bring the following to the office:",
        "Ownership record: we could not read Name, Area. Please bring a clearer copy or the original.",
        "This notice only asks for documents. It is not a decision on your application.",
        "Notice issued on 17 Nov 2026",
    ]


@pytest.mark.parametrize("lang", ["hi", "mr", "kok"])
def test_other_languages_use_their_templates_and_say_they_are_drafts(lang):
    lines, t = _notice(7, lang), templates(lang)
    assert lines[0] == t["deficiency.title"] and lines[-1] == t["footer.review"]
    assert lines[2] == t["deficiency.missing"].replace("{document}", t["documents.mutation_record"])
    assert "Mutation record" not in " ".join(lines)


def test_unknown_language_is_refused():
    with pytest.raises(ValueError):
        _notice(7, "fr")


# --- officer action, roles, storage, audit, citizen page (database + API) ------------------------------------

@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for n in (7, 18, 1):
            seed_case(s, _case("land_acquisition", n))
            s.commit()
            for step in (verify_documents, check_eligibility, compute_compensation, submit_to_officer):
                step(s, f"LA-{n:02d}")
    return engine


@pytest.fixture
def app(engine, tmp_path):
    return create_app(engine=engine, upload_dir=tmp_path)


@pytest.mark.parametrize("headers, status", [
    (staff("clerk", "C-1"), 403), (staff("admin", "A-1"), 403), ({}, 401)])     # {} = a citizen: no sign-in
def test_only_an_officer_can_preview_or_send(app, engine, headers, status):
    got = [call(app, "GET", "/cases/LA-07/notice", headers=headers),
           call(app, "POST", "/cases/LA-07/notice", body={"language": "en"}, headers=headers)]
    assert [code for code, _ in got] == [status, status]
    if status == 403:   # refused by the route's own role check, before the tool is reached (two layers)
        assert all(body["detail"].startswith("Role ") and body["detail"].endswith("cannot do this") for _, body in got)
    with Session(engine) as s:
        assert s.get(Case, "LA-07").status == "in_officer_review"
        assert s.query(DeficiencyNotice).count() == 0


def test_the_tool_itself_refuses_a_non_officer(engine):
    with Session(engine) as s:
        with pytest.raises(PermissionError):
            send_notice(s, "LA-07", role="clerk", officer_id="C-1")


def test_preview_changes_nothing(app, engine):
    with Session(engine) as s:
        before = s.query(AuditLog).count()
    status, body = call(app, "GET", "/cases/LA-07/notice?language=en", headers=staff("officer", "O-1"))
    assert status == 200 and [i["document"] for i in body["items"]] == ["mutation_record"]
    assert body["lines"][2] == "Mutation record: not submitted. Please bring it."
    with Session(engine) as s:
        assert s.get(Case, "LA-07").status == "in_officer_review"
        assert s.query(DeficiencyNotice).count() == 0 and s.query(AuditLog).count() == before


def test_sending_stores_audits_and_moves_the_case_and_nothing_else(app, engine):
    with Session(engine) as s:
        rules = [(r.rule_id, r.status) for r in s.query(RuleResultRow).filter_by(case_id="LA-07")]
        amounts = [(i.component, i.amount) for i in s.query(CompensationItemRow).filter_by(case_id="LA-07")]
    status, body = call(app, "POST", "/cases/LA-07/notice", body={"language": "hi"}, headers=staff("officer", "O-1"))
    assert status == 200 and body["language"] == "hi"
    with Session(engine) as s:
        assert s.get(Case, "LA-07").status == "needs_info"
        (notice,) = s.query(DeficiencyNotice).all()
        assert notice.language == "hi" and notice.officer_id == "O-1"
        assert [i["document"] for i in json.loads(notice.items_json)] == ["mutation_record"]
        (row,) = s.query(AuditLog).filter_by(case_id="LA-07", action="deficiency_notice_sent").all()
        payload = json.loads(row.payload_json)
        assert payload["status"] == "needs_info" and payload["previous_status"] == "in_officer_review"
        assert payload["lines"] == json.loads(notice.lines_json) and payload["language"] == "hi"
        # not a decision path: no decision row, rules and amounts untouched
        assert not s.query(AuditLog).filter_by(case_id="LA-07", action="officer_decision").count()
        assert [(r.rule_id, r.status) for r in s.query(RuleResultRow).filter_by(case_id="LA-07")] == rules
        assert [(i.component, i.amount) for i in s.query(CompensationItemRow).filter_by(case_id="LA-07")] == amounts


def test_nothing_to_ask_for_is_refused(app):
    assert call(app, "POST", "/cases/LA-18/notice", body={"language": "en"}, headers=staff("officer", "O-1"))[0] == 409
    assert call(app, "POST", "/cases/LA-01/notice", body={"language": "en"}, headers=staff("officer", "O-1"))[0] == 409


def test_only_cases_in_review(engine):
    with Session(engine) as s:
        send_notice(s, "LA-07", role="officer", officer_id="O-1")
        with pytest.raises(ToolError, match="only during officer review"):
            preview_notice(s, "LA-07", role="officer")


def test_unknown_language_is_a_bad_request(app):
    status, _ = call(app, "POST", "/cases/LA-07/notice", body={"language": "fr"}, headers=staff("officer", "O-1"))
    assert status == 400


def test_the_tracking_page_shows_documents_needed_from_the_stored_notice(engine):
    with Session(engine) as s:
        send_notice(s, "LA-07", role="officer", officer_id="O-1", language="mr")
        view = citizen_view(s, s.get(Case, "LA-07"))
    assert view["status"] == "needs_info" and view["next_step"] == "provide_documents"
    needed = view["documents_needed"]
    assert needed["language"] == "mr" and needed["items"] == [
        {"kind": "missing", "document": "mutation_record", "fields": [], "field_labels": []}]
    assert set(needed) == {"items", "language", "date"}


def test_a_plain_send_back_after_a_notice_does_not_show_the_old_notice(engine):
    from app.tools import record_officer_decision
    with Session(engine) as s:
        send_notice(s, "LA-07", role="officer", officer_id="O-1")
        s.get(Case, "LA-07").status = "in_officer_review"      # back in review, then sent back without a notice
        s.commit()
        record_officer_decision(s, "LA-07", role="officer", officer_id="O-1", decision="send_back", comment="call us")
        assert citizen_view(s, s.get(Case, "LA-07"))["documents_needed"] is None


def test_replacement_documents_continue_the_existing_flow(engine, tmp_path):
    """What happens to the open flags: they stay on the case until verification runs again; then they are
    recomputed from the documents, so a fixed problem's flag disappears. The notice stays in the record but is
    no longer shown to the citizen once the case leaves needs_info."""
    path = tmp_path / "mutation.txt"
    path.write_text("Mutation record (synthetic)", encoding="utf-8")
    with Session(engine) as s:
        send_notice(s, "LA-07", role="officer", officer_id="O-1")
        add_document(s, "LA-07", "mutation_record", str(path))
        assert s.get(Case, "LA-07").status == "received"
        assert "missing_document" in {f.kind for f in s.query(VerificationFlag).filter_by(case_id="LA-07")}
        assert citizen_view(s, s.get(Case, "LA-07"))["documents_needed"] is None
        verify_documents(s, "LA-07")
        kinds = {f.kind for f in s.query(VerificationFlag).filter_by(case_id="LA-07")}
        assert "missing_document" not in kinds
        assert s.query(DeficiencyNotice).filter_by(case_id="LA-07").count() == 1


# --- citizen dates read "17 Nov 2026", as the web formats them (bug-fix round E) -----------------------------------

def test_india_day_is_the_friendly_india_date():
    from datetime import datetime, timezone
    from app.models import india_day
    assert india_day(datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)) == "17 Nov 2026"
    assert india_day(datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)) == "7 Sept 2026"           # en-IN spelling
    assert india_day(datetime(2026, 11, 16, 19, 0, tzinfo=timezone.utc)) == "17 Nov 2026"        # 00:30 IST next day


def test_the_notice_text_dates_the_notice_in_the_friendly_format(app):
    import re
    lines = call(app, "GET", "/cases/LA-07/notice?language=en", headers=staff("officer", "O-1"))[1]["lines"]
    assert re.fullmatch(r"Notice issued on \d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Oct|Nov|Dec) \d{4}", lines[-1])
