"""duplicate_survey_claim (land acquisition): another open or decided case names the same survey number.

Defined in the YAML on the duplicate_claim built-in with `ignore_statuses: [withdrawn]`, so approved and rejected
cases count, and with no area fields, so co-owners whose areas fit are still flagged. Severity high, needs_review,
never fail. The officer sees the other case's reference; the citizen sees only a notice key
(notice.claim_verification, "Additional verification is in progress.").

Hand-derived base: LA-14 (Meena Kamat, survey 77/1) alone is eligible with no flags. Its co-owner LA-15 also names
77/1 (both are flagged in the synthetic set); the tests below pass the other cases explicitly."""

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.assessment import assess_case
from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_view
from app.main import create_app
from app.models import Case, VerificationFlag, make_engine
from app.rules_loader import Scheme, load_scheme_by_name
from app.tools import verify_documents
from app.verification import verify_documents as verify_pure
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
LA = load_scheme_by_name("land_acquisition")
FLAG = "duplicate_survey_claim"


def _la14() -> CaseIn:
    return CaseIn.model_validate_json((DATA / "case_14" / "case.json").read_text(encoding="utf-8"))


def _other(survey="77/1", status="received", case_id="LA-91", name="Sunil Kamat") -> CaseIn:
    case = _la14().model_copy(deep=True)
    case.case_id, case.status = case_id, status
    for doc in case.documents.values():
        if "survey_number" in doc.fields:
            doc.fields["survey_number"].value = survey
        if "name" in doc.fields:
            doc.fields["name"].value = name
    return case


def _check(case, others):
    result = verify_pure(LA, case, others)
    check = next(c for c in result.checks if c.check_id == FLAG)
    flags = [f for f in result.flags if f.kind == FLAG]
    return check, flags


# --- YAML definition ------------------------------------------------------------------------------------------

def test_defined_in_the_yaml_on_the_duplicate_built_in():
    check = next(c for c in LA.verification_checks if c.id == FLAG)
    assert (check.builtin, check.key, check.severity) == ("duplicate_claim", "ownership_record.survey_number", "high")
    assert check.ignore_statuses == ["withdrawn"]
    assert (check.claimed_area, check.total_area) == (None, None)
    assert check.citizen_notice == "claim_verification"
    assert check.approval_needs_resolution is False
    assert LA.terms[FLAG] == "Survey number named in another case"


def test_the_existing_duplicate_claim_keeps_its_statuses():
    check = next(c for c in LA.verification_checks if c.id == "duplicate_claim")
    assert check.ignore_statuses is None          # default: rejected and withdrawn do not compete


def test_loader_rejects_an_unknown_status():
    raw = LA.model_dump()
    dup = next(c for c in raw["verification_checks"] if c["id"] == FLAG)
    dup["ignore_statuses"] = ["withdrawn", "closed_forever"]
    with pytest.raises(ValueError, match="closed_forever"):
        Scheme.model_validate(raw)


# --- who is flagged ---------------------------------------------------------------------------------------------

def test_a_duplicate_is_flagged_on_both_cases_with_the_other_reference():
    a, b = _la14(), _other()
    check_a, flags_a = _check(a, [a, b])
    check_b, flags_b = _check(b, [a, b])
    assert check_a.status == check_b.status == "needs_review"
    assert [f.severity for f in flags_a] == [f.severity for f in flags_b] == ["high"]
    assert "LA-91" in flags_a[0].detail and "77/1" in flags_a[0].detail
    assert "LA-14" in flags_b[0].detail
    assert "Sunil Kamat" not in flags_a[0].detail and "Meena Kamat" not in flags_b[0].detail


def test_a_different_survey_number_is_not_flagged():
    a = _la14()
    check, flags = _check(a, [a, _other(survey="78/1")])
    assert (check.status, flags) == ("pass", [])


def test_the_existing_normalisation_applies():
    a = _la14()
    check, _ = _check(a, [a, _other(survey=" 77 / 1 ")])
    assert check.status == "needs_review"


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_a_decided_case_still_triggers_it(status):
    a = _la14()
    check, flags = _check(a, [a, _other(status=status)])
    assert check.status == "needs_review" and len(flags) == 1 and "LA-91" in flags[0].detail


def test_a_rejected_duplicate_does_not_change_duplicate_claim():
    a = _la14()
    result = verify_pure(LA, a, [a, _other(status="rejected")])
    assert next(c for c in result.checks if c.check_id == "duplicate_claim").status == "pass"


def test_a_withdrawn_case_does_not_trigger_it():
    a = _la14()
    check, flags = _check(a, [a, _other(status="withdrawn")])
    assert (check.status, flags) == ("pass", [])


def test_the_case_alone_is_not_its_own_duplicate():
    a = _la14()
    assert _check(a, [a])[0].status == "pass"


def test_it_recommends_review_and_never_rejects():
    a = _la14()
    alone = assess_case(LA, a, [a])
    assert (alone.eligibility.overall, alone.needs_human_review) == ("eligible", False)
    with_dup = assess_case(LA, a, [a, _other(status="approved")])
    assert with_dup.eligibility.overall == "needs_review"
    assert {r.rule_id: r.status for r in with_dup.eligibility.results}["no_competing_claim"] == "needs_review"
    assert with_dup.needs_human_review is True
    assert all(c.status != "fail" for c in with_dup.verification.checks)


# --- stored flag, officer view, citizen view -------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'dup.db'}")
    with Session(engine) as s:
        seed_case(s, _la14())
        seed_case(s, _other(status="approved"))
    return engine


def test_stored_flag_and_officer_view_name_the_other_case(engine, tmp_path):
    with Session(engine) as s:
        verify_documents(s, "LA-14")
        (flag,) = s.query(VerificationFlag).filter_by(case_id="LA-14", kind=FLAG).all()
        assert flag.severity == "high" and "LA-91" in flag.detail
    status, detail = call(create_app(engine=engine, upload_dir=tmp_path), "GET", "/cases/LA-14",
                          headers=staff("officer", "O-1"))
    assert status == 200
    shown = [f for f in detail["flags"] if f["kind"] == FLAG]
    assert len(shown) == 1 and "LA-91" in shown[0]["detail"]


def test_a_rejected_case_in_the_database_still_triggers_it(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'rej.db'}")
    with Session(engine) as s:
        seed_case(s, _la14())
        seed_case(s, _other(status="rejected"))
        verify_documents(s, "LA-14")
        assert s.query(VerificationFlag).filter_by(case_id="LA-14", kind=FLAG).count() == 1
        assert s.query(VerificationFlag).filter_by(case_id="LA-14", kind="duplicate_claim").count() == 0


def test_citizen_sees_only_the_notice(engine):
    with Session(engine) as s:
        verify_documents(s, "LA-14")
        view = citizen_view(s, s.get(Case, "LA-14"))
    assert view["notices"] == ["claim_verification"]
    text = json.dumps(view)
    for leak in ("LA-91", "Sunil Kamat", FLAG, "77/1"):
        assert leak not in text


def test_citizen_notice_goes_after_a_decision(engine):
    with Session(engine) as s:
        verify_documents(s, "LA-14")
        s.get(Case, "LA-14").status = "approved"
        s.commit()
        assert citizen_view(s, s.get(Case, "LA-14"))["notices"] == []


def test_notice_text_exists_in_every_language():
    i18n = Path(__file__).resolve().parent.parent / "web" / "src" / "i18n"
    texts = {lang: json.loads((i18n / f"{lang}.json").read_text(encoding="utf-8")).get("notice.claim_verification")
             for lang in ("en", "hi", "mr", "kok")}
    assert texts["en"] == "Additional verification is in progress."
    assert all(texts.values()), texts
