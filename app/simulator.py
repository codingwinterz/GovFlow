"""Rule simulator: what would change if one parameter or input default changed?

Read-only: a deep copy of the loaded scheme is changed in memory; the YAML is never written.
Every outcome and amount comes from the existing assess_case (rules engine + calculator).
"""

import math
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from app.assessment import assess_case
from app.case_model import CaseIn
from app.rules_loader import Scheme, load_scheme_by_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"


class Knob(BaseModel):
    name: str
    kind: Literal["parameter", "input_default"]
    value: float


class Outcome(BaseModel):
    overall: str
    compensation_status: Optional[str]
    total: Optional[float]
    items: dict[str, float]


class CaseComparison(BaseModel):
    case_id: str
    before: Outcome
    after: Outcome
    total_change: Optional[float]   # after.total - before.total, computed here (never in the browser)
    changed: bool


class SimulationResult(BaseModel):
    scheme: str
    rules_version: str
    name: str
    kind: str
    original_value: float
    new_value: float
    case_count: int
    changed_count: int
    cases: list[CaseComparison]
    read_only: bool = True


def knobs(scheme: Scheme) -> list[Knob]:
    if scheme.compensation is None:
        return []
    out = [Knob(name=k, kind="parameter", value=v) for k, v in scheme.compensation.parameters.items()]
    out += [Knob(name=k, kind="input_default", value=i.default)
            for k, i in scheme.compensation.inputs.items() if i.default is not None]
    return out


def with_change(scheme: Scheme, name: str, value: float) -> tuple[Scheme, Knob]:
    if not math.isfinite(value):
        raise ValueError("value must be a finite number")
    knob = next((k for k in knobs(scheme) if k.name == name), None)
    if knob is None:
        raise ValueError(f"{name!r} is not an adjustable parameter or input default of {scheme.scheme}")
    changed = scheme.model_copy(deep=True)
    if knob.kind == "parameter":
        changed.compensation.parameters[name] = float(value)
    else:
        changed.compensation.inputs[name].default = float(value)
    return changed, knob


def synthetic_cases(scheme_name: str) -> list[CaseIn]:
    return [CaseIn.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted((DATA_DIR / scheme_name).glob("case_*/case.json"))]


def _outcome(scheme: Scheme, case: CaseIn, others: list[CaseIn]) -> Outcome:
    a = assess_case(scheme, case, others)
    c = a.compensation
    return Outcome(overall=a.eligibility.overall, compensation_status=c.status if c else None,
                   total=c.total if c else None, items={i.component: i.amount for i in c.items} if c else {})


def simulate(scheme_name: str, name: str, value: float) -> SimulationResult:
    before_scheme = load_scheme_by_name(scheme_name)
    after_scheme, knob = with_change(before_scheme, name, value)
    cases = synthetic_cases(scheme_name)
    rows = []
    for case in cases:
        before, after = _outcome(before_scheme, case, cases), _outcome(after_scheme, case, cases)
        change = (round(after.total - before.total, 2)
                  if before.total is not None and after.total is not None else None)
        rows.append(CaseComparison(case_id=case.case_id, before=before, after=after, total_change=change,
                                   changed=before != after))
    return SimulationResult(scheme=scheme_name, rules_version=before_scheme.version, name=name, kind=knob.kind,
                            original_value=knob.value, new_value=float(value), case_count=len(rows),
                            changed_count=sum(r.changed for r in rows), cases=rows)
