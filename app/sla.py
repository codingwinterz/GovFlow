"""SLA timers. Days open and an overdue flag, computed on read. Nothing changes automatically:
no status moves, nothing is written. Each scheme's YAML sets sla_days."""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, Case, as_utc
from app.rules_loader import load_scheme_by_name

CLOSED = ("approved", "rejected", "withdrawn")
WAITING = "needs_info"     # waiting for the citizen: the clock is paused
SOURCE = ("days from case created_at to now (or to the officer decision once closed), minus time spent waiting for "
          "the citizen (needs_info, from the audit log), against the scheme's sla_days")


@lru_cache(maxsize=32)
def _sla_days(scheme: str) -> int:
    return load_scheme_by_name(scheme).sla_days


def decision_times(session: Session) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for row in session.query(AuditLog).filter_by(action="officer_decision").order_by(AuditLog.id):
        out[row.case_id] = as_utc(row.ts)
    return out


def _starts_wait(row: AuditLog) -> bool:
    if row.action == "deficiency_notice_sent":
        return True
    return row.action == "officer_decision" and json.loads(row.payload_json).get("decision") == "send_back"


def _ends_wait(row: AuditLog) -> bool:
    return row.action == "add_document" and json.loads(row.payload_json).get("previous_status") == WAITING


def waiting_times(session: Session, now: datetime) -> dict[str, timedelta]:
    """Time each case spent in needs_info, from the audit log: from a send-back or a deficiency notice to the next
    document added. A wait still open runs to `now`."""
    total: dict[str, timedelta] = {}
    started: dict[str, datetime] = {}
    rows = (session.query(AuditLog).filter(AuditLog.action.in_(("officer_decision", "deficiency_notice_sent",
                                                                 "add_document")))
            .order_by(AuditLog.id))
    for row in rows:
        if _starts_wait(row):
            started.setdefault(row.case_id, as_utc(row.ts))
        elif _ends_wait(row) and row.case_id in started:
            total[row.case_id] = total.get(row.case_id, timedelta()) + as_utc(row.ts) - started.pop(row.case_id)
    for case_id, since in started.items():
        total[case_id] = total.get(case_id, timedelta()) + max(timedelta(), now - since)
    return total


def sla_view(case: Case, now: datetime, decided: dict[str, datetime],
             waited: Optional[dict[str, timedelta]] = None) -> dict[str, Any]:
    closed = case.status in CLOSED
    end = (decided.get(case.id) or as_utc(case.updated_at)) if closed else now
    paused = (waited or {}).get(case.id, timedelta())
    days_open = max(0, (end - as_utc(case.created_at) - paused).days)
    sla = _sla_days(case.scheme)
    overdue = (not closed) and case.status != WAITING and days_open > sla
    return {"days_open": days_open, "sla_days": sla, "overdue": overdue}
