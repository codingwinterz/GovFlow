"""HTTP API for clerks, officers and citizens. Run: uvicorn app.main:app --reload

Roles come from the X-Role / X-User headers. DEMO ONLY: replace with real authentication
before any deployment; the headers are trusted as sent.
Only the officer role can approve, reject or send back (POST /cases/{id}/decision).
Every response that carries extracted values passes through mask_identifiers (rule 7).
"""

import base64
import binascii
import json
import re
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import tools
from app.agent import AgentReply, run_agent
from app import sla
from app.analytics import analytics
from app.audit import log_action
from app.auth import AUTH_ENV, INSECURE_ENV, issue_token, read_token
from app.body_limit import MAX_BODY_BYTES, BodyLimit
from app.upload_check import content_problem
from app.citizen import RateLimiter, citizen_view, code_matches
from app.env_file import env_value
from app.citizen import citizen_secret as default_citizen_secret
from app.confidence import needs_review_for_confidence
from app.resolutions import open_resolution_flags
from app import sahayak

SAHAYAK_DAILY_CAP = 200     # provider calls per day; past it, answers come from the entries verbatim
SAHAYAK_RATE_LIMIT = 20     # questions per client per ten minutes
from app.extraction import EXTRACTION_UNAVAILABLE_MESSAGE, ProviderError
from app.case_store import load_case
from app.models import AuditLog, Case, CompensationItemRow, Document, ExtractedField, RuleResultRow
from app.models import VerificationFlag, india_date, iso_utc, make_engine, queue_key
from app.privacy import mask_identifiers
from app.rules_engine import overall_from
from app.self_check import NoSelfCheck, public_questions, self_check
from app.simulator import knobs, simulate
from app.rules_loader import RULES_DIR, Scheme, case_input_names, is_scheme, load_scheme_by_name, scheme_names


def officer_inputs(scheme: Scheme) -> list[str]:
    """Officer-entered values the scheme reads as `case.<name>`, in YAML order (no names hardcoded here)."""
    return case_input_names(scheme)


def _all_schemes() -> list[Scheme]:
    return [load_scheme_by_name(name) for name in scheme_names()]

ROLES = ("citizen", "clerk", "officer", "admin")   # admin: rule simulator only
UPLOAD_TYPES = {".txt", ".png", ".jpg", ".jpeg", ".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BASE64_CHARS = 4 * -(-MAX_UPLOAD_BYTES // 3)   # base64 length of the largest allowed file
DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"   # gitignored: citizen documents
DOTENV = Path(__file__).resolve().parent.parent / ".env"
STATUS_NOT_CONFIGURED = ("Status lookup is not configured on this server: set GOVFLOW_CITIZEN_SECRET "
                         "(the demo seed writes one to .env).")


class Actor(BaseModel):
    role: str
    user: str

    @property
    def name(self) -> str:
        return f"{self.role}:{self.user}"


class CreateCase(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")   # also used as an upload folder name
    scheme: str
    reference_date: date
    inputs: dict[str, Any] = {}


class Inputs(BaseModel):
    inputs: dict[str, float | int | str]


class Upload(BaseModel):
    doc_type: str
    filename: str
    content_base64: str


class StatusLookup(BaseModel):
    case_ref: str = Field(max_length=64)
    code: str = Field(max_length=12)


class SelfCheckIn(BaseModel):
    scheme: str = Field(max_length=64)
    answers: dict[str, str] = {}


class SahayakIn(BaseModel):
    model_config = {"extra": "forbid"}
    message: str = Field(min_length=1, max_length=sahayak.MAX_MESSAGE)
    scheme: Optional[str] = Field(None, max_length=64)
    self_check: Optional[sahayak.SelfCheckSummary] = None    # ids and statuses only, never free text


class SimulateIn(BaseModel):
    scheme: str = Field(max_length=64)
    name: str = Field(max_length=64)
    value: float


class DemoLogin(BaseModel):
    role: Literal["clerk", "officer", "admin"]
    user: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")


class DecisionIn(BaseModel):
    decision: str
    comment: str = ""
    confirmed_fields: dict[str, Any] = {}   # approve: each amount-driving field at the value the officer checked
    # approve: for each open flag that needs one, {flag id: {"reference": "...", "date": "YYYY-MM-DD"}}
    resolutions: dict[str, dict[str, Any]] = {}


class NoticeIn(BaseModel):
    language: str = Field("en", max_length=8)


class _NoLLM:
    """Stands in when no agent LLM is configured: run_agent then uses the deterministic pipeline."""
    name, model = "none", None

    def __init__(self, reason: str):
        self.reason = reason

    def complete(self, system, messages, tools_) -> AgentReply:
        raise ProviderError(self.reason, kind="not_configured")


SIGN_IN_NOT_CONFIGURED = ("Sign-in is not configured on this server: set GOVFLOW_AUTH_SECRET "
                          "(the demo seed writes one to .env).")
PLAIN_HEADERS_REFUSED = ("Sign in first (POST /auth/demo-login) and send Authorization: Bearer <token>. "
                         "Plain X-Role headers are accepted only when GOVFLOW_DEMO_INSECURE=1.")


def actor_from(authorization: Optional[str], x_role: Optional[str], x_user: Optional[str],
               auth_secret: Optional[str], insecure: bool, at: datetime) -> Actor:
    """Who is calling: a signed, unexpired token; plain X-Role / X-User only in insecure demo mode."""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        claims = read_token(token, auth_secret, at) if auth_secret and scheme.lower() == "bearer" else None
        if claims is None or claims[0] not in ROLES:
            raise HTTPException(401, "Sign-in expired or not valid; sign in again")
        return Actor(role=claims[0], user=claims[1])
    if insecure and x_role in ROLES and x_user:
        return Actor(role=x_role, user=x_user)
    raise HTTPException(401, PLAIN_HEADERS_REFUSED)


def _require(actor: Actor, *roles: str) -> None:
    if actor.role not in roles:
        raise HTTPException(403, f"Role {actor.role} cannot do this")


# --- read models ---------------------------------------------------------------------------

def _case_summary(c: Case, flags_count: Optional[int] = None) -> dict[str, Any]:
    out = {"case_id": c.id, "scheme": c.scheme, "status": c.status, "confidence_flag": c.confidence_flag,
           "submitted_at": iso_utc(c.submitted_at) if c.submitted_at else None, "officer_id": c.officer_id,
           "created_at": iso_utc(c.created_at) if c.created_at else None}
    if flags_count is not None:
        out["flags_count"] = flags_count
    return out


def _documents(session: Session, case_id: str, threshold: float) -> list[dict[str, Any]]:
    docs = session.query(Document).filter_by(case_id=case_id).order_by(Document.id).all()
    latest = {d.doc_type: d.id for d in docs}
    out = []
    for d in docs:
        fields = [{"document_id": d.id, "document_type": d.doc_type, "field": f.field, "value": json.loads(f.value),
                   "confidence": f.confidence, "source_page": f.source_page, "method": f.method, "note": f.note,
                   "review_reason": f.review_reason,
                   "needs_review": needs_review_for_confidence(f.confidence, threshold) or bool(f.review_reason)}
                  for f in session.query(ExtractedField).filter_by(document_id=d.id)]
        unavailable = d.extraction_status == "extraction_unavailable"
        out.append({"id": d.id, "doc_type": d.doc_type, "current": latest[d.doc_type] == d.id,
                    "extraction_status": d.extraction_status, "extraction_error_kind": d.extraction_error_kind,
                    "message": EXTRACTION_UNAVAILABLE_MESSAGE if unavailable else None, "fields": fields})
    return out


def _latest_explanation(session: Session, case_id: str) -> Optional[dict[str, Any]]:
    row = (session.query(AuditLog).filter_by(case_id=case_id, action="agent_explanation")
           .order_by(AuditLog.id.desc()).first())
    if row is None:
        return None
    p = json.loads(row.payload_json)
    return {"text": p.get("text", ""), "warnings": p.get("warnings", []), "used_fallback": p.get("used_fallback"),
            "at": iso_utc(row.ts)}


def _detail(session: Session, case: Case) -> dict[str, Any]:
    scheme = load_scheme_by_name(case.scheme)
    rules = session.query(RuleResultRow).filter_by(case_id=case.id).all()
    items = session.query(CompensationItemRow).filter_by(case_id=case.id).all()
    open_flags = open_resolution_flags(session, case.id, scheme)
    labels = dict(scheme.labels)
    for check in open_flags:            # e.g. a tenant entry: the total is the holding's, not the owner's share
        if check.total_label:
            labels["total"] = check.total_label
    return mask_identifiers({
        **_case_summary(case), "reference_date": case.reference_date.isoformat() if case.reference_date else None,
        "inputs": json.loads(case.inputs_json), "rules_version": scheme.version, "labels": labels, "terms": scheme.terms,
        "resolutions_needed": [{"flag": c.id, "basis": c.basis} for c in open_flags],
        "documents": _documents(session, case.id, scheme.confidence_threshold),
        "flags": [{"kind": f.kind, "detail": f.detail, "severity": f.severity}
                  for f in session.query(VerificationFlag).filter_by(case_id=case.id)],
        "rule_results": [{"rule_id": r.rule_id, "status": r.status, "reason": r.reason, "clause": r.clause,
                          "rules_version": r.rules_version} for r in rules],
        "recommendation": overall_from([r.status for r in rules]) if rules else None,
        "compensation": {"items": [{"component": i.component, "amount": i.amount, "formula_note": i.formula_note}
                                   for i in items],
                         "total": round(sum(i.amount for i in items), 2) if items else None},
        "explanation": _latest_explanation(session, case.id),
        "confirm_fields": [{"ref": ref, "value": value} for ref, value in tools.amount_field_values(session, case.id).items()],
    })


# --- app -----------------------------------------------------------------------------------

def create_app(engine: Optional[Engine] = None, agent_llm_factory: Optional[Callable[[], Any]] = None,
               extraction_factory: Optional[Callable[[], Any]] = None,
               cross_check_factory: Optional[Callable[[], Any]] = None,
               upload_dir: Optional[Path] = None, citizen_secret: Optional[str] = None,
               auth_secret: Optional[str] = None, demo_insecure: Optional[bool] = None,
               clock: Callable[[], float] = time.monotonic,
               now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
               sahayak_llm_factory: Optional[Callable[[], Any]] = None,
               sahayak_daily_cap: int = SAHAYAK_DAILY_CAP, sahayak_rate_limit: int = SAHAYAK_RATE_LIMIT) -> FastAPI:
    app = FastAPI(title="GovFlow", version="0.1.0")
    app.add_middleware(BodyLimit, max_bytes=MAX_BODY_BYTES)   # 413 before any handler reads an oversized body
    secret = citizen_secret or default_citizen_secret()   # None: status lookups answer 503, never a weak default
    signing = auth_secret or env_value(AUTH_ENV)          # None: sign-in answers 503 and no token is accepted
    insecure = demo_insecure if demo_insecure is not None else env_value(INSECURE_ENV) == "1"
    limiter = RateLimiter(clock)
    knowledge = sahayak.load_knowledge()                                    # fail at start-up, not mid-chat
    sahayak_limiter = sahayak.RateLimiter(clock, limit=sahayak_rate_limit)  # its own, per client
    sahayak_budget = sahayak.DailyBudget(sahayak_daily_cap, today=lambda: now().date())
    sahayak_llm: dict[str, Any] = {}

    def actor_dep(authorization: Optional[str] = Header(None), x_role: Optional[str] = Header(None),
                  x_user: Optional[str] = Header(None)) -> Actor:
        return actor_from(authorization, x_role, x_user, signing, insecure, now())
    state: dict[str, Any] = {"engine": engine}
    uploads = Path(upload_dir or DEFAULT_UPLOAD_DIR)

    def second_reader() -> Any:
        """The cross-check reader (Tesseract), or None when it is not available: extraction then runs without it."""
        try:
            return cross_check_factory() if cross_check_factory else None
        except Exception:   # an optional second opinion must never block extraction
            return None

    def session_dep() -> Iterator[Session]:
        if state["engine"] is None:
            state["engine"] = make_engine()   # lazy: importing the app never creates a database
        with Session(state["engine"]) as session:
            yield session

    @app.exception_handler(tools.UnknownCase)
    async def _not_found(request: Request, exc: tools.UnknownCase) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(tools.InvalidInput)
    async def _bad_request(request: Request, exc: tools.InvalidInput) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(tools.ToolError)
    async def _conflict(request: Request, exc: tools.ToolError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(PermissionError)
    async def _forbidden(request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    def _get_case(session: Session, case_id: str) -> Case:
        case = session.get(Case, case_id)
        if case is None:
            raise tools.UnknownCase(f"Unknown case {case_id}")
        return case

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/demo-login")
    def demo_login(body: DemoLogin, session: Session = Depends(session_dep)) -> dict[str, Any]:
        """DEMO sign-in: no password. Issues a signed role token that expires. Production uses SSO instead."""
        if not signing:
            raise HTTPException(503, SIGN_IN_NOT_CONFIGURED)
        token, expires = issue_token(body.role, body.user, signing, now())
        log_action(session, None, f"{body.role}:{body.user}", "demo_sign_in", {"expires_at": iso_utc(expires)})
        session.commit()
        return {"token": token, "role": body.role, "user": body.user, "expires_at": iso_utc(expires)}

    @app.post("/public/status")
    def public_status(body: StatusLookup, request: Request,
                      session: Session = Depends(session_dep)) -> dict[str, Any]:
        """No login. Same 404 for an unknown reference or a wrong code; rate-limited by peer address."""
        if not secret:
            raise HTTPException(503, STATUS_NOT_CONFIGURED)
        client = request.client.host if request.client else "unknown"   # never X-Forwarded-For (spoofable)
        ref = body.case_ref.strip()
        if not limiter.allow(client, ref.upper()):
            raise HTTPException(429, "too_many_attempts")
        case = session.get(Case, ref)
        matches = code_matches(ref, body.code, secret)                    # computed even for unknown refs
        if case is None or not matches:
            limiter.failed(ref.upper())
            raise HTTPException(404, "not_found")
        return citizen_view(session, case)

    def _sahayak_llm() -> Any:
        """Built once; None when no provider is configured or it cannot be built (answers then come from entries)."""
        if "llm" not in sahayak_llm:
            try:
                sahayak_llm["llm"] = sahayak_llm_factory() if sahayak_llm_factory else None
            except Exception:
                sahayak_llm["llm"] = None
        return sahayak_llm["llm"]

    @app.get("/public/sahayak")
    def sahayak_topics(scheme: Optional[str] = None) -> dict[str, Any]:
        """Suggested questions (entry titles). No sign-in."""
        if scheme is not None and not is_scheme(scheme):
            raise HTTPException(422, "unknown scheme")
        topics = [{"id": e.id, "title": e.title} for e in knowledge if e.scheme in (None, scheme) or scheme is None]
        return {"topics": topics, "guide": sahayak.GUIDE, "language_note": sahayak.LANGUAGE_NOTE}

    @app.post("/public/sahayak")
    def sahayak_ask(body: SahayakIn, request: Request, session: Session = Depends(session_dep)) -> dict[str, Any]:
        """No sign-in. Answers only from the knowledge base; never decides, estimates or advises. The message is not
        stored: the audit row keeps its length and the matched entry ids only."""
        client = request.client.host if request.client else "unknown"
        if not sahayak_limiter.allow(client):
            raise HTTPException(429, "too_many_attempts")
        if body.scheme is not None and not is_scheme(body.scheme):
            raise HTTPException(422, "unknown scheme")
        problem = sahayak.summary_problem(body.self_check, body.scheme)
        if problem:
            raise HTTPException(422, problem)
        reply = sahayak.respond(body.message, knowledge, _sahayak_llm(), sahayak_budget, body.scheme, body.self_check)
        log_action(session, None, "citizen:public", "sahayak_query",
                   {"message_length": len(body.message), "entries": [e.id for e in reply.entries],
                    "used_fallback": reply.used_fallback, "reason": reply.reason, "scheme": body.scheme})
        session.commit()
        return mask_identifiers(reply.model_dump())

    @app.get("/public/self-check")
    def self_check_questions() -> list[dict[str, Any]]:
        return [q for q in (public_questions(s) for s in _all_schemes()) if q]

    @app.post("/public/self-check")
    def run_self_check(body: SelfCheckIn, request: Request) -> dict[str, Any]:
        """Dry run: no session, nothing created, nothing stored. A guide, not a decision."""
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client, f"self-check:{body.scheme}"):
            raise HTTPException(429, "too_many_attempts")
        if not is_scheme(body.scheme):
            raise HTTPException(404, "no_self_check")
        try:
            return self_check(load_scheme_by_name(body.scheme), body.answers).model_dump()
        except NoSelfCheck:
            raise HTTPException(404, "no_self_check") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/cases")
    def list_cases(status: Optional[str] = None, scheme: Optional[str] = None, actor: Actor = Depends(actor_dep),
                   session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
        _require(actor, "clerk", "officer")
        query = session.query(Case)
        if status:
            query = query.filter_by(status=status)
        if scheme:
            query = query.filter_by(scheme=scheme)
        flags: dict[str, list[dict[str, str]]] = {}
        for row in session.query(VerificationFlag).order_by(VerificationFlag.id):
            flags.setdefault(row.case_id, []).append({"kind": row.kind, "severity": row.severity})   # no detail text
        cases = sorted(query.all(), key=queue_key)
        decided, at = sla.decision_times(session), now()
        waited = sla.waiting_times(session, at)
        return [{**_case_summary(c, len(flags.get(c.id, []))), "flags": flags.get(c.id, []),
                 **sla.sla_view(c, at, decided, waited)} for c in cases]

    @app.get("/analytics")
    def get_analytics(stuck_days: float = 7, actor: Actor = Depends(actor_dep),
                      session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        return analytics(session, stuck_days=stuck_days, now=now())

    @app.get("/schemes")
    def schemes(actor: Actor = Depends(actor_dep)) -> list[dict[str, Any]]:
        return [{"scheme": s.scheme, "version": s.version, "documents": [d.id for d in s.required_documents],
                 "officer_inputs": officer_inputs(s), "labels": s.labels, "terms": s.terms} for s in _all_schemes()]

    @app.post("/cases", status_code=201)
    def create_case(body: CreateCase, actor: Actor = Depends(actor_dep),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        case = tools.create_case(session, body.case_id, body.scheme, body.reference_date, body.inputs, actor.name)
        return _case_summary(case)

    @app.get("/cases/{case_id}")
    def case_detail(case_id: str, actor: Actor = Depends(actor_dep),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        return _detail(session, _get_case(session, case_id))

    @app.get("/cases/{case_id}/status")
    def case_status(case_id: str, actor: Actor = Depends(actor_dep),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")   # blockers name internal flags: staff only
        return mask_identifiers(tools.get_case_status(session, case_id, actor=actor.name).model_dump())

    @app.put("/cases/{case_id}/inputs")
    def set_inputs(case_id: str, body: Inputs, actor: Actor = Depends(actor_dep),
                   session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        return {"case_id": case_id, "inputs": tools.update_inputs(session, case_id, body.inputs, actor.name)}

    @app.post("/cases/{case_id}/documents", status_code=201)
    def upload(case_id: str, body: Upload, actor: Actor = Depends(actor_dep),
               session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        _get_case(session, case_id)
        suffix = Path(body.filename).suffix.lower()
        if suffix not in UPLOAD_TYPES:
            raise HTTPException(400, f"Unsupported file type {suffix or '(none)'}; use {sorted(UPLOAD_TYPES)}")
        if len(body.content_base64) > MAX_BASE64_CHARS:                # refuse before decoding
            raise HTTPException(400, "File too large (max 10 MB)")
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "content_base64 is not valid base64") from None
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "File too large (max 10 MB)")
        problem = content_problem(suffix, content)
        if problem:
            raise HTTPException(400, problem)
        path = uploads / case_id / f"{uuid.uuid4().hex}{suffix}"   # server-chosen name: no path from the client
        doc = tools.add_document(session, case_id, body.doc_type, str(path), actor.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"id": doc.id, "case_id": case_id, "doc_type": doc.doc_type}

    @app.post("/cases/{case_id}/documents/{document_id}/extract")
    def extract(case_id: str, document_id: int, actor: Actor = Depends(actor_dep),
                session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        doc = session.get(Document, document_id)
        if doc is None or doc.case_id != case_id:
            raise tools.UnknownCase(f"Document {document_id} not found in case {case_id}")
        try:
            provider = extraction_factory() if extraction_factory else None
        except ProviderError as exc:
            raise HTTPException(503, f"No extraction provider available ({exc.kind})") from None
        if provider is None:
            raise HTTPException(503, "No extraction provider configured")
        result = tools.extract_document(session, document_id, provider, actor=actor.name, cross_check=second_reader())
        return mask_identifiers(result.model_dump(mode="json"))

    @app.post("/cases/{case_id}/run")
    def run(case_id: str, actor: Actor = Depends(actor_dep), session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        _get_case(session, case_id)
        try:
            llm = agent_llm_factory() if agent_llm_factory else _NoLLM("no agent LLM configured")
        except ProviderError as exc:
            llm = _NoLLM(f"agent LLM unavailable ({exc.kind})")
        try:
            extraction = extraction_factory() if extraction_factory else None
        except ProviderError:
            extraction = None
        return mask_identifiers(run_agent(session, case_id, llm, extraction=extraction,
                                          cross_check=second_reader() if extraction else None).model_dump(mode="json"))

    @app.post("/cases/{case_id}/decision")
    def decide(case_id: str, body: DecisionIn, actor: Actor = Depends(actor_dep),
               session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "officer")
        return tools.record_officer_decision(session, case_id, role=actor.role, officer_id=actor.user,
                                             decision=body.decision, comment=body.comment,
                                             confirmed=body.confirmed_fields,
                                             resolutions=body.resolutions).model_dump()

    @app.get("/cases/{case_id}/notice")
    def notice_preview(case_id: str, language: str = "en", actor: Actor = Depends(actor_dep),
                       session: Session = Depends(session_dep)) -> dict[str, Any]:
        """Preview a "documents needed" notice. Officer only; changes nothing."""
        _require(actor, "officer")
        return mask_identifiers(tools.preview_notice(session, case_id, role=actor.role, language=language).model_dump())

    @app.post("/cases/{case_id}/notice")
    def notice_send(case_id: str, body: NoticeIn, actor: Actor = Depends(actor_dep),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        """Send it: stored, audit-logged, case moves to needs_info. Officer only. Not a decision."""
        _require(actor, "officer")
        return mask_identifiers(tools.send_notice(session, case_id, role=actor.role, officer_id=actor.user,
                                                  language=body.language).model_dump())

    def _known_scheme(name: str) -> None:
        if not is_scheme(name):
            raise HTTPException(404, f"Unknown scheme {name!r}")

    @app.get("/simulate/{scheme}")
    def simulator_knobs(scheme: str, actor: Actor = Depends(actor_dep)) -> dict[str, Any]:
        _require(actor, "officer", "admin")
        _known_scheme(scheme)
        s = load_scheme_by_name(scheme)
        return {"scheme": scheme, "rules_version": s.version, "labels": s.labels,
                "knobs": [k.model_dump() for k in knobs(s)]}

    @app.post("/simulate")
    def run_simulation(body: SimulateIn, actor: Actor = Depends(actor_dep),
                       session: Session = Depends(session_dep)) -> dict[str, Any]:
        """Read-only what-if over the synthetic set. Never edits the YAML."""
        _require(actor, "officer", "admin")
        _known_scheme(body.scheme)
        try:
            result = simulate(body.scheme, body.name, body.value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        log_action(session, None, actor.name, "rule_simulation",
                   {"scheme": body.scheme, "name": body.name, "original_value": result.original_value,
                    "new_value": result.new_value, "changed_count": result.changed_count}, result.rules_version)
        session.commit()
        return result.model_dump()

    @app.get("/cases/{case_id}/award")
    def award(case_id: str, actor: Actor = Depends(actor_dep), session: Session = Depends(session_dep)) -> dict[str, Any]:
        """Award letter / case summary for an approved case. Every value comes from stored results."""
        _require(actor, "officer")
        case = _get_case(session, case_id)
        if case.status != "approved":
            raise HTTPException(409, f"Case {case_id} is {case.status}; an award letter is only for approved cases")
        scheme = load_scheme_by_name(case.scheme)
        decision = (session.query(AuditLog).filter_by(case_id=case_id, action="officer_decision")
                    .order_by(AuditLog.id.desc()).first())
        docs = load_case(session, case_id).documents
        field = lambda doc, name: docs[doc].fields[name].value if doc in docs and name in docs[doc].fields else None
        items = session.query(CompensationItemRow).filter_by(case_id=case_id).all()
        letter = mask_identifiers({
            "case_id": case.id, "scheme": case.scheme, "labels": scheme.labels, "terms": scheme.terms, "demo": True,
            "applicant_name": field("application", "name"), "applicant_id": field("identity_proof", "id_number"),
            "decision": {"decision": "approve", "officer_id": case.officer_id,
                         "date": india_date(decision.ts) if decision else None},
            "rules_version": scheme.version,
            "rule_results": [{"rule_id": r.rule_id, "status": r.status, "clause": r.clause, "reason": r.reason}
                             for r in session.query(RuleResultRow).filter_by(case_id=case_id)],
            "items": [{"component": i.component, "amount": i.amount, "formula_note": i.formula_note} for i in items],
            "total": round(sum(i.amount for i in items), 2),
            "generated_at": iso_utc(now()),
        })
        log_action(session, case_id, actor.name, "award_letter_viewed", {"total": letter["total"]}, scheme.version)
        session.commit()
        return letter

    @app.get("/cases/{case_id}/audit")
    def audit(case_id: str, actor: Actor = Depends(actor_dep),
              session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
        _require(actor, "officer")
        _get_case(session, case_id)
        rows = session.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id)
        return mask_identifiers([{"id": r.id, "ts": iso_utc(r.ts), "actor": r.actor, "action": r.action,
                                  "rules_version": r.rules_version, "payload": json.loads(r.payload_json)}
                                 for r in rows])

    return app


def _default_llm() -> Any:
    from app.env_file import load_env_file
    from app.providers.gemini_agent import GeminiAgentLLM
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    return GeminiAgentLLM()


def _default_cross_check() -> Any:
    from app.providers.tesseract import TesseractBaselineProvider, tesseract_available
    return TesseractBaselineProvider() if tesseract_available() else None


def _default_extraction() -> Any:
    from app.env_file import load_env_file
    from app.providers.gemini import GeminiProvider
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    return GeminiProvider()


def _default_sahayak() -> Any:
    from app.env_file import load_env_file
    from app.providers.gemini_sahayak import GeminiSahayak
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    return GeminiSahayak()


app = create_app(agent_llm_factory=_default_llm, extraction_factory=_default_extraction,
                 cross_check_factory=_default_cross_check, sahayak_llm_factory=_default_sahayak,
                 citizen_secret=default_citizen_secret(DOTENV), auth_secret=env_value(AUTH_ENV, DOTENV),
                 demo_insecure=env_value(INSECURE_ENV, DOTENV) == "1")
