"""Field extraction from documents: vision LLM first, OCR + text LLM as a fallback.

Extraction only reads; it never decides anything. Fields the scheme did not ask
for are dropped, missing fields are reported (never invented), and anything
below the confidence threshold stays flagged so the case routes to human review.
"""

import re
from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel

from app.cross_check import READERS_DISAGREE, readers_disagree

Mode = Literal["document", "ocr_text"]
Method = Literal["llm", "ocr_fallback"]


class Page(BaseModel):
    number: int
    text: Optional[str] = None          # synthetic/plain-text documents and OCR output
    image_bytes: Optional[bytes] = None
    media_type: Optional[str] = None    # e.g. image/png, application/pdf


class DocumentInput(BaseModel):
    document_id: str
    doc_type: str
    pages: list[Page]


class ExtractionRequest(BaseModel):
    document_id: str
    doc_type: str
    fields: list[str]
    pages: list[Page]
    mode: Mode


class ProviderField(BaseModel):
    name: str
    value: Any
    confidence: float
    page: Optional[int] = None


class OcrResult(BaseModel):
    text: str
    confidence: float


ErrorKind = Literal["rate_limited", "unavailable", "timeout", "network", "http_error",
                    "bad_response", "not_configured", "error"]
EXTRACTION_UNAVAILABLE_MESSAGE = "extraction unavailable, retry"


class ProviderError(RuntimeError):
    """The extraction provider failed (it read nothing). The document is marked
    extraction_unavailable and can be retried; this is not a low-confidence reading."""

    def __init__(self, message: str, kind: ErrorKind = "error", retryable: bool = False,
                 details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.retryable = retryable
        self.details: dict[str, Any] = details or {}   # e.g. http_status, quota_id, retry_delay_seconds


class ExtractionProvider(Protocol):
    name: str

    def extract(self, request: ExtractionRequest) -> list[ProviderField]: ...


class OcrEngine(Protocol):
    name: str

    def ocr(self, document_id: str, page: Page) -> OcrResult: ...


class ExtractedFieldOut(BaseModel):
    name: str
    value: Any
    confidence: float
    source_page: Optional[int]
    method: Method
    note: Optional[str] = None
    review_reason: Optional[str] = None   # set by the cross-check: goes to review whatever the confidence


class ExtractionResult(BaseModel):
    document_id: str
    doc_type: str
    fields: list[ExtractedFieldOut]
    low_confidence: list[str]
    missing: list[str]
    used_fallback: bool
    disagree: list[str] = []              # fields the cross-check reader read differently
    cross_check: Optional[str] = None     # the second reader's name, or why it could not run
    provider: str
    ocr_engine: Optional[str]
    status: Literal["ok", "extraction_unavailable"] = "ok"
    error: Optional[str] = None           # provider message (already scrubbed of keys by the provider)
    error_kind: Optional[ErrorKind] = None
    error_details: dict[str, Any] = {}    # structured provider error (http_status, quota_id, retry delay)
    retryable: bool = False



def _normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def values_match(a: Any, b: Any) -> bool:
    """Equal as numbers, or equal as text ignoring case and spacing."""
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return _normalise_text(a) == _normalise_text(b)


def _clean(fields: list[ProviderField], wanted: list[str]) -> dict[str, ProviderField]:
    out: dict[str, ProviderField] = {}
    for f in fields:
        if f.name not in wanted or f.value in (None, ""):
            continue
        conf = f.confidence if 0.0 <= f.confidence <= 1.0 else 0.0
        out[f.name] = f.model_copy(update={"confidence": conf})
    return out


def _from(f: ProviderField, method: Method, confidence: Optional[float] = None,
          value: Any = None, note: Optional[str] = None) -> ExtractedFieldOut:
    return ExtractedFieldOut(name=f.name, value=f.value if value is None else value,
                             confidence=f.confidence if confidence is None else confidence,
                             source_page=f.page, method=method, note=note)


def _ocr_pass(document: DocumentInput, fields: list[str], provider: ExtractionProvider,
              ocr: OcrEngine) -> dict[str, ProviderField]:
    results = [(p.number, ocr.ocr(document.document_id, p)) for p in document.pages]
    ocr_conf = min(r.confidence for _, r in results)
    pages = [Page(number=n, text=r.text) for n, r in results]
    request = ExtractionRequest(document_id=document.document_id, doc_type=document.doc_type,
                                fields=fields, pages=pages, mode="ocr_text")
    secondary = _clean(provider.extract(request), fields)
    # A text extraction is never more trustworthy than the OCR it read
    return {k: v.model_copy(update={"confidence": min(v.confidence, ocr_conf)}) for k, v in secondary.items()}


def _merge(name: str, primary: Optional[ProviderField], secondary: Optional[ProviderField],
           threshold: float) -> Optional[ExtractedFieldOut]:
    if secondary is not None and secondary.confidence >= threshold:
        if primary is None:
            return _from(secondary, "ocr_fallback")
        if values_match(primary.value, secondary.value):
            return _from(secondary, "ocr_fallback", value=primary.value)
        return _from(primary, "llm", note=f"OCR fallback read {secondary.value!r}; values disagree")
    if primary is not None:
        return _from(primary, "llm")
    if secondary is not None:
        return _from(secondary, "ocr_fallback")
    return None


def _cross_check(request: ExtractionRequest, out: list[ExtractedFieldOut], reader: ExtractionProvider,
                 types: dict[str, str]) -> tuple[str, list[str]]:
    """A second reader reads the same document; fields it reads differently go to review (see app.cross_check)."""
    try:
        second = _clean(reader.extract(request), request.fields)
    except ProviderError as exc:
        return f"{reader.name} unavailable ({exc.kind})", []
    disagree = []
    for f in out:
        other = second.get(f.name)
        if other is None:                                  # the second reader has nothing to say: no check
            continue
        if readers_disagree(types.get(f.name, "text"), f.value, other.value):
            f.review_reason = READERS_DISAGREE
            f.note = (f"{f.note}; " if f.note else "") + f"{reader.name} read {other.value!r}"
            disagree.append(f.name)
    return reader.name, disagree


def extract_facts(document: DocumentInput, fields: list[str], threshold: float,
                  provider: ExtractionProvider, ocr: Optional[OcrEngine] = None,
                  cross_check: Optional[ExtractionProvider] = None,
                  types: Optional[dict[str, str]] = None) -> ExtractionResult:
    base = {"document_id": document.document_id, "doc_type": document.doc_type,
            "provider": provider.name, "ocr_engine": ocr.name if ocr else None}
    request = ExtractionRequest(document_id=document.document_id, doc_type=document.doc_type,
                                fields=fields, pages=document.pages, mode="document")
    try:
        primary = _clean(provider.extract(request), fields)
        weak = [f for f in fields if f not in primary or primary[f].confidence < threshold]
        secondary = _ocr_pass(document, weak, provider, ocr) if (weak and ocr) else {}
    except ProviderError as exc:
        # Nothing was read: not low confidence, not missing. The document can be retried.
        return ExtractionResult(fields=[], low_confidence=[], missing=[], used_fallback=False,
                                status="extraction_unavailable", error=str(exc), error_kind=exc.kind,
                                error_details=exc.details, retryable=exc.retryable, **base)

    out = [m for f in fields if (m := _merge(f, primary.get(f), secondary.get(f), threshold))]
    checked, disagree = _cross_check(request, out, cross_check, types or {}) if cross_check else (None, [])
    return ExtractionResult(
        fields=out,
        low_confidence=[f.name for f in out if f.confidence < threshold],
        missing=[f for f in fields if f not in {o.name for o in out}],
        used_fallback=bool(weak and ocr),
        disagree=disagree,
        cross_check=checked,
        **base,
    )
