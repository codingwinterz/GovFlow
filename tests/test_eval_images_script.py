from scripts.eval_images import plan_systems


def test_everything_skipped_without_binary_or_key():
    plan = dict(plan_systems(has_tesseract=False, has_key=False))
    assert plan == {"tesseract_only": "Tesseract binary not installed",
                    "gemini": "GEMINI_API_KEY not set",
                    "combined": "needs Tesseract and GEMINI_API_KEY"}


def test_tesseract_only_runs_without_key():
    plan = dict(plan_systems(has_tesseract=True, has_key=False))
    assert plan["tesseract_only"] is None and plan["gemini"] and plan["combined"]


def test_all_run_when_both_available():
    assert all(reason is None for _, reason in plan_systems(has_tesseract=True, has_key=True))


# --- report formatting (no network: built from fake runs) ----------------------

from app.evaluation import run_messy_eval
from app.extraction import ExtractionResult
from app.providers.fake import FailingProvider
from scripts.eval_images import progress_line, report_lines
from tests.test_image_eval import PartlyFailing


def test_report_shows_answered_over_total_next_to_accuracy():
    text = "\n".join(report_lines("gemini", run_messy_eval(provider=PartlyFailing(), variant="text")))
    assert "answered 5/7 docs" in text and "accuracy" in text


def test_provider_errors_are_reported_apart_from_reading_errors():
    lines = report_lines("gemini", run_messy_eval(provider=PartlyFailing(), variant="text"))
    assert any(l.strip().startswith("provider errors: 2 (rate_limited x2)") for l in lines)
    assert any(l.strip().startswith("reading errors:") for l in lines)


def test_accuracy_is_not_applicable_when_nothing_answered():
    text = "\n".join(report_lines("gemini", run_messy_eval(provider=FailingProvider(), variant="clean")))
    assert "accuracy n/a" in text and "answered 0/7 docs" in text


def test_report_names_the_model_used():
    assert any("model test-model-1" in l for l in report_lines("gemini", run_messy_eval(provider=PartlyFailing())))


def test_printed_errors_never_contain_the_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "odd-shaped-key-123")
    report = run_messy_eval(provider=FailingProvider(kind="timeout", message="boom odd-shaped-key-123"),
                            variant="clean")
    assert "odd-shaped-key-123" not in "\n".join(report_lines("gemini", report))


def _result(**kw):
    return ExtractionResult(document_id="1", doc_type="survey_sheet", fields=[], low_confidence=[], missing=[],
                            used_fallback=False, provider="gemini", ocr_engine=None, **kw)


def test_progress_line_distinguishes_unavailable_from_read():
    assert progress_line("case_08.survey_sheet", _result()).split() == ["case_08.survey_sheet", "read", "0", "fields"]
    unavailable = progress_line("case_08.survey_sheet",
                                _result(status="extraction_unavailable", error_kind="rate_limited"))
    assert "UNAVAILABLE (rate_limited)" in unavailable


def test_report_shows_quota_and_retry_delay():
    from tests.test_image_eval import QuotaExhausted
    text = "\n".join(report_lines("gemini", run_messy_eval(provider=QuotaExhausted(), variant="clean")))
    assert "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in text and "retry in 41s" in text
    assert "limit 20" in text and "You exceeded your current quota" in text


def test_flag_scores_print_na_when_nothing_was_scored():
    text = "\n".join(report_lines("gemini", run_messy_eval(provider=FailingProvider(), variant="clean")))
    assert "flags precision n/a recall n/a (scored 0/8 cases" in text


# --- results file: written after every block, keys redacted ----------------------

import json

from scripts.eval_images import save_results


def test_results_saved_after_each_block_so_an_interrupted_run_keeps_them(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-1234567890")
    out = tmp_path / "eval_results" / "images_x.json"
    save_results(out, {"gemini/land_acquisition/clean": {"note": "ok"}})
    assert json.loads(out.read_text(encoding="utf-8")) == {"gemini/land_acquisition/clean": {"note": "ok"}}
    save_results(out, {"a": {"error": "failed with key test-key-1234567890"}, "b": {}})
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert set(saved) == {"a", "b"}
    assert "test-key-1234567890" not in out.read_text(encoding="utf-8")
