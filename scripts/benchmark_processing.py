"""Processing-time benchmark over the synthetic set. A measurement script: no product code is changed.

For every synthetic case it times each stage and the total, per scheme:
  read       extraction of the case's document images (clean variant), where the case has images
  verify     the YAML verification checks (verification.verify_documents)
  assess     the eligibility rules (rules_engine.check_eligibility)
  calculate  the amount formulas (compensation.compute_compensation)
Reading uses real Tesseract (required). Gemini is used for reading only if a preflight passes: one call, no retries.
Otherwise the run is labelled "fallback provider" and Tesseract reads alone.

Usage: python -m scripts.benchmark_processing [--out docs/BENCHMARK.md]
Prints stage summaries only: never a key, a document's text or a tracking code.
"""
import argparse
import math
import os
import platform
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"
STAGES = ("read", "verify", "assess", "calculate", "total")


# --- pure helpers (tested) ------------------------------------------------------------------------------------------

def summarize(samples: list[float]) -> dict[str, Any]:
    """n, median, mean and the nearest-rank 90th percentile (the ceil(0.9 * n)-th smallest value)."""
    if not samples:
        return {"n": 0, "median": None, "mean": None, "p90": None}
    ordered = sorted(samples)
    return {"n": len(ordered), "median": float(statistics.median(ordered)), "mean": float(statistics.fmean(ordered)),
            "p90": float(ordered[math.ceil(0.9 * len(ordered)) - 1])}


def preflight(call: Optional[Callable[[], Any]]) -> tuple[bool, str]:
    """One live call, no retries. (True, "") if it answered, else (False, why)."""
    if call is None:
        return False, "Gemini not configured"
    try:
        call()
    except Exception as exc:   # any failure means the run uses the fallback provider
        return False, str(exc)[:200]
    return True, ""


def _cell(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}"


def render(meta: dict[str, Any], stats: dict[str, dict[str, dict[str, Any]]]) -> str:
    lines = [
        "# Processing-time benchmark",
        "",
        f"Run on {meta['date']} with `python -m scripts.benchmark_processing`. Times are in milliseconds.",
        "",
        f"- **Machine:** {meta['machine']}; Python {meta['python']}",
        f"- **Provider:** {meta['provider']}",
        f"- **Cases:** {meta['cases']} synthetic cases; {meta['documents']} document images read (clean variant)",
        "",
        "| Scheme | Stage | n | Median | Mean | 90th percentile |",
        "|---|---|---|---|---|---|",
    ]
    for scheme in sorted(stats):
        for stage in STAGES:
            s = stats[scheme].get(stage)
            if s is None:
                continue
            lines.append(f"| {scheme} | {stage} | {s['n']} | {_cell(s['median'])} | {_cell(s['mean'])} | {_cell(s['p90'])} |")
    lines += [
        "",
        "## What the stages are",
        "",
        "- **read:** extracting the fields of each document image the case has (the time per case is the sum over its",
        "  images). Only cases with an image file are counted; the others were seeded with fields already read.",
        "- **verify:** the scheme's YAML verification checks (name match, duplicates, recorded entries).",
        "- **assess:** the eligibility rules.",
        "- **calculate:** the amount formulas.",
        "- **total:** the sum of the stages measured for that case.",
        "",
        "## Limits",
        "",
        "- Synthetic documents only: invented cases and clean images, not real records or scans.",
        "- One machine, one run; times vary with the machine, its load and, for a live model, the network.",
        "- Software time only. It excludes human review time, the officer's decision, uploads, queueing and waiting",
        "  for the citizen.",
        "- Reading is measured on the clean image variant only; degraded and hard images take longer and are read",
        "  less reliably (see `docs/EVAL_RESULTS.md`).",
        "",
    ]
    return "\n".join(lines)


# --- measurement ----------------------------------------------------------------------------------------------------

def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _gemini_call() -> Optional[Callable[[], Any]]:
    """One generateContent call through the product client's single-attempt method (no retry loop)."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    from app.providers.gemini import API_BASE, GeminiClient
    client = GeminiClient()
    url = f"{API_BASE}/{client.model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    body = {"contents": [{"role": "user", "parts": [{"text": "Reply with the single word OK."}]}],
            "generationConfig": {"maxOutputTokens": 5, "temperature": 0}}
    return lambda: client._call_once(url, headers, body)


def _images(case_dir: Path) -> list[Path]:
    folder = case_dir / "images"
    return sorted(folder.glob("*_clean.png")) if folder.is_dir() else []


def measure(use_gemini: bool) -> tuple[dict[str, dict[str, dict[str, Any]]], int, int]:
    from app.case_model import CaseIn
    from app.compensation import compute_compensation
    from app.extraction import DocumentInput, Page, extract_facts
    from app.providers.tesseract import TesseractBaselineProvider, TesseractOcr
    from app.rules_engine import check_eligibility
    from app.rules_loader import RULES_DIR, load_scheme_by_name
    from app.verification import verify_documents

    provider: Any = TesseractBaselineProvider()
    if use_gemini:
        from app.providers.gemini import GeminiProvider
        provider = GeminiProvider()
    ocr, cross = TesseractOcr(), TesseractBaselineProvider()

    stats: dict[str, dict[str, dict[str, Any]]] = {}
    case_count = image_count = 0
    for scheme_dir in sorted(p for p in DATA.iterdir() if p.is_dir() and (RULES_DIR / f"{p.name}.yaml").is_file()):
        scheme = load_scheme_by_name(scheme_dir.name)
        docs = {d.id: d for d in scheme.required_documents}
        folders = sorted(scheme_dir.glob("case_*"))
        cases = [CaseIn.model_validate_json((f / "case.json").read_text(encoding="utf-8")) for f in folders]
        samples: dict[str, list[float]] = {stage: [] for stage in STAGES}
        for folder, case in zip(folders, cases):
            times: dict[str, float] = {}
            images = [p for p in _images(folder) if p.name.removesuffix("_clean.png") in docs]
            if images:
                start = time.perf_counter()
                for n, path in enumerate(images, start=1):
                    doc = docs[path.name.removesuffix("_clean.png")]
                    document = DocumentInput(document_id=f"{case.case_id}-{n}", doc_type=doc.id,
                                             pages=[Page(number=1, image_bytes=path.read_bytes(), media_type="image/png")])
                    extract_facts(document, doc.fields, scheme.confidence_threshold, provider, ocr, cross, doc.types)
                times["read"] = _ms(start)
                image_count += len(images)
            start = time.perf_counter()
            verification = verify_documents(scheme, case, cases)
            times["verify"] = _ms(start)
            start = time.perf_counter()
            check_eligibility(scheme, case, verification)
            times["assess"] = _ms(start)
            if scheme.compensation:
                start = time.perf_counter()
                compute_compensation(scheme, case)
                times["calculate"] = _ms(start)
            times["total"] = sum(times.values())
            for stage, value in times.items():
                samples[stage].append(value)
            case_count += 1
        stats[scheme_dir.name] = {stage: summarize(values) for stage, values in samples.items() if values}
        print(f"{scheme_dir.name}: {len(cases)} cases timed")
    return stats, case_count, image_count


def machine() -> str:
    """Operating system and processor only: no host name or user name."""
    cpu = platform.processor() or platform.machine()
    return f"{platform.system()} {platform.release()} ({platform.version()}), {cpu}, {os.cpu_count()} logical CPUs"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "BENCHMARK.md"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from app.env_file import load_env_file
    from app.providers.tesseract import tesseract_available
    load_env_file(ROOT / ".env")
    if not tesseract_available():
        sys.exit("Tesseract is required (install it or set TESSERACT_CMD).")
    ok, reason = preflight(_gemini_call())
    from app.providers.gemini import DEFAULT_MODEL
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    provider = (f"Gemini `{model}` reads (preflight passed), Tesseract for the OCR pass and the cross-check" if ok
                else f"fallback provider: Tesseract reads alone (Gemini preflight did not pass: {reason})")
    print("provider:", "gemini" if ok else "fallback provider")
    stats, cases, images = measure(ok)
    meta = {"date": date.today().isoformat(), "machine": machine(), "python": platform.python_version(),
            "provider": provider, "cases": cases, "documents": images}
    Path(args.out).write_text(render(meta, stats), encoding="utf-8")
    print("wrote", Path(args.out).relative_to(ROOT))


if __name__ == "__main__":
    main()
