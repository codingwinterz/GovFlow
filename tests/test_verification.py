from datetime import date

from app.case_model import CaseIn
from app.rules_loader import load_scheme_by_name
from app.verification import name_score, verify_documents

SCHEME = load_scheme_by_name("land_acquisition")


def _case(case_id="T-1", status="received", app_name="Asha Naik", owner_name="Asha Naik",
          id_name="Asha Naik", id_conf=0.96, owner_survey="123/4", sheet_survey="123/4",
          claimed_ha=0.25, total_ha=1.0, drop=()) -> CaseIn:
    docs = {
        "application": {"fields": {"name": {"value": app_name}}},
        "ownership_record": {"fields": {
            "name": {"value": owner_name, "confidence": 0.97},
            "survey_number": {"value": owner_survey, "confidence": 0.95},
            "area": {"value": claimed_ha, "confidence": 0.95},
            "area_unit": {"value": "ha", "confidence": 0.95},
            "issue_date": {"value": "2026-10-01"},
        }},
        "identity_proof": {"fields": {
            "name": {"value": id_name, "confidence": id_conf},
            "expiry_date": {"value": "2030-01-01"},
        }},
        "survey_sheet": {"fields": {
            "survey_number": {"value": sheet_survey, "confidence": 0.95},
            "area": {"value": total_ha, "confidence": 0.95},
            "area_unit": {"value": "ha", "confidence": 0.95},
        }},
        "mutation_record": {"fields": {"issue_date": {"value": "2026-06-01"}}},
    }
    for d in drop:
        docs.pop(d)
    return CaseIn(case_id=case_id, scheme="land_acquisition", status=status,
                  reference_date=date(2026, 11, 15), documents=docs)


def _check(result, check_id):
    return next(c for c in result.checks if c.check_id == check_id)


# --- name scoring -----------------------------------------------------------

def test_name_score_ignores_case_punctuation_and_order():
    assert name_score("Asha Naik", "NAIK, Asha.") == 1.0


def test_name_score_ignores_spacing_inside_names():
    assert name_score("Maria D Souza", "Maria DSouza") == 1.0


# --- name_match -------------------------------------------------------------

def test_name_match_passes_for_same_name():
    check = _check(verify_documents(SCHEME, _case()), "name_match")
    assert check.status == "pass"
    assert check.score == 1.0


def test_name_match_passes_above_fuzzy_threshold():
    check = _check(verify_documents(SCHEME, _case(id_name="Prakash Kamath", owner_name="Prakash Kamat",
                                                  app_name="Prakash Kamat")), "name_match")
    assert check.status == "pass"


def test_name_match_between_thresholds_needs_review():
    # 0.889: above confidence_threshold 0.85, below fuzzy 0.9
    check = _check(verify_documents(SCHEME, _case(app_name="Santosh Parab", owner_name="Santosh Parab",
                                                  id_name="Santosh Prabhu")), "name_match")
    assert check.status == "needs_review"
    assert 0.85 <= check.score < 0.9


def test_name_match_fails_for_different_person():
    check = _check(verify_documents(SCHEME, _case(id_name="Vinod Shetty")), "name_match")
    assert check.status == "fail"
    assert check.severity == "high"


def test_name_match_cites_the_documents_and_field():
    check = _check(verify_documents(SCHEME, _case(id_name="Vinod Shetty")), "name_match")
    assert "identity_proof.name" in check.sources
    assert "ownership_record.name" in check.sources


def test_name_match_with_low_confidence_field_needs_review():
    check = _check(verify_documents(SCHEME, _case(id_conf=0.5)), "name_match")
    assert check.status == "needs_review"
    assert "identity_proof.name" in check.detail


def test_name_match_with_missing_document_needs_review():
    check = _check(verify_documents(SCHEME, _case(drop=("identity_proof",))), "name_match")
    assert check.status == "needs_review"


# --- survey_no_match --------------------------------------------------------

def test_survey_match_normalises_whitespace_and_case():
    check = _check(verify_documents(SCHEME, _case(owner_survey="123/4-a", sheet_survey=" 123/4-A ")),
                   "survey_no_match")
    assert check.status == "pass"


def test_survey_mismatch_fails():
    check = _check(verify_documents(SCHEME, _case(sheet_survey="132/4")), "survey_no_match")
    assert check.status == "fail"


# --- duplicate_claim --------------------------------------------------------

def test_no_other_cases_is_not_duplicate():
    assert _check(verify_documents(SCHEME, _case()), "duplicate_claim").status == "pass"


def test_overlapping_open_claim_needs_review_with_high_severity():
    other = _case(case_id="T-2", claimed_ha=0.9)   # 0.25 + 0.9 > 1.0 ha survey total
    check = _check(verify_documents(SCHEME, _case(), [other]), "duplicate_claim")
    assert check.status == "needs_review"
    assert check.severity == "high"
    assert "T-2" in check.detail


def test_co_owner_claims_within_survey_total_are_not_duplicates():
    other = _case(case_id="T-2", claimed_ha=0.5)   # 0.25 + 0.5 <= 1.0 ha
    assert _check(verify_documents(SCHEME, _case(), [other]), "duplicate_claim").status == "pass"


def test_closed_cases_are_ignored():
    other = _case(case_id="T-2", claimed_ha=0.9, status="rejected")
    assert _check(verify_documents(SCHEME, _case(), [other]), "duplicate_claim").status == "pass"


def test_same_case_id_is_not_its_own_duplicate():
    assert _check(verify_documents(SCHEME, _case(), [_case()]), "duplicate_claim").status == "pass"


def test_different_survey_number_is_not_duplicate():
    other = _case(case_id="T-2", owner_survey="999/1", sheet_survey="999/1", claimed_ha=0.9)
    assert _check(verify_documents(SCHEME, _case(), [other]), "duplicate_claim").status == "pass"


def test_unknown_survey_total_with_same_survey_needs_review():
    other = _case(case_id="T-2", claimed_ha=0.1)
    check = _check(verify_documents(SCHEME, _case(drop=("survey_sheet",)), [other]), "duplicate_claim")
    assert check.status == "needs_review"


# --- flags ------------------------------------------------------------------

def test_flags_summarise_problems():
    case = _case(id_name="Vinod Shetty", drop=("mutation_record",))
    kinds = {f.kind for f in verify_documents(SCHEME, case).flags}
    assert {"name_match", "missing_document"} <= kinds


def test_clean_case_has_no_flags():
    assert verify_documents(SCHEME, _case()).flags == []


def test_expired_document_is_flagged():
    case = _case()
    case.documents["identity_proof"].fields["expiry_date"].value = "2026-01-01"
    flags = verify_documents(SCHEME, case).flags
    assert any(f.kind == "document_expired" and "identity_proof" in f.detail for f in flags)


# --- policy: approved claims still count as competing; rejected/withdrawn do not ------

def test_approved_case_still_counts_as_competing_claim():
    other = _case(case_id="T-2", claimed_ha=0.9, status="approved")
    assert _check(verify_documents(SCHEME, _case(), [other]), "duplicate_claim").status == "needs_review"


def test_withdrawn_cases_are_ignored():
    other = _case(case_id="T-2", claimed_ha=0.9, status="withdrawn")
    assert _check(verify_documents(SCHEME, _case(), [other]), "duplicate_claim").status == "pass"


# --- policy: a dropped middle name is never a fail -------------------------------------

def test_dropped_middle_name_needs_review_not_fail():
    # scores 0.786 (< 0.85), which would otherwise be a fail
    check = _check(verify_documents(SCHEME, _case(app_name="Anil Kumar Sawant", owner_name="Anil Kumar Sawant",
                                                  id_name="Anil Sawant")), "name_match")
    assert check.status == "needs_review"
    assert "middle name" in check.detail


def test_middle_initial_versus_none_needs_review():
    check = _check(verify_documents(SCHEME, _case(app_name="Anil K Sawant", owner_name="Anil K Sawant",
                                                  id_name="Anil Sawant")), "name_match")
    assert check.status == "needs_review"


def test_dropped_surname_is_not_treated_as_middle_name():
    check = _check(verify_documents(SCHEME, _case(id_name="Asha")), "name_match")
    assert check.status == "fail"


def test_different_middle_names_are_not_a_dropped_middle_name():
    check = _check(verify_documents(SCHEME, _case(app_name="Anil Kumar Sawant", owner_name="Anil Kumar Sawant",
                                                  id_name="Anil Ramesh Sawant")), "name_match")
    assert check.status != "pass"
    assert "middle name" not in check.detail


def test_unavailable_extraction_is_flagged_for_retry():
    case = _case()
    case.documents["identity_proof"].extraction_unavailable = True
    flags = verify_documents(load_scheme_by_name("land_acquisition"), case).flags
    assert [f.detail for f in flags if f.kind == "extraction_unavailable"] == [
        "identity_proof: extraction unavailable, retry"]
