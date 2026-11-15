"""Append-only audit trail (CLAUDE.md rule 5). The table itself rejects UPDATE/DELETE."""

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.privacy import mask_identifiers


def log_action(session: Session, case_id: Optional[str], actor: str, action: str,
               payload: Any, rules_version: Optional[str] = None) -> AuditLog:
    row = AuditLog(case_id=case_id, actor=actor, action=action, rules_version=rules_version,
                   payload_json=json.dumps(mask_identifiers(payload), sort_keys=True, default=str))
    session.add(row)
    return row
