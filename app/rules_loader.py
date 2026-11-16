"""Load and validate a scheme YAML file. All scheme logic lives in the YAML."""

import ast
import re
import string
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ValidationError, model_validator

from app.field_types import FIELD_TYPES
from app.safe_eval import UnsafeExpression, check_expression

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


class RulesError(ValueError):
    """The scheme YAML is invalid."""


class Validity(BaseModel):
    expiry_field: Optional[str] = None
    date_field: Optional[str] = None
    max_age_days: Optional[int] = None

    @model_validator(mode="after")
    def _one_kind(self) -> "Validity":
        by_expiry = self.expiry_field is not None
        by_age = self.date_field is not None and self.max_age_days is not None
        if by_expiry == by_age:
            raise ValueError("validity needs either expiry_field, or date_field and max_age_days")
        return self


class Derived(BaseModel):
    """A field computed from two read fields, e.g. area_sqm from area + area_unit."""
    convert: str                      # a number field
    unit_field: str                   # a unit field
    to: Literal["sqm"]                # only square metres for now; factors live in app/units.py


class RequiredDocument(BaseModel):
    id: str
    fields: list[str] = []            # what extraction must read; empty = not declared
    types: dict[str, str] = {}        # field -> text | number | percent | date | unit | one_of (list = text)
    options: dict[str, list[str]] = {}   # one_of fields: the allowed values
    derived: dict[str, Derived] = {}
    validity: Optional[Validity] = None

    @model_validator(mode="before")
    @classmethod
    def _typed_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            declared = data["fields"]
            types = {k: ("one_of" if isinstance(v, dict) and "one_of" in v else str(v)) for k, v in declared.items()}
            options = {k: list(v["one_of"] or []) for k, v in declared.items() if isinstance(v, dict) and "one_of" in v}
            data = {**data, "fields": list(declared), "types": types, "options": options}
        return data

    @model_validator(mode="after")
    def _known_types(self) -> "RequiredDocument":
        self.types = {f: self.types.get(f, "text") for f in self.fields}
        for name, kind in self.types.items():
            if kind not in FIELD_TYPES:
                raise ValueError(f"{self.id}.{name}: unknown type {kind!r}; use one of {list(FIELD_TYPES)}")
            if kind == "one_of" and not [o for o in self.options.get(name, []) if str(o).strip()]:
                raise ValueError(f"{self.id}.{name}: one_of needs a non-empty list of allowed values")
        for name, d in self.derived.items():
            if name in self.types:
                raise ValueError(f"{self.id}.{name}: derived field clashes with a read field")
            for source, kind in ((d.convert, "number"), (d.unit_field, "unit")):
                if self.types.get(source) != kind:
                    raise ValueError(f"{self.id}.{name}: {source!r} must be a declared {kind} field")
        return self


# Message templates for the duplicate_claim built-in, with the placeholders each may use.
DUPLICATE_MESSAGES = {
    "key_unavailable": {"key_expr"},
    "no_competitor": {"key"},
    "competing": {"ids", "key"},                       # another open case shares the key
    "within_total": {"ids", "key", "combined", "total"},   # only with claimed_area and total_area
    "exceeds_total": {"ids", "key", "combined", "total"},
}


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class VerificationCheck(BaseModel):
    id: str
    severity: Literal["low", "medium", "high"] = "medium"
    # field comparison checks
    fields: list[str] = []
    across: list[str] = []
    tolerance: Optional[str] = None
    # built-in checks
    builtin: Optional[Literal["duplicate_claim"]] = None
    key: Optional[str] = None
    claimed_area: Optional[str] = None
    total_area: Optional[str] = None
    messages: dict[str, str] = {}     # wording shown to officers; each scheme writes its own

    @property
    def fuzzy_threshold(self) -> Optional[float]:
        match = re.fullmatch(r"fuzzy_(0(\.\d+)?|1(\.0+)?)", self.tolerance or "")
        return float(match.group(1)) if match else None

    def _check_duplicate_shape(self) -> None:
        if not self.key:
            raise ValueError(f"{self.id}: duplicate_claim needs key")
        if self.total_area and not self.claimed_area:
            raise ValueError(f"{self.id}: total_area needs claimed_area")
        required = {"key_unavailable", "no_competitor", "competing"}
        if self.claimed_area and self.total_area:
            required |= {"within_total", "exceeds_total"}
        if not self.messages:
            raise ValueError(f"{self.id}: duplicate_claim needs messages: {sorted(required)}")
        missing = required - set(self.messages)
        unknown = set(self.messages) - set(DUPLICATE_MESSAGES)
        if missing or unknown:
            raise ValueError(f"{self.id}: messages missing {sorted(missing)}, unknown {sorted(unknown)}")
        for name, template in self.messages.items():
            bad = _placeholders(template) - DUPLICATE_MESSAGES[name]
            if bad:
                raise ValueError(f"{self.id}: message {name} uses unknown placeholders {sorted(bad)}; "
                                 f"allowed {sorted(DUPLICATE_MESSAGES[name])}")

    @model_validator(mode="after")
    def _shape(self) -> "VerificationCheck":
        if self.builtin == "duplicate_claim":
            self._check_duplicate_shape()
            return self
        if not (self.fields and len(self.across) >= 2):
            raise ValueError(f"{self.id}: needs fields and at least two documents in across")
        if self.tolerance != "exact" and self.fuzzy_threshold is None:
            raise ValueError(f"{self.id}: tolerance must be 'exact' or 'fuzzy_<0..1>'")
        return self


class EligibilityRule(BaseModel):
    id: str
    clause: str
    fail_reason: str
    when: Optional[str] = None
    depends_on: list[str] = []

    @model_validator(mode="after")
    def _has_condition(self) -> "EligibilityRule":
        if self.when is None and not self.depends_on:
            raise ValueError(f"{self.id}: needs `when`, `depends_on`, or both")
        return self


class YearsBetween(BaseModel):
    start: str
    end: Optional[str] = None
    end_earliest_of: list[str] = []        # the earliest of several dates (e.g. award, possession)
    end_default_from: Optional[str] = None  # stands in for a date not recorded yet (assumed not yet happened)

    @model_validator(mode="after")
    def _one_end(self) -> "YearsBetween":
        if (self.end is None) == (not self.end_earliest_of):
            raise ValueError("years_between needs exactly one of `end` or `end_earliest_of`")
        return self


class CompensationInput(BaseModel):
    from_: Optional[str] = None
    default: Optional[float] = None
    years_between: Optional[YearsBetween] = None
    range: Optional[tuple[float, float]] = None   # allowed [min, max]; outside -> needs review, never clamped

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _rename_from(cls, data: Any) -> Any:
        if isinstance(data, dict) and "from" in data:
            data = {**data, "from_": data.pop("from")}
        return data

    @model_validator(mode="after")
    def _one_source(self) -> "CompensationInput":
        if (self.from_ is None) == (self.years_between is None):
            raise ValueError("compensation input needs exactly one of `from` or `years_between`")
        if self.range is not None:
            lo, hi = self.range
            if lo > hi:
                raise ValueError(f"range {list(self.range)} has min above max")
            if self.default is not None and not lo <= self.default <= hi:
                raise ValueError(f"default {self.default} is outside range {list(self.range)}")
        return self


class Component(BaseModel):
    id: str
    formula: str


class Compensation(BaseModel):
    inputs: dict[str, CompensationInput] = {}
    parameters: dict[str, float] = {}
    components: list[Component]


LABELS = ("title", "amounts", "total")   # display wording; each scheme writes its own


class SelfCheckQuestion(BaseModel):
    field: str                         # doc_id.field, a declared document field
    prompt: str
    choices: list[str] = []


class SelfCheck(BaseModel):
    questions: list[SelfCheckQuestion]
    rules: list[str]                   # eligibility rules whose `when` can be answered from the questions


class Scheme(BaseModel):
    scheme: str
    version: str
    source: str
    labels: dict[str, str]
    sla_days: int                    # target days from intake to officer decision; overdue is a flag only
    confidence_threshold: float
    required_documents: list[RequiredDocument]
    verification_checks: list[VerificationCheck] = []
    eligibility_rules: list[EligibilityRule]
    compensation: Optional[Compensation] = None
    self_check: Optional[SelfCheck] = None

    @model_validator(mode="after")
    def _positive_sla(self) -> "Scheme":
        if self.sla_days <= 0:
            raise ValueError(f"sla_days must be a positive whole number of days, got {self.sla_days}")
        return self

    @model_validator(mode="after")
    def _labels(self) -> "Scheme":
        missing = [k for k in LABELS if not str(self.labels.get(k, "")).strip()]
        unknown = sorted(set(self.labels) - set(LABELS))
        if missing or unknown:
            raise ValueError(f"labels missing {missing}, unknown {unknown}; expected {list(LABELS)}")
        return self

    @property
    def document_ids(self) -> list[str]:
        return [d.id for d in self.required_documents]


def _expressions(scheme: Scheme) -> list[str]:
    exprs = [r.when for r in scheme.eligibility_rules if r.when]
    exprs += [e for c in scheme.verification_checks for e in (c.key, c.claimed_area, c.total_area) if e]
    if scheme.compensation:
        exprs += [c.formula for c in scheme.compensation.components]
        for inp in scheme.compensation.inputs.values():
            if inp.from_:
                exprs.append(inp.from_)
            if inp.years_between:
                yb = inp.years_between
                exprs += [e for e in (yb.start, yb.end, yb.end_default_from, *yb.end_earliest_of) if e]
    return exprs


def _check_declared_fields(scheme: Scheme) -> None:
    """Fields used by checks and validity must be in the document's extraction list."""
    declared = {d.id: set(d.fields) for d in scheme.required_documents if d.fields}
    needed: list[tuple[str, str, str]] = []
    for check in scheme.verification_checks:
        needed += [(doc, f, f"check {check.id}") for doc in check.across for f in check.fields]
    for doc in scheme.required_documents:
        if doc.validity:
            v = doc.validity
            needed += [(doc.id, f, "validity") for f in (v.expiry_field, v.date_field) if f]
    for doc_id, field_name, used_by in needed:
        if doc_id in declared and field_name not in declared[doc_id]:
            raise RulesError(f"{doc_id}.{field_name} is used by {used_by} but not in its fields list")
    types = {d.id: d.types for d in scheme.required_documents}
    for doc_id, field_name, used_by in needed:
        if used_by == "validity" and doc_id in declared and types[doc_id][field_name] != "date":
            raise RulesError(f"{doc_id}.{field_name} is used by validity and must have type date")


RESERVED_NAMES = ("params", "case", "reference_date", "all_documents_present", "all_documents_valid")


def _params_used(expr: str) -> set[str]:
    return {n.attr for n in ast.walk(ast.parse(expr, mode="eval"))
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "params"}


def _check_params(scheme: Scheme) -> None:
    """Rule and check expressions may read params.<name>; every name must be a declared parameter."""
    known = set(scheme.compensation.parameters) if scheme.compensation else set()
    exprs = [r.when for r in scheme.eligibility_rules if r.when]
    exprs += [e for c in scheme.verification_checks for e in (c.key, c.claimed_area, c.total_area) if e]
    for expr in exprs:
        unknown = _params_used(expr) - known
        if unknown:
            raise RulesError(f"{expr!r} uses unknown parameters {sorted(unknown)}; declared: {sorted(known)}")


def _refs(expr: str) -> tuple[set[str], set[str]]:
    """Top-level names, and doc.field references, in an expression."""
    tree = ast.parse(expr, mode="eval")
    calls = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in calls}
    refs = {f"{n.value.id}.{n.attr}" for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    return names, refs


def _check_self_check(scheme: Scheme) -> None:
    if scheme.self_check is None:
        return
    declared = {f"{d.id}.{f}" for d in scheme.required_documents for f in d.fields}
    asked = {q.field for q in scheme.self_check.questions}
    unknown = sorted(asked - declared)
    if unknown:
        raise RulesError(f"self_check questions {unknown} are not declared document fields")
    rules = {r.id: r for r in scheme.eligibility_rules}
    for rule_id in scheme.self_check.rules:
        if rule_id not in rules:
            raise RulesError(f"self_check lists unknown rule {rule_id!r}")
        when = rules[rule_id].when
        if not when:
            raise RulesError(f"self_check rule {rule_id!r} has no `when` condition to evaluate")
        names, refs = _refs(when)
        docs = {q.split(".")[0] for q in asked}
        outside = (names - docs - {"params"}) | {r for r in refs if r.split(".")[0] in docs and r not in asked}
        if outside:
            raise RulesError(f"self_check rule {rule_id!r} reads {sorted(outside)}, which are not questions")


def _cross_check(scheme: Scheme) -> None:
    reserved = set(scheme.document_ids) & set(RESERVED_NAMES)
    if reserved:
        raise RulesError(f"Document ids {sorted(reserved)} are reserved names")
    check_ids = {c.id for c in scheme.verification_checks}
    for rule in scheme.eligibility_rules:
        unknown = set(rule.depends_on) - check_ids
        if unknown:
            raise RulesError(f"Rule {rule.id} depends on unknown checks: {sorted(unknown)}")
    docs = set(scheme.document_ids)
    for check in scheme.verification_checks:
        unknown = set(check.across) - docs
        if unknown:
            raise RulesError(f"Check {check.id} uses undeclared documents: {sorted(unknown)}")
    _check_declared_fields(scheme)
    for expr in _expressions(scheme):
        try:
            check_expression(expr)
        except UnsafeExpression as exc:
            raise RulesError(str(exc)) from exc
    _check_params(scheme)
    _check_self_check(scheme)


def parse_scheme(data: dict) -> Scheme:
    try:
        scheme = Scheme.model_validate(data)
    except ValidationError as exc:
        raise RulesError(str(exc)) from exc
    _cross_check(scheme)
    return scheme


def load_scheme(path: Path) -> Scheme:
    return parse_scheme(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_scheme_by_name(name: str) -> Scheme:
    return load_scheme(RULES_DIR / f"{name}.yaml")
