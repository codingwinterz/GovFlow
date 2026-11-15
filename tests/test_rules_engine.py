from app.rules_engine import check_eligibility, overall_from
from app.rules_loader import load_scheme_by_name
from app.verification import verify_documents
from tests.test_verification import _case

SCHEME = load_scheme_by_name("land_acquisition")


def _assess(case, others=None):
    return check_eligibility(SCHEME, case, verify_documents(SCHEME, case, others))


def _rule(result, rule_id):
    return next(r for r in result.results if r.rule_id == rule_id)


def test_clean_case_is_eligible_and_cites_clauses():
    result = _assess(_case())
    assert result.overall == "eligible"
    assert all(r.status == "pass" for r in result.results)
    assert all(r.clause for r in result.results)
    assert result.rules_version == "0.1.0"


def test_name_mismatch_fails_valid_ownership_via_check_result():
    result = _assess(_case(id_name="Vinod Shetty"))
    rule = _rule(result, "valid_ownership")
    assert rule.status == "fail"
    assert "name_match" in rule.reason
    assert result.overall == "not_eligible"


def test_name_in_review_band_makes_ownership_needs_review():
    result = _assess(_case(app_name="Santosh Parab", owner_name="Santosh Parab", id_name="Santosh Prabhu"))
    assert _rule(result, "valid_ownership").status == "needs_review"
    assert result.overall == "needs_review"


def test_missing_document_fails_documents_complete():
    result = _assess(_case(drop=("mutation_record",)))
    assert _rule(result, "documents_complete").status == "fail"
    assert result.overall == "not_eligible"


def test_missing_ownership_record_fails_valid_ownership():
    # name_match is needs_review (doc missing) but `when` is definitively false -> fail
    assert _rule(_assess(_case(drop=("ownership_record",))), "valid_ownership").status == "fail"


def test_expired_document_fails_documents_not_expired():
    case = _case()
    case.documents["identity_proof"].fields["expiry_date"].value = "2026-01-01"
    assert _rule(_assess(case), "documents_not_expired").status == "fail"


def test_unreadable_validity_date_needs_review():
    case = _case()
    case.documents["identity_proof"].fields["expiry_date"].confidence = 0.4
    rule = _rule(_assess(case), "documents_not_expired")
    assert rule.status == "needs_review"
    assert "all_documents_valid" in rule.reason


def test_survey_mismatch_fails_land_identified():
    assert _rule(_assess(_case(sheet_survey="132/4")), "land_identified").status == "fail"


def test_duplicate_claim_routes_to_review_not_rejection():
    other = _case(case_id="T-2", claimed_ha=0.9)
    result = _assess(_case(), [other])
    assert _rule(result, "no_competing_claim").status == "needs_review"
    assert result.overall == "needs_review"


def test_overall_fail_dominates_review():
    assert overall_from(["pass", "needs_review", "fail"]) == "not_eligible"
    assert overall_from(["pass", "needs_review"]) == "needs_review"
    assert overall_from(["pass", "pass"]) == "eligible"
