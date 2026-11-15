"""SLA timers. Days open and an overdue flag, computed on read. Nothing changes automatically:
no status moves, nothing is written. Each scheme's YAML sets sla_days."""

from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, Case, as_utc
from app.rules_loader import load_scheme_by_name

CLOSED = ("approved", "rejected", "withdrawn")
SOURCE = "days from case created_at to now (or to the officer decision once closed), against the scheme's sla_days"


@lru_cache(maxsize=32)
def _sla_days(scheme: str) -> int:
    return load_scheme_by_name(scheme).sla_days


def decision_times(session: Session) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for row in session.query(AuditLog).filter_by(action="officer_decision").order_by(AuditLog.id):
        out[row.case_id] = as_utc(row.ts)
    return out


def sla_view(case: Case, now: datetime, decided: dict[str, datetime]) -> dict[str, Any]:
    closed = case.status in CLOSED
    end = (decided.get(case.id) or as_utc(case.updated_at)) if closed else now
    days_open = max(0, (end - as_utc(case.created_at)).days)
    sla = _sla_days(case.scheme)
    return {"days_open": days_open, "sla_days": sla, "overdue": (not closed) and days_open > sla}
