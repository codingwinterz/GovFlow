"""Deficiency notice: the documents a citizen must bring, built from the case's open problems that the citizen
can fix. Fixed templates (the existing translation files) filled with YAML labels; no LLM writes any of it.
It never approves, rejects or computes anything.

Citizen remedies, by source:
  missing document              -> missing        ("bring it")
  document expired or too old   -> expired        ("bring a current one")
  field at or below the threshold, or not a valid value (not a date, not a number ...) -> unreadable
  declared field not found on a present document (and not may_be_blank)               -> missing_field
  a check the YAML marks citizen_remedy: name_mismatch, for each document whose name differs -> name_mismatch
Left out (no citizen action): values outside a plausible range, readers disagreeing, extraction unavailable,
survey or house mismatches, duplicate claims, tenant / mundkar entries, and any other check.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from app.facts import CaseFacts
from app.rules_loader import Scheme
from app.verification import CheckResult, dropped_middle_name, has_non_name_characters, name_score

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "web" / "src" / "i18n"
LANGUAGES = ("en", "hi", "mr", "kok")
Kind = Literal["missing", "expired", "unreadable", "missing_field", "name_mismatch"]
KIND_ORDER = ("missing", "expired", "name_mismatch", "unreadable", "missing_field")
NOT_THE_CITIZENS = "outside the plausible range"   # a suspicious value is for the officer, not a re-submission


class NoticeItem(BaseModel):
    kind: Kind
    document: str                 # document id from the scheme YAML
    fields: list[str] = []        # field ids on that document (unreadable, missing_field)
    field_labels: list[str] = []  # their YAML labels, for the browser


def _label(scheme: Scheme, doc: str, field: str) -> str:
    return scheme.terms.get(f"{doc}.{field}") or scheme.terms.get(field) or field.replace("_", " ")


def _name_mismatches(scheme: Scheme, checks: list[CheckResult], facts: CaseFacts) -> list[str]:
    out: list[str] = []
    flagged = {c.check_id for c in checks if c.status != "pass"}
    for check in scheme.verification_checks:
        if check.citizen_remedy != "name_mismatch" or check.id not in flagged or not check.across:
            continue
        for f in check.fields:
            base = facts.names.get(check.across[0], {}).get(f)
            if base is None:
                continue
            for doc in check.across[1:]:
                value = facts.names.get(doc, {}).get(f)
                if value is None:
                    continue
                differs = (name_score(str(base), str(value)) < (check.fuzzy_threshold or 1.0)
                           or dropped_middle_name(str(base), str(value)) or has_non_name_characters(str(value)))
                if differs and doc not in out:
                    out.append(doc)
    return out


def build_items(scheme: Scheme, checks: list[CheckResult], facts: CaseFacts) -> list[NoticeItem]:
    found: dict[tuple[str, str], list[str]] = {}

    def add(kind: str, doc: str, field: Optional[str] = None) -> None:
        fields = found.setdefault((kind, doc), [])
        if field and field not in fields:
            fields.append(field)

    for doc in facts.missing_documents:
        add("missing", doc)
    for doc, status in facts.validity.items():
        if status == "expired":
            add("expired", doc)
    for doc in _name_mismatches(scheme, checks, facts):
        add("name_mismatch", doc)
    for ref in facts.low_confidence:
        add("unreadable", *ref.split(".", 1))
    for ref, why in facts.invalid.items():
        if not why.startswith(NOT_THE_CITIZENS):
            add("unreadable", *ref.split(".", 1))
    for req in scheme.required_documents:
        doc = facts.names.get(req.id, {})
        if not doc.get("present"):
            continue
        for field in req.fields:
            ref = f"{req.id}.{field}"
            if field in doc or field in req.may_be_blank or ref in facts.low_confidence \
                    or ref in facts.invalid or ref in facts.disagree:
                continue
            add("missing_field", req.id, field)

    order = {d: i for i, d in enumerate(scheme.document_ids)}
    keys = sorted(found, key=lambda k: (order.get(k[1], 99), KIND_ORDER.index(k[0])))
    return [NoticeItem(kind=kind, document=doc, fields=found[(kind, doc)],
                       field_labels=[_label(scheme, doc, f) for f in found[(kind, doc)]]) for kind, doc in keys]


@lru_cache(maxsize=8)
def templates(language: str) -> dict[str, str]:
    if language not in LANGUAGES:
        raise ValueError(f"Unknown language {language!r}; use one of {', '.join(LANGUAGES)}")
    return json.loads((TRANSLATIONS_DIR / f"{language}.json").read_text(encoding="utf-8"))


def _fill(template: str, values: dict[str, str]) -> str:
    out = template
    for name, value in values.items():
        out = out.replace("{" + name + "}", value)
    return out


def render(items: list[NoticeItem], language: str, scheme: Scheme, case_ref: str, issued: str) -> list[str]:
    """The notice as lines, from the fixed templates."""
    t = templates(language)
    doc_name = lambda d: t.get(f"documents.{d}") or scheme.terms.get(d) or d.replace("_", " ")
    lines = [t["deficiency.title"], _fill(t["deficiency.intro"], {"case_ref": case_ref})]
    for item in items:
        lines.append(_fill(t[f"deficiency.{item.kind}"],
                           {"document": doc_name(item.document), "fields": ", ".join(item.field_labels)}))
    lines += [t["deficiency.footer"], _fill(t["deficiency.date"], {"date": issued})]
    return lines
