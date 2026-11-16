"""Real-evaluation path over rendered document images (clean and degraded).

Three systems, reported separately:
  tesseract_only  Tesseract OCR + label parser, no LLM (baseline)
  gemini          Gemini vision, no OCR fallback
  combined        Gemini vision first, Tesseract OCR + Gemini text pass for weak fields

Provider errors (rate limits, timeouts) are reported apart from reading errors, and
accuracy is computed only over documents the provider answered (answered/total shown).

Needs: Tesseract binary (TESSERACT_CMD if not on PATH) and/or GEMINI_API_KEY (shell or .env).
Optional: GEMINI_MODEL (model id), GEMINI_PACE_SECONDS (pause between calls, default 4).
Full results, including model outputs, are written to eval_results/ (gitignored, never commit).

Usage: python -m scripts.eval_images
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.evaluation import EvalReport, ProviderFailure, run_messy_eval
from app.extraction import ExtractionResult
from app.privacy import redact_secrets

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "eval_results"
VARIANTS = ("clean", "degraded", "hard")
SCHEMES = ("land_acquisition", "disaster_relief")


def say(line: str = "") -> None:
    print(redact_secrets(line), flush=True)   # live progress, and never a key on screen


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
        return TesseractBaselineProvider(), None, None
    if system == "gemini":
        return GeminiProvider(), None, None
    # combined: Gemini first, Tesseract OCR fallback for weak fields, and Tesseract as the cross-check reader
    return GeminiProvider(), TesseractOcr(), TesseractBaselineProvider()


def progress_line(label: str, result: ExtractionResult) -> str:
    if result.status == "ok":
        return f"    {label:<28} read {len(result.fields)} fields"
    return f"    {label:<28} UNAVAILABLE ({result.error_kind})"


def error_text(p: ProviderFailure) -> str:
    """The provider's own message plus quota and retry delay, if the provider reported them."""
    d = p.details
    if not d:
        return p.message.splitlines()[0][:160] if p.message else ""
    text = f"HTTP {d.get('http_status', '?')}" + (f" {d['status']}" if d.get("status") else "")
    text += f": {d.get('message', '')}"
    if d.get("quota_id"):
        text += f" | quota {d['quota_id']} ({d.get('quota_metric', '')}, limit {d.get('quota_value', '?')})"
    if d.get("retry_delay_seconds") is not None:
        text += f" | retry in {d['retry_delay_seconds']:g}s"
    return text


def report_lines(system: str, r: EvalReport) -> list[str]:
    e, f = r.extraction, r.flags
    accuracy = "n/a" if e.accuracy is None else f"{e.accuracy:.3f}"
    kinds = Counter(p.kind for p in r.provider_errors)
    lines = [
        f"{system} / {r.scheme} / {r.variant}   model {r.model or 'none (no LLM)'}",
        f"  accuracy {accuracy}  ({e.correct}/{e.fields_answered} fields, answered {e.documents_answered}/"
        f"{e.documents_total} docs)",
        f"  accepted {e.accepted}   accepted WRONG {e.accepted_wrong}   routed to review {e.routed_to_review}",
        f"  reading errors: {e.reading_errors} (answered fields wrong or not found)",
        f"  cross-check fired {e.cross_check_fired} (on correct readings {e.cross_check_on_correct}, "
        f"on wrong readings {e.cross_check_on_wrong})",
        f"  provider errors: {len(r.provider_errors)}"
        + (f" ({', '.join(f'{k} x{n}' for k, n in sorted(kinds.items()))})" if kinds else "")
        + f"   -> {e.unavailable} fields unavailable, not scored",
    ]
    lines += [f"      {p.document}: {p.kind}: {error_text(p)}" for p in r.provider_errors]
    na = lambda v: "n/a" if v is None else f"{v:.3f}"
    lines.append(f"  flags precision {na(f.precision)} recall {na(f.recall)} "
                 f"(scored {f.cases_scored}/{f.cases_total} cases; unscored: "
                 + (", ".join(f"{c} {why}" for c, why in f.unscored.items()) or "none") + ")")
    return [redact_secrets(line) for line in lines]


def main() -> None:
    from app.env_file import load_env_file
    from app.providers.tesseract import tesseract_available
    loaded = load_env_file(ROOT / ".env")
    if loaded:
        say(f"Loaded from .env: {', '.join(loaded)}")   # names only
    say(f"Gemini model: {os.environ.get('GEMINI_MODEL') or 'default'}; "
        f"pace {os.environ.get('GEMINI_PACE_SECONDS') or 'default'} s")
    saved, summaries = {}, []
    for system, skip in plan_systems(tesseract_available(), bool(os.environ.get("GEMINI_API_KEY"))):
        if skip:
            summaries.append([f"{system}: SKIPPED: {skip}"])
            say(summaries[-1][0])
            continue
        provider, ocr, cross_check = _build(system)
        for scheme, variant in [(s, v) for s in SCHEMES for v in VARIANTS]:
            say(f"\n{system} / {scheme} / {variant} ...")
            report = run_messy_eval(provider=provider, ocr=ocr, variant=variant, cross_check=cross_check, scheme=scheme,
                                    on_document=lambda label, result: say(progress_line(label, result)))
            summaries.append(report_lines(system, report))
            for line in summaries[-1]:
                say(line)
            saved[f"{system}/{scheme}/{variant}"] = report.model_dump(mode="json")
    say("\n=== summary ===")
    for block in summaries:
        for line in block:
            say(line)
    if saved:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"images_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        out.write_text(json.dumps(redact_secrets(saved), indent=2), encoding="utf-8")
        say(f"\nFull rows written to {out} (gitignored)")


if __name__ == "__main__":
    main()
