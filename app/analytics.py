"""Read-only dashboard analytics over stored cases, SLA timers, compensation items, and verification flags."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import sla
from app.models import (
    CASE_STATUSES, AuditLog, Case, CompensationItemRow, VerificationFlag,
    as_utc as _utc, iso_utc,
)
from app.rules_loader import is_scheme, load_scheme_by_name, scheme_names

CLOSED = ("approved", "rejected", "withdrawn")
SEVERITIES = ("high", "medium", "low")


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


def _liability(session: Session, cases: list[Case], all_schemes: list[str]) -> dict[str, Any]:
    rows = (
        session.query(CompensationItemRow.case_id, func.sum(CompensationItemRow.amount))
        .group_by(CompensationItemRow.case_id)
        .all()
    )
    totals = {case_id: float(total or 0.0) for case_id, total in rows}
    committed_by_scheme = {s: 0.0 for s in all_schemes}
    pending_by_scheme = {s: 0.0 for s in all_schemes}
    for c in cases:
        amount = totals.get(c.id, 0.0)
        if not amount:
            continue
        if c.status == "approved":
            committed_by_scheme[c.scheme] = round(committed_by_scheme.get(c.scheme, 0.0) + amount, 2)
        elif c.status not in CLOSED:
            pending_by_scheme[c.scheme] = round(pending_by_scheme.get(c.scheme, 0.0) + amount, 2)
    committed_total = round(sum(committed_by_scheme.values()), 2)
    pending_total = round(sum(pending_by_scheme.values()), 2)
    combined_by_scheme = {
        s: round(committed_by_scheme.get(s, 0.0) + pending_by_scheme.get(s, 0.0), 2)
        for s in all_schemes
    }
    return {
        "committed_total": committed_total,
        "pending_total": pending_total,
        "combined_total": round(committed_total + pending_total, 2),
        "committed_by_scheme": committed_by_scheme,
        "pending_by_scheme": pending_by_scheme,
        "combined_by_scheme": combined_by_scheme,
        "source": (
            "stored compensation items: approved cases (committed) and open pipeline cases (pending); "
            "rejected and withdrawn cases excluded"
        ),
    }


def _flags_summary(session: Session, cases: list[Case], all_schemes: list[str]) -> dict[str, Any]:
    case_by_id = {c.id: c for c in cases}
    resolved_pairs: set[tuple[str, str]] = set()
    for row in session.query(AuditLog).filter_by(action="flag_resolution").order_by(AuditLog.id):
        try:
            flag_kind = json.loads(row.payload_json).get("flag")
        except Exception:
            flag_kind = None
        if row.case_id and flag_kind:
            resolved_pairs.add((row.case_id, str(flag_kind)))

    flag_rows = session.query(VerificationFlag).order_by(VerificationFlag.id).all()
    open_count = 0
    resolved_count = 0
    by_kind: dict[str, int] = {}
    by_severity: dict[str, int] = {sev: 0 for sev in SEVERITIES}
    by_scheme: dict[str, int] = {s: 0 for s in all_schemes}

    for f in flag_rows:
        c = case_by_id.get(f.case_id)
        is_resolved = (f.case_id, f.kind) in resolved_pairs or (c is not None and c.status in CLOSED)
        if is_resolved:
            resolved_count += 1
        else:
            open_count += 1
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        if c is not None:
            by_scheme[c.scheme] = by_scheme.get(c.scheme, 0) + 1

    return {
        "total_count": len(flag_rows),
        "open_count": open_count,
        "resolved_count": resolved_count,
        "by_kind": by_kind,
        "by_severity": by_severity,
        "by_scheme": by_scheme,
        "source": "verification flags on cases; resolved by officer flag_resolution or case closure",
    }


def _schemes_with_amounts(schemes: list[str]) -> list[str]:
    """Liability is listed only for schemes that calculate an amount (a compensation section in the YAML)."""
    return [s for s in schemes if not is_scheme(s) or load_scheme_by_name(s).compensation is not None]


def analytics(session: Session, stuck_days: float = 7, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cases = session.query(Case).all()
    all_schemes = sorted(set(scheme_names()) | {c.scheme for c in cases})

    by_status: dict[str, int] = {}
    per_scheme: dict[str, int] = {}
    by_scheme_and_status: dict[str, dict[str, int]] = {
        s: {st: 0 for st in CASE_STATUSES} for s in all_schemes
    }
    for c in cases:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        per_scheme[c.scheme] = per_scheme.get(c.scheme, 0) + 1
        by_scheme_and_status.setdefault(c.scheme, {st: 0 for st in CASE_STATUSES})
        by_scheme_and_status[c.scheme][c.status] = by_scheme_and_status[c.scheme].get(c.status, 0) + 1

    times = _processing_seconds(session)
    moved = last_movement(session)
    cutoff = now - timedelta(days=stuck_days)
    stuck = sorted(
        (
            {"case_id": c.id, "status": c.status, "scheme": c.scheme, "last_movement": iso_utc(moved[c.id])}
            for c in cases if c.status not in CLOSED and moved[c.id] <= cutoff
        ),
        key=lambda s: moved[s["case_id"]],
    )

    decided, waited = sla.decision_times(session), sla.waiting_times(session, now)
    sla_by_case = {c.id: sla.sla_view(c, now, decided, waited) for c in cases}

    overdue = [
        {"case_id": c.id, "status": c.status, "scheme": c.scheme, **sla_by_case[c.id]}
        for c in cases if sla_by_case[c.id]["overdue"]
    ]
    overdue_by_status: dict[str, int] = {}
    overdue_by_scheme: dict[str, int] = {}
    for o in overdue:
        overdue_by_status[o["status"]] = overdue_by_status.get(o["status"], 0) + 1
        overdue_by_scheme[o["scheme"]] = overdue_by_scheme.get(o["scheme"], 0) + 1

    days_all = [sla_by_case[c.id]["days_open"] for c in cases]
    days_by_scheme: dict[str, list[int]] = {s: [] for s in all_schemes}
    for c in cases:
        days_by_scheme.setdefault(c.scheme, []).append(sla_by_case[c.id]["days_open"])
    avg_days_by_scheme = {
        s: (round(sum(vals) / len(vals), 1) if vals else None)
        for s, vals in days_by_scheme.items()
    }

    return {
        "total_cases": len(cases),
        "by_status": by_status,
        "per_scheme": per_scheme,
        "by_scheme_and_status": by_scheme_and_status,
        "overdue_count": len(overdue),
        "overdue_by_status": overdue_by_status,
        "overdue_by_scheme": overdue_by_scheme,
        "overdue_source": sla.SOURCE,
        "overdue_cases": sorted(overdue, key=lambda o: -o["days_open"]),
        "average_days_open": round(sum(days_all) / len(days_all), 1) if days_all else None,
        "average_days_open_by_scheme": avg_days_by_scheme,
        "average_days_open_source": (
            "active days open from case created_at to now (or officer decision), "
            "excluding needs_info citizen waiting intervals"
        ),
        "decided_cases": len(times),
        "average_processing_seconds": round(sum(times) / len(times), 1) if times else None,
        "average_processing_source": "case created_at to officer_decision audit entry",
        "liability": _liability(session, cases, _schemes_with_amounts(all_schemes)),
        "flags": _flags_summary(session, cases, all_schemes),
        "stuck_days": stuck_days,
        "stuck_source": "latest audit entry per case (else case updated_at)",
        "stuck_cases": stuck,
    }
