"""Load and validate a scheme YAML file. All scheme logic lives in the YAML."""

import re
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ValidationError, model_validator

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


class RequiredDocument(BaseModel):
    id: str
    validity: Optional[Validity] = None


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

    @property
    def fuzzy_threshold(self) -> Optional[float]:
        match = re.fullmatch(r"fuzzy_(0(\.\d+)?|1(\.0+)?)", self.tolerance or "")
        return float(match.group(1)) if match else None

    @model_validator(mode="after")
    def _shape(self) -> "VerificationCheck":
        if self.builtin == "duplicate_claim":
            if not (self.key and self.claimed_area):
                raise ValueError(f"{self.id}: duplicate_claim needs key and claimed_area")
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
    end: str
    end_default_from: Optional[str] = None


class CompensationInput(BaseModel):
    from_: Optional[str] = None
    default: Optional[float] = None
    years_between: Optional[YearsBetween] = None

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
        return self


class Component(BaseModel):
    id: str
    formula: str


class Compensation(BaseModel):
    inputs: dict[str, CompensationInput] = {}
    parameters: dict[str, float] = {}
    components: list[Component]


class Scheme(BaseModel):
    scheme: str
    version: str
    source: str
    confidence_threshold: float
    required_documents: list[RequiredDocument]
    verification_checks: list[VerificationCheck] = []
    eligibility_rules: list[EligibilityRule]
    compensation: Optional[Compensation] = None

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
                exprs += [e for e in (yb.start, yb.end, yb.end_default_from) if e]
    return exprs


def _cross_check(scheme: Scheme) -> None:
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
    for expr in _expressions(scheme):
        try:
            check_expression(expr)
        except UnsafeExpression as exc:
            raise RulesError(str(exc)) from exc


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
