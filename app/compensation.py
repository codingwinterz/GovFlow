"""Deterministic compensation calculator driven by the scheme YAML.

Components are evaluated in YAML order; each rounded result is added to the
namespace so later components (e.g. solatium) can use it, and the itemised
amounts always add up exactly to the total.
"""

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.case_model import CaseIn
from app.facts import CaseFacts, build_facts, missing_reason
from app.rules_loader import CompensationInput, Scheme, YearsBetween
from app.safe_eval import UnknownName, evaluate, names_in

DAYS_PER_YEAR = 365  # VERIFY: day-count convention for s.30(3) interest (actual/365 assumed)


class InputValue(BaseModel):
    name: str
    value: Any
    source: str


class CompensationItem(BaseModel):
    component: str
    amount: float
    formula_note: str


class CompensationResult(BaseModel):
    status: Literal["computed", "needs_review"]
    items: list[CompensationItem]
    total: Optional[float]
    inputs: list[InputValue]
    missing: list[str]
    review_notes: list[str]
    rules_version: str


class _Missing(Exception):
    """An input cannot be resolved; carries the reason for the officer."""


def _fmt(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return str(round(value, 6))
    return str(value)


def _as_date(value: Any, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise _Missing(f"{label} is not a valid date: {value!r}") from exc


def _lookup(expr: str, names: dict) -> Any:
    try:
        return evaluate(expr, names)
    except UnknownName as exc:
        raise _Missing(f"{expr} unavailable") from exc


def _years_between(spec: YearsBetween, names: dict) -> tuple[float, str]:
    start = _as_date(_lookup(spec.start, names), spec.start)
    try:
        end, end_source = _as_date(evaluate(spec.end, names), spec.end), spec.end
    except UnknownName:
        if spec.end_default_from is None:
            raise _Missing(f"{spec.end} unavailable")
        end = _as_date(_lookup(spec.end_default_from, names), spec.end_default_from)
        end_source = f"{spec.end_default_from} (default, VERIFY)"
    if end < start:
        raise _Missing(f"end date {end} is before start date {start}")
    days = (end - start).days
    return days / DAYS_PER_YEAR, f"years_between({spec.start}={start}, {end_source}={end}) = {days}/{DAYS_PER_YEAR}"


def _resolve(name: str, spec: CompensationInput, names: dict, facts: CaseFacts) -> InputValue:
    exprs = [spec.from_] if spec.from_ else [spec.years_between.start, spec.years_between.end]
    withheld = "; ".join(r for r in (missing_reason(e, facts) for e in exprs) if r)
    if withheld:   # a document value was read but is unusable: never replace it with a default
        raise _Missing(withheld)
    if spec.years_between:
        value, source = _years_between(spec.years_between, names)
        return InputValue(name=name, value=value, source=source)
    try:
        return InputValue(name=name, value=evaluate(spec.from_, names), source=spec.from_)
    except UnknownName:
        if spec.default is None:
            raise _Missing(f"{spec.from_} unavailable")
        return InputValue(name=name, value=spec.default,
                          source=f"default {_fmt(spec.default)} (VERIFY: {spec.from_} not supplied)")


def compute_compensation(scheme: Scheme, case: CaseIn) -> CompensationResult:
    comp = scheme.compensation
    facts = build_facts(scheme, case)
    case_names = facts.names
    inputs: list[InputValue] = []
    missing: list[str] = []
    notes: list[str] = []
    namespace: dict[str, Any] = dict(comp.parameters)

    for name, spec in comp.inputs.items():
        try:
            resolved = _resolve(name, spec, case_names, facts)
        except _Missing as exc:
            missing.append(name)
            notes.append(f"{name}: {exc}")
            continue
        inputs.append(resolved)
        namespace[name] = resolved.value

    items: list[CompensationItem] = []
    for component in comp.components:
        try:
            amount = round(float(evaluate(component.formula, namespace)), 2)
        except UnknownName as exc:
            missing.append(component.id)
            notes.append(f"{component.id}: needs {exc.args[0]}")
            continue
        except (TypeError, ValueError, ZeroDivisionError) as exc:   # e.g. an untyped officer input
            missing.append(component.id)
            notes.append(f"{component.id}: could not be computed ({exc})")
            continue
        used = ", ".join(f"{n}={_fmt(namespace[n])}" for n in names_in(component.formula))
        items.append(CompensationItem(component=component.id, amount=amount,
                                      formula_note=f"{component.formula} with {used}"))
        namespace[component.id] = amount

    status = "needs_review" if missing else "computed"
    total = None if missing else round(sum(i.amount for i in items), 2)
    return CompensationResult(status=status, items=items, total=total, inputs=inputs,
                              missing=missing, review_notes=notes,
                              rules_version=scheme.version)
