"""Read-only dashboard analytics. Counts and times only; no money is computed here."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog, Case
from app.models import as_utc as _utc

CLOSED = ("approved", "rejected", "withdrawn")


def last_movement(session: Session) -> dict[str, datetime]:
    """Latest audit entry per case (any tool call, upload or decision), else the case's updated_at."""
    rows = session.query(AuditLog.case_id, func.max(AuditLog.ts)).group_by(AuditLog.case_id).all()
    latest = {case_id: _utc(ts) for case_id, ts in rows if case_id}
    return {c.id: latest.get(c.id, _utc(c.updated_at)) for c in session.query(Case)}


def _processing_seconds(session: Session) -> list[float]:
    decided = {}
    for row in session.query(AuditLog).filter_by(action="officer_decision").order_by(AuditLog.id):
        decided[row.case_id] = _utc(row.ts)   # the latest decision counts
    created = {c.id: _utc(c.created_at) for c in session.query(Case).filter(Case.id.in_(list(decided)))}
    return [(decided[i] - created[i]).total_seconds() for i in decided if i in created]


def analytics(session: Session, stuck_days: float = 7, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cases = session.query(Case).all()
    by_status: dict[str, int] = {}
    per_scheme: dict[str, int] = {}
    for c in cases:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        per_scheme[c.scheme] = per_scheme.get(c.scheme, 0) + 1
    times = _processing_seconds(session)
    moved = last_movement(session)
    cutoff = now - timedelta(days=stuck_days)
    stuck = sorted(({"case_id": c.id, "status": c.status, "scheme": c.scheme,
                     "last_movement": moved[c.id].isoformat()}
                    for c in cases if c.status not in CLOSED and moved[c.id] <= cutoff),
                   key=lambda s: s["last_movement"])
    return {"total_cases": len(cases), "by_status": by_status, "per_scheme": per_scheme,
            "decided_cases": len(times),
            "average_processing_seconds": round(sum(times) / len(times), 1) if times else None,
            "average_processing_source": "case created_at to officer_decision audit entry",
            "stuck_days": stuck_days, "stuck_source": "latest audit entry per case (else case updated_at)",
            "stuck_cases": stuck}
