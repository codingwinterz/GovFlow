"""Real-evaluation path over rendered document images (clean and degraded).

Three systems, reported separately:
  tesseract_only  Tesseract OCR + label parser, no LLM (baseline)
  gemini          Gemini vision, no OCR fallback
  combined        Gemini vision first, Tesseract OCR + Gemini text pass for weak fields

Needs: Tesseract binary (TESSERACT_CMD if not on PATH) and/or GEMINI_API_KEY in the environment.
Full results, including model outputs, are written to eval_results/ (gitignored, never commit).

Usage: python -m scripts.eval_images
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.evaluation import EvalReport, run_messy_eval

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"
VARIANTS = ("clean", "degraded")


def plan_systems(has_tesseract: bool, has_key: bool) -> list[tuple[str, Optional[str]]]:
    """Each system with the reason it is skipped, or None if it can run."""
    return [
        ("tesseract_only", None if has_tesseract else "Tesseract binary not installed"),
        ("gemini", None if has_key else "GEMINI_API_KEY not set"),
        ("combined", None if (has_tesseract and has_key) else "needs Tesseract and GEMINI_API_KEY"),
    ]


def _build(system: str):
    from app.providers.gemini import GeminiProvider
    from app.providers.tesseract import TesseractBaselineProvider, TesseractOcr
    if system == "tesseract_only":
        return TesseractBaselineProvider(), None
    if system == "gemini":
        return GeminiProvider(), None
    return GeminiProvider(), TesseractOcr()


def _line(system: str, r: EvalReport) -> str:
    e, f = r.extraction, r.flags
    return (f"{system:<15}{r.variant:<10}{e.correct:>3}/{e.total:<4}{e.accuracy:>8.3f}{e.accepted:>9}"
            f"{e.accepted_wrong:>8}{e.routed_to_review:>8}{f.precision:>8.3f}{f.recall:>8.3f}{len(r.errors):>7}")


def main() -> None:
    from app.env_file import load_env_file
    from app.providers.tesseract import tesseract_available
    loaded = load_env_file(RESULTS_DIR.parent / ".env")
    if loaded:
        print(f"Loaded from .env: {', '.join(loaded)}")
    plan = plan_systems(tesseract_available(), bool(os.environ.get("GEMINI_API_KEY")))
    print(f"{'system':<15}{'variant':<10}{'correct':<8}{'acc':>8}{'accepted':>9}{'WRONG':>8}{'review':>8}"
          f"{'flagP':>8}{'flagR':>8}{'errors':>7}")
    saved = {}
    for system, skip in plan:
        if skip:
            print(f"{system:<15}SKIPPED: {skip}")
            continue
        provider, ocr = _build(system)
        for variant in VARIANTS:
            report = run_messy_eval(provider=provider, ocr=ocr, variant=variant)
            print(_line(system, report))
            for err in report.errors:
                print(f"{'':<15}  error: {err}")
            saved[f"{system}/{variant}"] = report.model_dump(mode="json")
    if saved:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"images_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        out.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        print(f"\nFull rows written to {out} (gitignored)")


if __name__ == "__main__":
    main()
