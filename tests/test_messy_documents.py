"""End-to-end over the messy synthetic documents: extract (fake provider) -> verify -> flags."""

from app.evaluation import run_messy_eval

REPORT = run_messy_eval()


def test_every_expected_flag_is_raised_and_nothing_extra():
    assert REPORT.flags.false_negatives == []
    assert REPORT.flags.false_positives == []
    assert REPORT.flags.precision == 1.0 and REPORT.flags.recall == 1.0


def test_no_wrong_value_is_accepted_with_confidence():
    assert REPORT.extraction.accepted_wrong == 0


def test_garbled_name_is_routed_to_review_not_guessed():
    row = next(r for r in REPORT.extraction.rows if r.case == "case_11" and r.field == "name")
    assert row.accepted is False and row.correct is False


def test_ocr_fallback_confirmed_faint_unit():
    row = next(r for r in REPORT.extraction.rows if r.case == "case_09" and r.field == "area_unit")
    assert row.accepted is True and row.method == "ocr_fallback"


def test_report_states_provider_used():
    assert REPORT.providers == {"fake"}
