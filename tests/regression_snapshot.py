"""Regression snapshots for LA-01, DR-01 and SW-01: the explanation text, the tool-step list, the compensation
values and the citizen page output, captured on main before the revenue mutation engine changes.

The golden files in tests/snapshots/ were written once by `python -m tests.regression_snapshot --write` on the
unchanged main branch. They must never be rewritten to make a test pass: a difference is a regression.
The only value normalised is the citizen decision date (today in India), replaced by FIXED_DECISION_DATE.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agent import run_agent
from app.case_model import CaseIn
from app.case_store import seed_case
from app.citizen import citizen_view
from app.extraction import ProviderError
from app.models import Case, CompensationItemRow, RuleResultRow, make_engine
from app.tools import amount_field_values, record_officer_decision

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
CASES = ("LA-01", "DR-01", "SW-01")
FIXED_DECISION_DATE = "2026-01-01"   # stands in for today (the decision date changes daily)
SCHEMES = ("land_acquisition", "disaster_relief", "social_welfare")   # the schemes that existed on main


class _NoLLM:
    name, model = "none", None

    def complete(self, system, messages, tools):
        raise ProviderError("no agent LLM in the regression snapshot", kind="not_configured")


def _cases() -> list[CaseIn]:
    return [CaseIn.model_validate_json(p.read_text(encoding="utf-8"))
            for scheme in SCHEMES for p in sorted((DATA / scheme).glob("case_*/case.json"))]


def capture(case_id: str) -> dict[str, Any]:
    engine = make_engine("sqlite://")
    with Session(engine) as session:
        for case in _cases():
            seed_case(session, case)
        run = run_agent(session, case_id, _NoLLM(), actor="snapshot")
        rules = [{"rule_id": r.rule_id, "status": r.status, "reason": r.reason, "clause": r.clause,
                  "rules_version": r.rules_version}
                 for r in session.query(RuleResultRow).filter_by(case_id=case_id).order_by(RuleResultRow.id)]
        items = [{"component": i.component, "amount": i.amount, "formula_note": i.formula_note}
                 for i in session.query(CompensationItemRow).filter_by(case_id=case_id)
                 .order_by(CompensationItemRow.id)]
        status_before_decision = session.get(Case, case_id).status
        record_officer_decision(session, case_id, role="officer", officer_id="snapshot", decision="approve",
                                comment="regression snapshot", confirmed=amount_field_values(session, case_id))
        view = citizen_view(session, session.get(Case, case_id))
    engine.dispose()
    if view.get("decision"):
        view["decision"]["date"] = FIXED_DECISION_DATE
    return {"case_id": case_id,
            "steps": [s.model_dump() for s in run.steps],
            "explanation": run.explanation,
            "explanation_warnings": run.explanation_warnings,
            "used_fallback": run.used_fallback,
            "final_status": run.final_status,
            "status_before_decision": status_before_decision,
            "rules": rules,
            "compensation": items,
            "citizen_view": view}


def snapshot_path(case_id: str) -> Path:
    return SNAPSHOT_DIR / f"{case_id}.json"


def write_all() -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    for case_id in CASES:
        snapshot_path(case_id).write_text(json.dumps(capture(case_id), indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write the regression snapshots (only on an unchanged main).")
    parser.add_argument("--write", action="store_true")
    if parser.parse_args().write:
        write_all()
