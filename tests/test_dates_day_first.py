"""Dates on Goa documents are printed day first (DD/MM/YYYY). The prompt says so and asks the model to copy the
date as printed; the code, not the model, turns it into a date, always day first. A value that is only valid
month-first (01/13/2026) is rejected and goes to review, never swapped."""

from datetime import date
from pathlib import Path

import pytest

from app.case_model import CaseIn
from app.field_types import coerce
from app.providers.gemini import OCR_PROMPT, PROMPT
from app.rules_loader import load_scheme_by_name
from app.verification import verify_documents

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"


def test_ambiguous_date_is_read_day_first():
    assert coerce("date", "01/10/2026") == (date(2026, 10, 1), None)


def test_day_above_twelve_is_unambiguous():
    assert coerce("date", "13/01/2026") == (date(2026, 1, 13), None)


@pytest.mark.parametrize("text", ["01-10-2026", "01.10.2026", "1/10/2026", " 01/10/2026 "])
def test_common_day_first_separators(text):
    assert coerce("date", text) == (date(2026, 10, 1), None)


def test_iso_still_accepted():
    assert coerce("date", "2026-10-01") == (date(2026, 10, 1), None)


@pytest.mark.parametrize("text", ["01/13/2026", "31/02/2026", "01/10/26", "1 Oct 2026", "2026/10/01"])
def test_month_first_or_unclear_dates_are_rejected_not_guessed(text):
    value, error = coerce("date", text)
    assert value is None and error


@pytest.mark.parametrize("prompt", [PROMPT, OCR_PROMPT])
def test_prompts_say_day_first_and_ask_for_the_date_as_printed(prompt):
    assert "DD/MM/YYYY" in prompt and "day first" in prompt
    assert "YYYY-MM-DD" not in prompt          # the model no longer reorders dates; the code does


def _la09_with_issue_date(value):
    case = CaseIn.model_validate_json((DATA / "land_acquisition" / "case_09" / "case.json").read_text(encoding="utf-8"))
    case.documents["ownership_record"].fields["issue_date"].value = value
    return case


def _kinds(case):
    return {f.kind for f in verify_documents(load_scheme_by_name("land_acquisition"), case).flags}


def test_la09_printed_date_read_day_first_is_not_expired():
    # LA-09's record is printed "Issued: 01/10/2026"; reference date 2026-11-15, record-of-rights age limit 180 days.
    kinds = _kinds(_la09_with_issue_date("01/10/2026"))
    assert "document_expired" not in kinds
    assert "invalid_value" not in kinds         # the date was read, not merely rejected


def test_la09_month_first_reading_would_have_expired_it():
    # What the model produced on 17 Nov when it converted the date itself: 10 January instead of 1 October.
    assert "document_expired" in _kinds(_la09_with_issue_date("2026-01-10"))
