"""Measures extraction accuracy and verification flag precision/recall on the messy set.

With no provider given, each document uses a FakeProvider that replays its recorded
response. Those extraction numbers describe the recordings, not a model. Flag
precision/recall measures the deterministic verification code on what was extracted.
"""

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from app.case_model import CaseIn
from app.case_store import seed_case
from app.extraction import ExtractionProvider, OcrEngine, ProviderField, values_match
from app.models import Document, make_engine, make_session
from app.providers.fake import FakeOcr, FakeProvider
from app.rules_loader import load_scheme_by_name
from app.tools import extract_document, verify_documents

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"


class FieldRow(BaseModel):
    case: str
    doc_type: str
    field: str
    truth: Any
    value: Any
    confidence: Optional[float]
    method: Optional[str]
    accepted: bool        # at or above the confidence threshold, so the tools will use it
    correct: bool


class ExtractionSummary(BaseModel):
    rows: list[FieldRow]
    total: int
    accepted: int
    accepted_correct: int
    accepted_wrong: int   # the dangerous number: confidently wrong
    routed_to_review: int


class FlagSummary(BaseModel):
    per_case: dict[str, dict[str, list[str]]]
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    precision: float
    recall: float


class EvalReport(BaseModel):
    providers: set[str]
    extraction: ExtractionSummary
    flags: FlagSummary


def _as_fields(items: list[dict]) -> list[ProviderField]:
    return [ProviderField(**i) for i in items]


def _fake_for(doc_id: str, fixture: dict) -> tuple[FakeProvider, Optional[FakeOcr]]:
    provider = FakeProvider({(doc_id, "document"): _as_fields(fixture["document"]),
                             (doc_id, "ocr_text"): _as_fields(fixture["ocr_text"])})
    ocr = FakeOcr({doc_id: (fixture["ocr"]["text"], fixture["ocr"]["confidence"])}) if fixture["ocr"] else None
    return provider, ocr


def _rows(case: str, doc_type: str, truth: dict, result, threshold: float) -> list[FieldRow]:
    got = {f.name: f for f in result.fields}
    rows = []
    for name, true_value in truth.items():
        f = got.get(name)
        rows.append(FieldRow(case=case, doc_type=doc_type, field=name, truth=true_value,
                             value=f.value if f else None, confidence=f.confidence if f else None,
                             method=f.method if f else None,
                             accepted=bool(f and f.confidence >= threshold),
                             correct=bool(f and values_match(f.value, true_value))))
    return rows


def _flag_summary(per_case: dict[str, dict[str, list[str]]]) -> FlagSummary:
    tp, fp, fn = [], [], []
    for case_id, sets in per_case.items():
        expected, actual = set(sets["expected"]), set(sets["actual"])
        tp += [f"{case_id}:{k}" for k in sorted(expected & actual)]
        fp += [f"{case_id}:{k}" for k in sorted(actual - expected)]
        fn += [f"{case_id}:{k}" for k in sorted(expected - actual)]
    precision = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 1.0
    recall = len(tp) / (len(tp) + len(fn)) if (tp or fn) else 1.0
    return FlagSummary(per_case=per_case, true_positives=tp, false_positives=fp, false_negatives=fn,
                       precision=round(precision, 3), recall=round(recall, 3))


def run_messy_eval(provider: Optional[ExtractionProvider] = None, ocr: Optional[OcrEngine] = None) -> EvalReport:
    """provider=None replays recorded fake responses; pass a real provider to measure a model."""
    labels = json.loads((SET_DIR / "messy_labels.json").read_text(encoding="utf-8"))
    threshold = load_scheme_by_name("land_acquisition").confidence_threshold
    rows: list[FieldRow] = []
    providers: set[str] = set()

    with make_session(make_engine("sqlite://")) as session:
        for folder in sorted(SET_DIR.glob("case_*")):
            seed_case(session, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))

        for item in labels["documents"]:
            folder = SET_DIR / item["case"]
            case_id = json.loads((folder / "case.json").read_text(encoding="utf-8"))["case_id"]
            doc = Document(case_id=case_id, doc_type=item["doc_type"],
                           file_path=str(folder / "documents" / f"{item['doc_type']}.txt"))
            session.add(doc)
            session.commit()
            if provider is None:
                fixture = json.loads((folder / "fake" / f"{item['doc_type']}.json").read_text(encoding="utf-8"))
                doc_provider, doc_ocr = _fake_for(str(doc.id), fixture)
            else:
                doc_provider, doc_ocr = provider, ocr
            providers.add(doc_provider.name)
            result = extract_document(session, doc.id, doc_provider, doc_ocr, actor="eval")
            rows += _rows(item["case"], item["doc_type"], item["truth"], result, threshold)

        per_case = {}
        for case_id, expected in labels["expected_flags"].items():
            actual = sorted({f.kind for f in verify_documents(session, case_id, actor="eval").flags})
            per_case[case_id] = {"expected": sorted(expected), "actual": actual}

    accepted = [r for r in rows if r.accepted]
    extraction = ExtractionSummary(
        rows=rows, total=len(rows), accepted=len(accepted),
        accepted_correct=sum(r.correct for r in accepted),
        accepted_wrong=sum(not r.correct for r in accepted),
        routed_to_review=len(rows) - len(accepted),
    )
    return EvalReport(providers=providers, extraction=extraction, flags=_flag_summary(per_case))
