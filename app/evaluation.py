"""Measures extraction accuracy and verification flag precision/recall on the messy set.

With no provider given, each document uses a FakeProvider that replays its recorded
response. Those extraction numbers describe the recordings, not a model. Flag
precision/recall measures the deterministic verification code on what was extracted.

Provider failures (rate limits, timeouts) are counted apart from reading errors:
accuracy is computed only over documents the provider actually answered, and flags
only over cases whose labelled documents were all answered.
"""

import json
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel

from app.case_model import CaseIn
from app.case_store import seed_case
from app.extraction import ExtractionProvider, ExtractionResult, OcrEngine, ProviderField, values_match
from app.models import Document, make_engine, make_session
from app.providers.fake import FakeOcr, FakeProvider
from app.rules_loader import load_scheme_by_name
from app.tools import extract_document, verify_documents
from app.units import UnknownUnit, to_sqm

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
Variant = Literal["text", "clean", "degraded"]
OnDocument = Callable[[str, ExtractionResult], None]


class FieldRow(BaseModel):
    case: str
    doc_type: str
    field: str
    truth: Any
    value: Any
    confidence: Optional[float]
    method: Optional[str]
    answered: bool        # False when the provider failed on this document (nothing was read)
    accepted: bool        # at or above the confidence threshold, so the tools will use it
    correct: bool


class ProviderFailure(BaseModel):
    document: str         # e.g. case_02.identity_proof
    kind: str             # error class: rate_limited, unavailable, timeout, ...
    message: str
    details: dict[str, Any] = {}   # provider's structured error: quota id/metric, retry delay, http status


class ExtractionSummary(BaseModel):
    rows: list[FieldRow]
    total: int                 # all labelled fields
    documents_total: int
    documents_answered: int    # the provider returned a reading (possibly empty)
    fields_answered: int       # labelled fields on answered documents
    unavailable: int           # labelled fields on documents the provider failed on
    accepted: int
    accepted_correct: int
    accepted_wrong: int        # the dangerous number: confidently wrong
    routed_to_review: int      # answered but below threshold or not found
    reading_errors: int        # answered fields that are wrong or missing
    correct: int               # value right, whatever its confidence
    accuracy: Optional[float]  # correct / fields_answered; None when nothing was answered


class FlagSummary(BaseModel):
    cases_total: int
    cases_scored: int          # cases with at least one labelled document, all of them answered
    unscored: dict[str, str]   # case id -> why it was not scored
    per_case: dict[str, dict[str, list[str]]]
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    precision: Optional[float]   # None when no case was scored
    recall: Optional[float]


class EvalReport(BaseModel):
    variant: Variant
    providers: set[str]
    model: Optional[str]                  # e.g. the Gemini model id; None for recorded fakes / no LLM
    provider_errors: list[ProviderFailure]
    extraction: ExtractionSummary
    flags: FlagSummary


def _as_fields(items: list[dict]) -> list[ProviderField]:
    return [ProviderField(**i) for i in items]


def _fake_for(doc_id: str, fixture: dict) -> tuple[FakeProvider, Optional[FakeOcr]]:
    provider = FakeProvider({(doc_id, "document"): _as_fields(fixture["document"]),
                             (doc_id, "ocr_text"): _as_fields(fixture["ocr_text"])})
    ocr = FakeOcr({doc_id: (fixture["ocr"]["text"], fixture["ocr"]["confidence"])}) if fixture["ocr"] else None
    return provider, ocr


def field_matches(field: str, got: Any, truth: Any) -> bool:
    """Compare an extracted value with the truth label; units compare by conversion factor."""
    if got is None:
        return False
    if field == "area_unit":
        try:
            return abs(to_sqm(1, str(got)) - to_sqm(1, str(truth))) < 1e-9
        except UnknownUnit:
            return False
    return values_match(got, truth)


def _rows(case: str, doc_type: str, truth: dict, result: ExtractionResult, threshold: float) -> list[FieldRow]:
    got = {f.name: f for f in result.fields}
    answered = result.status == "ok"
    rows = []
    for name, true_value in truth.items():
        f = got.get(name)
        rows.append(FieldRow(case=case, doc_type=doc_type, field=name, truth=true_value,
                             value=f.value if f else None, confidence=f.confidence if f else None,
                             method=f.method if f else None, answered=answered,
                             accepted=bool(f and f.confidence >= threshold),
                             correct=bool(f and field_matches(name, f.value, true_value))))
    return rows


def scoring_status(labelled: int, answered: int) -> Optional[str]:
    """None if a case's flags can be scored, else the reason. Zero documents is never 'fully answered'."""
    if labelled == 0:
        return "no labelled documents"
    if answered < labelled:
        return f"{labelled - answered} of {labelled} labelled documents unanswered"
    return None


def _flag_summary(per_case: dict[str, dict[str, list[str]]], cases_total: int,
                  unscored: dict[str, str]) -> FlagSummary:
    tp, fp, fn = [], [], []
    for case_id, sets in per_case.items():
        expected, actual = set(sets["expected"]), set(sets["actual"])
        tp += [f"{case_id}:{k}" for k in sorted(expected & actual)]
        fp += [f"{case_id}:{k}" for k in sorted(actual - expected)]
        fn += [f"{case_id}:{k}" for k in sorted(expected - actual)]
    precision = recall = None
    if per_case:   # only answered documents can back a score
        precision = round(len(tp) / (len(tp) + len(fp)), 3) if (tp or fp) else 1.0
        recall = round(len(tp) / (len(tp) + len(fn)), 3) if (tp or fn) else 1.0
    return FlagSummary(cases_total=cases_total, cases_scored=len(per_case), unscored=unscored,
                       per_case=per_case, true_positives=tp, false_positives=fp, false_negatives=fn,
                       precision=precision, recall=recall)


def _summary(rows: list[FieldRow], documents_total: int, documents_answered: int) -> ExtractionSummary:
    answered = [r for r in rows if r.answered]
    accepted = [r for r in answered if r.accepted]
    correct = sum(r.correct for r in answered)
    return ExtractionSummary(
        rows=rows, total=len(rows), documents_total=documents_total, documents_answered=documents_answered,
        fields_answered=len(answered), unavailable=len(rows) - len(answered), accepted=len(accepted),
        accepted_correct=sum(r.correct for r in accepted), accepted_wrong=sum(not r.correct for r in accepted),
        routed_to_review=len(answered) - len(accepted), reading_errors=len(answered) - correct, correct=correct,
        accuracy=round(correct / len(answered), 3) if answered else None,
    )


def run_messy_eval(provider: Optional[ExtractionProvider] = None, ocr: Optional[OcrEngine] = None,
                   variant: Variant = "text", on_document: Optional[OnDocument] = None) -> EvalReport:
    """variant="text" reads documents/*.txt; "clean"/"degraded" read the rendered images.

    provider=None replays recorded fake responses (text only); pass a real provider to measure it.
    on_document(label, result) is called after each document, for live progress.
    """
    if variant != "text" and provider is None:
        raise ValueError("Image variants need a real provider; recorded fakes only cover text documents")
    labels = json.loads((SET_DIR / "messy_labels.json").read_text(encoding="utf-8"))
    threshold = load_scheme_by_name("land_acquisition").confidence_threshold
    rows: list[FieldRow] = []
    providers: set[str] = set()
    failures: list[ProviderFailure] = []
    labelled: dict[str, int] = {}
    answered: dict[str, int] = {}

    with make_session(make_engine("sqlite://")) as session:
        for folder in sorted(SET_DIR.glob("case_*")):
            seed_case(session, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))

        for item in labels["documents"]:
            folder = SET_DIR / item["case"]
            case_id = json.loads((folder / "case.json").read_text(encoding="utf-8"))["case_id"]
            labelled[case_id] = labelled.get(case_id, 0) + 1
            source = (folder / "documents" / f"{item['doc_type']}.txt" if variant == "text"
                      else folder / "images" / f"{item['doc_type']}_{variant}.png")
            doc = Document(case_id=case_id, doc_type=item["doc_type"], file_path=str(source))
            session.add(doc)
            session.commit()
            if provider is None:
                fixture = json.loads((folder / "fake" / f"{item['doc_type']}.json").read_text(encoding="utf-8"))
                doc_provider, doc_ocr = _fake_for(str(doc.id), fixture)
            else:
                doc_provider, doc_ocr = provider, ocr
            providers.add(doc_provider.name)
            result = extract_document(session, doc.id, doc_provider, doc_ocr, actor="eval")
            label = f"{item['case']}.{item['doc_type']}"
            if result.status != "ok":
                failures.append(ProviderFailure(document=label, kind=result.error_kind or "error",
                                                message=result.error or "", details=result.error_details))
            else:
                answered[case_id] = answered.get(case_id, 0) + 1
            if on_document:
                on_document(label, result)
            rows += _rows(item["case"], item["doc_type"], item["truth"], result, threshold)

        per_case, unscored = {}, {}
        for case_id, expected in labels["expected_flags"].items():
            reason = scoring_status(labelled.get(case_id, 0), answered.get(case_id, 0))
            if reason:
                unscored[case_id] = reason   # a provider failure says nothing about the verification code
                continue
            actual = sorted({f.kind for f in verify_documents(session, case_id, actor="eval").flags})
            per_case[case_id] = {"expected": sorted(expected), "actual": actual}

    documents_total = len(labels["documents"])
    extraction = _summary(rows, documents_total, documents_total - len(failures))
    return EvalReport(variant=variant, providers=providers, model=getattr(provider, "model", None),
                      provider_errors=failures, extraction=extraction,
                      flags=_flag_summary(per_case, len(labels["expected_flags"]), unscored))
