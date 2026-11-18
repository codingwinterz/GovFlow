"""Flags that need an officer's recorded resolution before approval (the YAML's approval_needs_resolution).

A flag is open while it is on the case and no resolution has been recorded for it since the latest
verification. New evidence re-runs verification, so a resolution never carries over to documents it did not see.
Nothing here decides anything: it only says which resolutions are still missing.
"""

import json
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, VerificationFlag
from app.rules_loader import Scheme, VerificationCheck

MAX_REFERENCE = 200


def resolution_checks(scheme: Scheme) -> dict[str, VerificationCheck]:
    return {c.id: c for c in scheme.verification_checks if c.approval_needs_resolution}


def _resolved_since_verification(session: Session, case_id: str) -> set[str]:
    latest = (session.query(AuditLog.id).filter_by(case_id=case_id, action="verify_documents")
              .order_by(AuditLog.id.desc()).first())
    since = latest[0] if latest else 0
    rows = session.query(AuditLog).filter(AuditLog.case_id == case_id, AuditLog.action == "flag_resolution",
                                          AuditLog.id > since)
    return {json.loads(r.payload_json)["flag"] for r in rows}


def open_resolution_flags(session: Session, case_id: str, scheme: Scheme) -> list[VerificationCheck]:
    """The checks whose flag is on the case and has no resolution recorded since the latest verification."""
    checks = resolution_checks(scheme)
    flagged = {f.kind for f in session.query(VerificationFlag).filter_by(case_id=case_id) if f.kind in checks}
    resolved = _resolved_since_verification(session, case_id)
    return [checks[k] for k in checks if k in flagged and k not in resolved]


def citizen_notices(session: Session, case_id: str, scheme: Scheme) -> list[str]:
    """Notice keys for the citizen page, in YAML order: a check with citizen_notice whose flag is on the case
    (and, if it needs a resolution, not yet resolved). Keys only: no flag detail, other case or name."""
    open_ids = {c.id for c in open_resolution_flags(session, case_id, scheme)}
    flagged = {f.kind for f in session.query(VerificationFlag).filter_by(case_id=case_id)}
    keys: list[str] = []
    for c in scheme.verification_checks:
        is_open = c.id in open_ids if c.approval_needs_resolution else c.id in flagged
        if c.citizen_notice and is_open and c.citizen_notice not in keys:
            keys.append(c.citizen_notice)
    return keys


def resolution_problem(resolution: Optional[dict[str, Any]], today: date) -> Optional[str]:
    """Why a submitted resolution is not acceptable, or None. It needs a reference and a date not in the future."""
    if not isinstance(resolution, dict):
        return "a reference and a date are required"
    reference = str(resolution.get("reference") or "").strip()
    if not reference:
        return "a reference is required"
    if len(reference) > MAX_REFERENCE:
        return f"the reference is longer than {MAX_REFERENCE} characters"
    try:
        when = date.fromisoformat(str(resolution.get("date") or ""))
    except ValueError:
        return "the date must be YYYY-MM-DD"
    if when > today:
        return "the date is in the future"
    return None
