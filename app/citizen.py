"""Public, citizen-facing case status. Returns keys and API values only: the browser turns keys into
text from translation templates and formats numbers itself. No LLM is involved.

Never returned: verification flags, rule details, officer ids or comments, other cases, identifiers.
The verification code is an HMAC of the case reference with GOVFLOW_CITIZEN_SECRET. There is no built-in
secret: without one, status lookups are refused (a secret in the source would make every code predictable).
"""

import hashlib
import hmac
import json
from pathlib import Path
from collections import defaultdict, deque
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.audit import log_action
from app.env_file import env_value
from app.case_store import load_case
from app.facts import build_facts
from app.models import AuditLog, Case, CompensationItemRow, india_date
from app.privacy import mask_identifiers
from app.resolutions import open_resolution_flags
from app.rules_loader import load_scheme_by_name

SECRET_ENV = "GOVFLOW_CITIZEN_SECRET"
CITIZEN_STATUS = {"received": "received", "extracted": "received", "verified": "received", "assessed": "received",
                  "in_officer_review": "under_review", "needs_info": "needs_info", "approved": "approved",
                  "rejected": "rejected", "withdrawn": "closed"}
NEXT_STEP = {"received": "processing", "under_review": "officer_review", "needs_info": "provide_documents",
             "approved": "approved", "rejected": "rejected", "closed": "closed"}
DECIDED = ("needs_info", "approved", "rejected")
WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS_PER_CLIENT = 10
MAX_FAILURES_PER_CASE = 5


def citizen_secret(dotenv: Optional[Path] = None) -> Optional[str]:
    """The server's code secret: the environment, else the .env file at `dotenv`; None when not set."""
    return env_value(SECRET_ENV, dotenv)


def citizen_code(case_ref: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), case_ref.strip().upper().encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


def code_matches(case_ref: str, code: str, secret: str) -> bool:
    return hmac.compare_digest(citizen_code(case_ref, secret), str(code).strip())


class RateLimiter:
    """Sliding windows: all attempts per client, failed codes per case reference (known or not)."""

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self.by_client: dict[str, deque] = defaultdict(deque)
        self.failures_by_case: dict[str, deque] = defaultdict(deque)
        self._last_sweep = clock()

    def _recent(self, q: deque) -> deque:
        while q and q[0] <= self.clock() - WINDOW_SECONDS:
            q.popleft()
        return q

    def _sweep(self) -> None:
        """Once per window, forget addresses and references with no attempt inside the window, so records from
        one-off visitors (or an attacker rotating addresses and references) do not pile up in memory."""
        if self.clock() - self._last_sweep < WINDOW_SECONDS:
            return
        self._last_sweep = self.clock()
        for table in (self.by_client, self.failures_by_case):
            for key in [k for k, q in table.items() if not self._recent(q)]:
                del table[key]

    def allow(self, client: str, case_ref: str) -> bool:
        self._sweep()
        attempts = self._recent(self.by_client[client])
        failures = self._recent(self.failures_by_case[case_ref])
        attempts.append(self.clock())
        return len(attempts) <= MAX_ATTEMPTS_PER_CLIENT and len(failures) < MAX_FAILURES_PER_CASE

    def failed(self, case_ref: str) -> None:
        self.failures_by_case[case_ref].append(self.clock())


def _missing(session: Session, case: Case) -> list[dict[str, str]]:
    if CITIZEN_STATUS.get(case.status) in ("approved", "rejected", "closed"):
        return []
    facts = build_facts(load_scheme_by_name(case.scheme), load_case(session, case.id))
    out = [{"document": d, "reason": "missing"} for d in facts.missing_documents]
    out += [{"document": d, "reason": "expired"} for d, v in facts.validity.items() if v == "expired"]
    return out


def _decision(session: Session, case: Case) -> Optional[dict[str, str]]:
    if case.status not in DECIDED:
        return None
    row = (session.query(AuditLog).filter_by(case_id=case.id, action="officer_decision")
           .order_by(AuditLog.id.desc()).first())
    if row is None:
        return None
    return {"decision": json.loads(row.payload_json)["decision"], "date": india_date(row.ts)}


def _amounts(session: Session, case: Case, version: str) -> Optional[dict[str, Any]]:
    if case.status != "approved":
        return None   # before an officer decides, amounts are recommendations: not shown to the public
    items = session.query(CompensationItemRow).filter_by(case_id=case.id).all()
    return {"items": [{"component": i.component, "amount": i.amount, "source": i.formula_note} for i in items],
            "total": round(sum(i.amount for i in items), 2), "rules_version": version,
            "terms": load_scheme_by_name(case.scheme).terms}   # so the basis reads as words, not identifiers


def citizen_view(session: Session, case: Case) -> dict[str, Any]:
    scheme = load_scheme_by_name(case.scheme)
    status = CITIZEN_STATUS.get(case.status, "received")
    missing = _missing(session, case)
    next_step = "provide_documents" if missing and status in ("received", "needs_info") else NEXT_STEP[status]
    # A key only (translated in the browser): e.g. "additional verification of rights is in progress". No flag
    # detail, names or legal grounds reach the public page.
    notices = ([] if status in ("approved", "rejected", "closed") else
               [c.citizen_notice for c in open_resolution_flags(session, case.id, scheme) if c.citizen_notice])
    view = {"case_ref": case.id, "scheme": case.scheme, "status": status, "next_step": next_step,
            "missing": missing, "notices": notices, "decision": _decision(session, case),
            "amounts": _amounts(session, case, scheme.version)}
    log_action(session, case.id, "citizen:public", "citizen_status_viewed",
               {"returned": sorted(k for k, v in view.items() if v)}, scheme.version)
    session.commit()
    return mask_identifiers(view)
