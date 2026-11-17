"""Self-check before applying: a dry run of the scheme's own eligibility conditions on answers to
the questions its YAML declares. Nothing is created or stored. The result is a guide, not a decision."""

from datetime import date
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.case_model import CaseIn, DocumentIn, FieldValue
from app.extraction import (
    DocumentInput, ExtractionProvider, ExtractionResult, OcrEngine, Page, extract_facts,
)
from app.facts import CaseFacts, build_facts
from app.privacy import mask_identifiers
from app.providers.tesseract import TesseractBaselineProvider, TesseractOcr, tesseract_available
from app.rules_engine import evaluate_when
from app.rules_loader import RequiredDocument, Scheme, load_scheme_by_name, scheme_names
from app.verification import entry_is_empty, has_non_name_characters

GUIDE_LABEL = "This is a guide, not a decision. Only an officer decides."
PRECHECK_DISCLAIMER = "A quick check, not an application. An officer reviews every document."
PRECHECK_LANGUAGE_NOTE = "Document pre-check feedback is in English."
PRECHECK_NOTHING_SAVED_NOTE = (
    "Nothing is saved: your file and its text are checked in memory and never stored."
)
EXCLUDED_PRECHECK_DOCS = {"application"}  # clerk-typed intake form, not a citizen upload
READABLE_VALUE_FIELDS = {"name", "area", "area_unit"}

_PRECHECK_DECISION = re.compile(
    r"\b(?:in)?eligible\b|\b(?:approved|rejected|accepted|sanction(?:ed|s)?|entitled|entitlement|guarantee[ds]?)\b",
    re.IGNORECASE,
)
_PRECHECK_RUPEE = re.compile(r"₹|\brs\.?(?=\s|\d|$)|\brupees?\b|\binr\b", re.IGNORECASE)
_PRECHECK_SNAKE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")

Outcome = Literal["likely_eligible", "likely_not_eligible", "need_more_information"]
ReadableCategory = Literal["yes", "partly", "no"]
FieldReadStatus = Literal["found", "could not read"]



class NoSelfCheck(ValueError):
    """The scheme declares no self-check questions."""


class RuleGuide(BaseModel):
    rule_id: str
    status: Literal["pass", "fail", "needs_review"]
    message: str


class SelfCheckResult(BaseModel):
    scheme: str
    outcome: Outcome
    rules: list[RuleGuide]
    documents_to_bring: list[str]
    checked_when_you_apply: list[str]   # cross-document checks that need the real documents
    guide_label: str = GUIDE_LABEL
    rules_version: str


def _hypothetical_case(scheme: Scheme, answers: dict[str, str]) -> CaseIn:
    documents: dict[str, DocumentIn] = {}
    for ref, value in answers.items():
        doc_id, field = ref.split(".", 1)
        documents.setdefault(doc_id, DocumentIn()).fields[field] = FieldValue(value=value, confidence=1.0)
    return CaseIn(case_id="SELF-CHECK", scheme=scheme.scheme, reference_date=date.today(), documents=documents)


def self_check(scheme: Scheme, answers: dict[str, str]) -> SelfCheckResult:
    if scheme.self_check is None:
        raise NoSelfCheck(f"Scheme {scheme.scheme} has no self-check")
    asked = {q.field for q in scheme.self_check.questions}
    unknown = sorted(set(answers) - asked)
    if unknown:
        raise ValueError(f"{unknown} is not a self-check question")
    given = {k: v for k, v in answers.items() if str(v).strip()}
    facts = build_facts(scheme, _hypothetical_case(scheme, given))
    rules = {r.id: r for r in scheme.eligibility_rules}
    guides: list[RuleGuide] = []
    for rule_id in scheme.self_check.rules:
        rule = rules[rule_id]
        status, reason = evaluate_when(rule.when, facts)
        unanswered = [q for q in sorted(asked) if q in rule.when and q not in given]
        if status == "needs_review":
            message = f"Please answer: {', '.join(unanswered)}" if unanswered else reason   # reason names the field
        else:
            message = rule.fail_reason if status == "fail" else "Looks fine from your answers."
        guides.append(RuleGuide(rule_id=rule_id, status=status, message=message))
    statuses = {g.status for g in guides}
    outcome: Outcome = ("likely_not_eligible" if "fail" in statuses
                        else "need_more_information" if "needs_review" in statuses else "likely_eligible")
    return SelfCheckResult(scheme=scheme.scheme, outcome=outcome, rules=guides,
                           documents_to_bring=scheme.document_ids,
                           checked_when_you_apply=[c.id for c in scheme.verification_checks],
                           rules_version=scheme.version)


def public_questions(scheme: Scheme) -> Optional[dict]:
    if scheme.self_check is None:
        return None
    types = {f"{d.id}.{f}": t for d in scheme.required_documents for f, t in d.types.items()}
    return {"scheme": scheme.scheme, "labels": scheme.labels, "guide_label": GUIDE_LABEL,
            "documents": scheme.document_ids, "terms": scheme.terms,
            "questions": [{"field": q.field, "prompt": q.prompt, "type": types[q.field], "choices": q.choices}
                          for q in scheme.self_check.questions]}


# --- citizen document pre-check (in memory, zero storage) ------------------------------------------------

class PrecheckField(BaseModel):
    label: str
    status: FieldReadStatus
    what_we_read: Optional[str] = None


class PrecheckResult(BaseModel):
    scheme_label: str
    document_label: str
    readable: ReadableCategory
    fields: list[PrecheckField]
    issues: list[str]
    next_steps: list[str]
    used_fallback: bool
    disclaimer: str = PRECHECK_DISCLAIMER
    language: Literal["en"] = "en"
    language_note: str = PRECHECK_LANGUAGE_NOTE
    nothing_saved_note: str = PRECHECK_NOTHING_SAVED_NOTE


def _term(scheme: Scheme, key: str, doc_id: Optional[str] = None) -> str:
    label = (scheme.terms.get(f"{doc_id}.{key}") if doc_id else None) or scheme.terms.get(key)
    if label:
        return label.replace("_", " ")
    plain = key.split(".")[-1].replace("_", " ").strip()
    return plain[:1].upper() + plain[1:] if plain else key


def precheck_documents(scheme: Scheme) -> list[RequiredDocument]:
    """Citizen-uploadable documents for a scheme (excludes clerk-typed intake forms like `application`)."""
    return [d for d in scheme.required_documents if d.id not in EXCLUDED_PRECHECK_DOCS]


def public_precheck_schemes() -> list[dict[str, Any]]:
    out = []
    for name in scheme_names():
        s = load_scheme_by_name(name)
        out.append({
            "scheme": s.scheme,
            "title": s.labels["title"],
            "documents": [{"id": d.id, "label": _term(s, d.id)} for d in precheck_documents(s)],
            "disclaimer": PRECHECK_DISCLAIMER,
            "language_note": PRECHECK_LANGUAGE_NOTE,
            "nothing_saved_note": PRECHECK_NOTHING_SAVED_NOTE,
        })
    return out


def precheck_guard_problems(strings: list[str]) -> list[str]:
    """Reject decision words, rupee mentions/symbols, and snake_case identifiers in user-facing strings."""
    problems: list[str] = []
    for text in strings:
        if not text:
            continue
        for m in _PRECHECK_DECISION.finditer(text):
            problems.append(f"decision word {m.group(0).lower()!r}")
        if _PRECHECK_RUPEE.search(text):
            problems.append("mentions rupees")
        for m in _PRECHECK_SNAKE.finditer(text):
            problems.append(f"snake_case token {m.group(0)!r}")
    return problems




def _result_strings(result: PrecheckResult) -> list[str]:
    strings = [
        result.scheme_label,
        result.document_label,
        result.readable,
        result.disclaimer,
        result.language_note,
        result.nothing_saved_note,
        *result.issues,
        *result.next_steps,
    ]
    for f in result.fields:
        strings.extend([f.label, f.status])
        if f.what_we_read is not None:
            strings.append(f.what_we_read)
    return strings


def _format_what_we_read(field_name: str, doc_facts: dict[str, Any],
                         invalid_refs: set[str], doc_id: str) -> Optional[str]:
    if field_name not in READABLE_VALUE_FIELDS or field_name not in doc_facts:
        return None
    if field_name == "name":
        return str(mask_identifiers(str(doc_facts["name"]).strip()))
    if field_name == "area":
        if f"{doc_id}.area_sqm" in invalid_refs:
            return None
        val = doc_facts["area"]
        num = f"{float(val):g}" if isinstance(val, (int, float)) else str(val).strip()
        unit = str(doc_facts.get("area_unit", "")).strip()
        return str(mask_identifiers(f"{num} {unit}".strip()))
    if field_name == "area_unit":
        return str(mask_identifiers(str(doc_facts["area_unit"]).strip()))
    return None


def _build_precheck_result(scheme: Scheme, req_doc: RequiredDocument, extraction: ExtractionResult,
                           reference_date: date, used_fallback: bool,
                           redact_guarded_values: bool = False) -> PrecheckResult:
    doc_in = DocumentIn(
        fields={
            f.name: FieldValue(
                value=f.value,
                confidence=f.confidence,
                page=f.source_page,
                review_reason=f.review_reason,
            )
            for f in extraction.fields
        },
        extraction_unavailable=(extraction.status == "extraction_unavailable"),
    )
    case_in = CaseIn(
        case_id="PRECHECK",
        scheme=scheme.scheme,
        reference_date=reference_date,
        documents={req_doc.id: doc_in},
    )
    facts: CaseFacts = build_facts(scheme, case_in)
    doc_facts: dict[str, Any] = dict(facts.names.get(req_doc.id, {}))
    invalid_refs = set(facts.invalid.keys())
    doc_label = _term(scheme, req_doc.id)

    # Check damaged name characters on present name field
    damaged_name = False
    if "name" in doc_facts and has_non_name_characters(str(doc_facts["name"])):
        damaged_name = True
        del doc_facts["name"]

    # Derived area_sqm implausibility invalidates area
    area_implausible = f"{req_doc.id}.area_sqm" in invalid_refs
    if area_implausible and "area" in doc_facts:
        del doc_facts["area"]

    required_fields = [f for f in req_doc.fields if f not in req_doc.may_be_blank]
    field_items: list[PrecheckField] = []
    unreadable_labels: list[str] = []
    implausible_labels: list[str] = []

    for fname in required_fields:
        flabel = _term(scheme, fname, req_doc.id)
        ref = f"{req_doc.id}.{fname}"
        why_invalid = facts.invalid.get(ref, "")
        if fname == "area" and area_implausible:
            why_invalid = facts.invalid.get(f"{req_doc.id}.area_sqm", "outside the plausible range")
        is_found = fname in doc_facts
        what_we_read = _format_what_we_read(fname, doc_facts, invalid_refs, req_doc.id) if is_found else None
        if redact_guarded_values and what_we_read is not None and precheck_guard_problems([what_we_read]):
            what_we_read = None
            is_found = False
        if is_found:
            field_items.append(PrecheckField(label=flabel, status="found", what_we_read=what_we_read))
        else:
            field_items.append(PrecheckField(label=flabel, status="could not read", what_we_read=None))
            if "outside the plausible range" in why_invalid:
                implausible_labels.append(flabel)
            else:
                unreadable_labels.append(flabel)

    issues: list[str] = []
    next_steps: list[str] = []
    found_count = sum(1 for f in field_items if f.status == "found")

    if found_count == 0:
        issues.append(f"We could not read the required details on this {doc_label}.")
        next_steps.append(
            f"Try a clearer, well-lit photo or scan of the {doc_label}, or bring the original to the office."
        )
    else:
        if damaged_name:
            issues.append("Name contains unclear characters, digits or symbols.")
        if implausible_labels:
            issues.append(
                f"{', '.join(implausible_labels)} on this {doc_label} looks outside the expected range "
                "or could not be read clearly."
            )
        if unreadable_labels:
            issues.append(f"Could not read clearly: {', '.join(unreadable_labels)}.")
        if damaged_name or implausible_labels or unreadable_labels:
            next_steps.append(f"Bring a clearer copy or the original {doc_label} so every detail can be read.")

    # Check document validity / age
    validity_status = facts.validity.get(req_doc.id)
    if validity_status == "expired" and req_doc.validity:
        if req_doc.validity.max_age_days is not None:
            days = req_doc.validity.max_age_days
            issues.append(f"This {doc_label} is older than {days} days.")
            next_steps.append(f"Bring a current {doc_label} issued within the last {days} days.")
        else:
            issues.append(f"This {doc_label} has passed its expiry date.")
            next_steps.append(f"Bring a current, unexpired {doc_label}.")

    # Check single-document recorded_entry checks (e.g. tenant or mundkar entry on ownership_record)
    for check in scheme.verification_checks:
        if check.builtin != "recorded_entry":
            continue
        doc_entries = [e.split(".", 1)[1] for e in check.entries if e.startswith(f"{req_doc.id}.")]
        if not doc_entries:
            continue
        has_entry = any(
            name in doc_facts and not entry_is_empty(doc_facts[name], check.empty_values)
            for name in doc_entries
        )
        unreadable_entry = any(
            f"{req_doc.id}.{name}" in facts.low_confidence
            or f"{req_doc.id}.{name}" in facts.invalid
            or f"{req_doc.id}.{name}" in facts.disagree
            for name in doc_entries
        )
        if has_entry:
            issues.append(
                "A tenant or mundkar entry is recorded on this document; an officer will verify rights during review."
            )
            next_steps.append("Bring any supporting order or document for the recorded entry when you apply.")
        elif unreadable_entry:
            issues.append("Tenant or mundkar entry column could not be read clearly.")
            next_steps.append(f"Bring a clearer copy or the original {doc_label}.")

    if found_count == 0:
        readable: ReadableCategory = "no"
    elif found_count == len(field_items) and not issues:
        readable = "yes"
        next_steps.append(
            f"Bring the original {doc_label} along with the other required documents when you apply."
        )
    else:
        readable = "partly"

    return PrecheckResult(
        scheme_label=scheme.labels["title"].replace("_", " "),
        document_label=doc_label,
        readable=readable,
        fields=field_items,
        issues=issues,
        next_steps=next_steps,
        used_fallback=used_fallback,
    )


def _ocr_only_extraction(doc_input: DocumentInput, req_doc: RequiredDocument, threshold: float,
                         ocr: Optional[OcrEngine],
                         fallback_provider: Optional[ExtractionProvider]) -> ExtractionResult:
    try:
        engine = ocr or (TesseractOcr() if (doc_input.pages and doc_input.pages[0].image_bytes is None) or tesseract_available() else None)
        fb = fallback_provider or (TesseractBaselineProvider(engine) if engine else None)
        if fb is None:
            return ExtractionResult(
                document_id=doc_input.document_id, doc_type=doc_input.doc_type,
                fields=[], low_confidence=[], missing=list(req_doc.fields),
                used_fallback=True, provider="ocr_only", ocr_engine=None,
            )
        res = extract_facts(doc_input, req_doc.fields, threshold, fb, ocr=None, cross_check=None, types=req_doc.types)
        return res.model_copy(update={"used_fallback": True})
    except Exception:
        return ExtractionResult(
            document_id=doc_input.document_id, doc_type=doc_input.doc_type,
            fields=[], low_confidence=[], missing=list(req_doc.fields),
            used_fallback=True, provider="ocr_only", ocr_engine=None,
        )


def precheck_document(
    scheme: Scheme,
    doc_type: str,
    page: Page,
    reference_date: date,
    provider: Optional[ExtractionProvider] = None,
    ocr: Optional[OcrEngine] = None,
    cross_check: Optional[ExtractionProvider] = None,
    fallback_provider: Optional[ExtractionProvider] = None,
    allow_provider: bool = True,
) -> PrecheckResult:
    allowed_docs = {d.id: d for d in precheck_documents(scheme)}
    if doc_type not in allowed_docs:
        raise ValueError(f"Unsupported pre-check document type {doc_type!r} for scheme {scheme.scheme}")
    req_doc = allowed_docs[doc_type]
    doc_input = DocumentInput(document_id="precheck", doc_type=doc_type, pages=[page])

    if provider is not None and allow_provider:
        ocr_engine = ocr or (TesseractOcr() if (page.image_bytes is None or tesseract_available()) else None)
        extraction = extract_facts(
            doc_input, req_doc.fields, scheme.confidence_threshold,
            provider, ocr=ocr_engine, cross_check=cross_check, types=req_doc.types,
        )
        if extraction.status == "ok":
            candidate = _build_precheck_result(
                scheme, req_doc, extraction, reference_date,
                used_fallback=extraction.used_fallback, redact_guarded_values=False,
            )
            raw_values = [str(f.value) for f in extraction.fields if f.value is not None]
            if not precheck_guard_problems(raw_values + _result_strings(candidate)):
                return candidate


    # Fallback path: provider unavailable, daily cap reached, provider failed, or guard rejected output
    fb_extraction = _ocr_only_extraction(doc_input, req_doc, scheme.confidence_threshold, ocr, fallback_provider)
    result = _build_precheck_result(
        scheme, req_doc, fb_extraction, reference_date,
        used_fallback=True, redact_guarded_values=True,
    )
    # Final defense-in-depth check on fallback output
    if precheck_guard_problems(_result_strings(result)):
        cleaned_fields = [
            f.model_copy(update={"what_we_read": None, "status": "could not read"})
            if f.what_we_read and precheck_guard_problems([f.what_we_read]) else f
            for f in result.fields
        ]
        result = result.model_copy(update={"fields": cleaned_fields})
    return result

