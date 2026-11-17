"""A name containing digits, "?" or other symbols that do not occur in names fails the name match, whatever
the fuzzy score. "L?ta Sh1rodkar" scored 0.917 against "Lata Shirodkar" because symbols were dropped before
comparing, so a damaged reading passed. Letters in any script, spaces, apostrophes, hyphens and dots stay valid."""

from pathlib import Path

import pytest

from app.case_model import CaseIn
from app.rules_loader import load_scheme_by_name
from app.verification import has_non_name_characters, verify_documents

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"


@pytest.mark.parametrize("name", ["L?ta Sh1rodkar", "Lata Shirodkar 2", "Lata #Shirodkar", "Lata_Shirodkar",
                                  "Lata/Shirodkar", "Lata @ Shirodkar", "Lata Shirodkar*"])
def test_symbols_that_do_not_occur_in_names_are_detected(name):
    assert has_non_name_characters(name)


@pytest.mark.parametrize("name", ["Lata Shirodkar", "Esther D'Souza", "Esther D’Souza", "R. K. Naik",
                                  "Anne-Marie Fernandes", "अनिता सावंत", "  Lata   Shirodkar  "])
def test_ordinary_names_are_not_flagged(name):
    assert not has_non_name_characters(name)


def _la11(record_name, confidence=0.95):
    case = CaseIn.model_validate_json((DATA / "land_acquisition" / "case_11" / "case.json").read_text(encoding="utf-8"))
    case.documents["ownership_record"].fields["name"].value = record_name
    case.documents["ownership_record"].fields["name"].confidence = confidence
    return verify_documents(load_scheme_by_name("land_acquisition"), case)


def test_la11_damaged_name_fails_the_name_match_even_when_read_confidently():
    result = _la11("L?ta Sh1rodkar")
    (check,) = [c for c in result.checks if c.check_id == "name_match"]
    assert check.status == "fail" and "L?ta Sh1rodkar" in check.detail and "not found in names" in check.detail
    assert "name_match" in {f.kind for f in result.flags}


def test_la11_with_the_clean_name_still_passes():
    (check,) = [c for c in _la11("Lata Shirodkar").checks if c.check_id == "name_match"]
    assert check.status == "pass"


def test_relief_name_with_an_apostrophe_still_passes():
    case = CaseIn.model_validate_json((DATA / "disaster_relief" / "case_05" / "case.json").read_text(encoding="utf-8"))
    (check,) = [c for c in verify_documents(load_scheme_by_name("disaster_relief"), case).checks
                if c.check_id == "name_match"]
    assert check.status == "pass"      # DR-05 is "Esther D'Souza" on every document
