"""Typed fields: extracted strings are coerced once, before any rule, check or formula sees them.
A value that cannot be coerced goes to needs_review with a clear reason. Never a crash, never a guess."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.assessment import assess_case
from app.case_model import CaseIn
from app.case_store import seed_case
from app.extraction import ProviderField
from app.field_types import coerce
from app.models import Document, make_engine, make_session
from app.providers.fake import FakeProvider
from app.rules_loader import RULES_DIR, RulesError, load_scheme_by_name, parse_scheme
from app.tools import check_eligibility, compute_compensation, extract_document, verify_documents

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
DR = load_scheme_by_name("disaster_relief")


# --- coerce() ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, value", [("80", 80.0), ("80.0", 80.0), (" 80 ", 80.0), (80, 80.0), (74.9, 74.9),
                                        ("-5", -5.0), (".5", 0.5)])
def test_number_accepts_plain_numbers(raw, value):
    assert coerce("number", raw) == (value, None)


@pytest.mark.parametrize("raw, reason", [
    ("80%", "not a plain number"), ("eighty", "not a plain number"), ("", "empty"), ("   ", "empty"),
    (None, "empty"), ("1,0,00", "not a plain number"), ("nan", "not a plain number"), ("inf", "not a plain number"),
    (True, "not a plain number"),
])
def test_number_rejects_anything_else_with_a_reason(raw, reason):
    value, error = coerce("number", raw)
    assert value is None and reason in error and (raw is None or repr(raw) in error or reason == "empty")


@pytest.mark.parametrize("raw, value, error", [
    ("2026-11-15", date(2026, 11, 15), None), (" 2026-11-15 ", date(2026, 11, 15), None),
    (date(2026, 1, 2), date(2026, 1, 2), None),
    ("15/11/2026", date(2026, 11, 15), None), ("11/15/2026", None, "not a date"),   # day first only
    ("2026-02-30", None, "not a date"), ("", None, "empty"),
])
def test_date(raw, value, error):
    got, why = coerce("date", raw)
    assert got == value and (why is None if error is None else error in why)


@pytest.mark.parametrize("raw, ok", [("sq ft", True), (" Ha ", True), ("sqm", True), ("bigha", False), ("", False)])
def test_unit(raw, ok):
    value, error = coerce("unit", raw)
    assert (value == raw.strip() and error is None) if ok else (value is None and error)


@pytest.mark.parametrize("raw, value", [(" Asha Naik ", "Asha Naik"), (7, "7"), ("H-7", "H-7")])
def test_text(raw, value):
    assert coerce("text", raw) == (value, None)


def test_empty_text_is_rejected():
    assert coerce("text", "  ")[1] == "empty value"


# --- through the rules: DR-01 with the damage percentage as a real extraction would return it ---

def _dr01(damage):
    path = DATA / "disaster_relief" / "case_01" / "case.json"
    case = CaseIn.model_validate_json(path.read_text(encoding="utf-8"))
    case.documents["damage_assessment"].fields["damage_percent"].value = damage
    return case


@pytest.mark.parametrize("damage", ["80", "80.0", " 80 ", "80%", " 80 % "])
def test_numeric_strings_give_the_same_outcome_as_numbers(damage):
    result = assess_case(DR, _dr01(damage), [])
    assert result.eligibility.overall == "eligible" and result.compensation.total == 125000
    assert not [f for f in result.verification.flags if f.kind == "invalid_value"]


@pytest.mark.parametrize("damage, reason", [("eighty", "not a percentage"), ("80%%", "not a percentage"),
                                            ("", "empty")])
def test_uncoercible_values_go_to_review_with_a_reason(damage, reason):
    result = assess_case(DR, _dr01(damage), [])                 # must not raise
    rule = next(r for r in result.eligibility.results if r.rule_id == "damage_category_eligible")
    assert rule.status == "needs_review" and "damage_assessment.damage_percent" in rule.reason and reason in rule.reason
    assert result.eligibility.overall == "needs_review"
    assert result.compensation.status == "needs_review" and result.compensation.total is None
    assert any(reason in note for note in result.compensation.review_notes)
    (flag,) = [f for f in result.verification.flags if f.kind == "invalid_value"]
    assert "damage_assessment.damage_percent" in flag.detail and reason in flag.detail
    assert result.needs_human_review


def test_invalid_document_value_never_falls_back_to_a_default():
    data = yaml.safe_load((RULES_DIR / "disaster_relief.yaml").read_text(encoding="utf-8"))
    data["compensation"]["inputs"]["damage_percent"]["default"] = 50   # a default must not hide a bad reading
    result = assess_case(parse_scheme(data), _dr01("eighty"), [])
    assert result.compensation.status == "needs_review" and "damage_percent" in result.compensation.missing


def test_invalid_date_makes_validity_unknown_not_valid():
    case = _dr01(80)
    case.documents["identity_proof"].fields["expiry_date"].value = "12/31/2030"   # month first: not a day-first date
    result = assess_case(DR, case, [])
    kinds = {f.kind for f in result.verification.flags}
    assert {"invalid_value", "validity_unknown"} <= kinds
    rule = next(r for r in result.eligibility.results if r.rule_id == "documents_not_expired")
    assert rule.status == "needs_review"


def test_bad_unit_on_land_record_is_flagged_with_its_reason():
    path = DATA / "land_acquisition" / "case_01" / "case.json"
    case = CaseIn.model_validate_json(path.read_text(encoding="utf-8"))
    case.documents["ownership_record"].fields["area_unit"].value = "bigha"
    result = assess_case(load_scheme_by_name("land_acquisition"), case, [])
    (flag,) = [f for f in result.verification.flags if f.kind == "invalid_value"]
    assert "ownership_record.area_unit" in flag.detail and "bigha" in flag.detail
    assert result.compensation.status == "needs_review"


# --- end to end: extracted strings stored in the DB, then assessed ---------------------------

@pytest.mark.parametrize("damage, overall", [("80", "eligible"), ("80%", "eligible"), ("eighty", "needs_review"),
                                             ("", "needs_review")])
def test_extracted_strings_through_the_database(tmp_path, damage, overall):
    case = _dr01(80)
    del case.documents["damage_assessment"]
    with make_session(make_engine("sqlite://")) as s:
        seed_case(s, case)
        path = tmp_path / "damage.txt"
        path.write_text("scan", encoding="utf-8")
        doc = Document(case_id="DR-01", doc_type="damage_assessment", file_path=str(path))
        s.add(doc)
        s.commit()
        values = {"house_number": "H-101", "village": "Siolim", "damage_percent": damage, "notified_area": "yes",
                  "house_type": "Pucca", "area_type": "plain", "assessment_date": "2026-10-20"}
        provider = FakeProvider({(str(doc.id), "document"): [
            ProviderField(name=k, value=v, confidence=0.95, page=1) for k, v in values.items()]})
        extract_document(s, doc.id, provider)
        verify_documents(s, "DR-01")
        assert check_eligibility(s, "DR-01").overall == overall
        assert (compute_compensation(s, "DR-01").total == 125000) == (overall == "eligible")


# --- the YAML declares the types ---------------------------------------------------------

def _yaml(name):
    return yaml.safe_load((RULES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def test_both_schemes_declare_types_for_every_field():
    for name in ("land_acquisition", "disaster_relief"):
        scheme = load_scheme_by_name(name)
        for doc in scheme.required_documents:
            assert set(doc.types) == set(doc.fields), (name, doc.id)
    assert load_scheme_by_name("disaster_relief").required_documents[3].types["damage_percent"] == "percent"


def test_unknown_type_is_rejected():
    data = _yaml("disaster_relief")
    data["required_documents"][3]["fields"]["damage_percent"] = "percentage"
    with pytest.raises(RulesError, match="percentage"):
        parse_scheme(data)


def test_validity_field_must_be_a_date():
    data = _yaml("disaster_relief")
    data["required_documents"][1]["fields"]["expiry_date"] = "text"
    with pytest.raises(RulesError, match="expiry_date.*date"):
        parse_scheme(data)


def test_plain_field_list_still_loads_as_text():
    data = _yaml("disaster_relief")
    data["required_documents"][0]["fields"] = ["name"]
    assert parse_scheme(data).required_documents[0].types == {"name": "text"}


# --- digit grouping (Indian and Western) and the percent type ---------------------------------

@pytest.mark.parametrize("raw, value", [
    ("1,00,000", 100000.0), ("12,34,567.50", 1234567.5), ("100,000", 100000.0), ("1,234,567", 1234567.0),
    ("1,000", 1000.0), ("-1,00,000", -100000.0), (" 10,000 ", 10000.0),
])
def test_number_accepts_valid_indian_or_western_grouping(raw, value):
    assert coerce("number", raw) == (value, None)


@pytest.mark.parametrize("raw", ["1,0,00", "10,00", "1,00,00", "100,00,000", "1,000,00", ",100", "100,", "1,,000",
                                 "1,000.5,0", "1 000"])
def test_number_rejects_malformed_grouping(raw):
    value, error = coerce("number", raw)
    assert value is None and "not a plain number" in error


@pytest.mark.parametrize("raw, value", [("80%", 80.0), ("80", 80.0), (" 80 % ", 80.0), ("74.9%", 74.9), (15, 15.0)])
def test_percent_accepts_a_trailing_percent_sign(raw, value):
    assert coerce("percent", raw) == (value, None)


@pytest.mark.parametrize("raw", ["%80", "80%%", "eighty%", "", "8 0%", "80 percent"])
def test_percent_rejects_anything_else(raw):
    value, error = coerce("percent", raw)
    assert value is None and error


def test_number_still_rejects_a_percent_sign():
    assert coerce("number", "80%")[0] is None


def test_damage_percent_is_declared_as_percent():
    assert DR.required_documents[3].types["damage_percent"] == "percent"


# --- percent range: 0 to 100 inclusive -----------------------------------------------------------

@pytest.mark.parametrize("raw, value", [("0", 0.0), ("0%", 0.0), ("100", 100.0), ("100%", 100.0), (55.5, 55.5)])
def test_percent_accepts_zero_to_hundred_inclusive(raw, value):
    assert coerce("percent", raw) == (value, None)


@pytest.mark.parametrize("raw", ["100.01", "150%", "-5", "-0.1%", 101])
def test_percent_outside_range_is_rejected(raw):
    value, error = coerce("percent", raw)
    assert value is None and "outside 0-100" in error


@pytest.mark.parametrize("damage", ["120%", "-3"])
def test_out_of_range_damage_goes_to_review_naming_the_field(damage):
    result = assess_case(DR, _dr01(damage), [])
    rule = next(r for r in result.eligibility.results if r.rule_id == "damage_category_eligible")
    assert rule.status == "needs_review"
    assert "damage_assessment.damage_percent" in rule.reason and "outside 0-100" in rule.reason
    (flag,) = [f for f in result.verification.flags if f.kind == "invalid_value"]
    assert "damage_assessment.damage_percent" in flag.detail and "outside 0-100" in flag.detail
    assert result.compensation.status == "needs_review"
