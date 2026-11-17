"""Append-only audit trail (CLAUDE.md rule 5). The table itself rejects UPDATE/DELETE."""

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.privacy import mask_identifiers, redact_secrets


def log_action(session: Session, case_id: Optional[str], actor: str, action: str,
               payload: Any, rules_version: Optional[str] = None) -> AuditLog:
    row = AuditLog(case_id=case_id, actor=actor, action=action, rules_version=rules_version,
                   payload_json=json.dumps(redact_secrets(mask_identifiers(payload)), sort_keys=True, default=str))
    session.add(row)
    return row


def log_precheck(session: Session, document_type: str, result_category: str,
                 elapsed_ms: int, used_fallback: bool, rules_version: str) -> AuditLog:
    """Citizen document pre-check audit row: strictly whitelisted keys only (no file, text, values, or filename)."""
    payload = {
        "document_type": str(document_type),
        "result_category": str(result_category),
        "elapsed_ms": max(0, int(elapsed_ms)),
        "used_fallback": bool(used_fallback),
    }
    return log_action(session, None, "citizen:public", "document_precheck", payload, rules_version)

