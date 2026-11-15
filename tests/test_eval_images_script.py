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
