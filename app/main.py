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
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func
from sqlalchemy.orm import Session

from app import tools
from app.agent import AgentReply, run_agent
from app.analytics import analytics
from app.extraction import EXTRACTION_UNAVAILABLE_MESSAGE, ProviderError
from app.models import AuditLog, Case, CompensationItemRow, Document, ExtractedField, RuleResultRow
from app.models import VerificationFlag, make_engine, queue_key
from app.privacy import mask_identifiers
from app.rules_engine import overall_from
from app.rules_loader import RULES_DIR, Scheme, load_scheme_by_name


def officer_inputs(scheme: Scheme) -> list[str]:
    """Officer-entered values the scheme reads as `case.<name>`, in YAML order (no names hardcoded here)."""
    if scheme.compensation is None:
        return []
    names = re.findall(r"\bcase\.([A-Za-z_][A-Za-z0-9_]*)", json.dumps(scheme.compensation.model_dump(by_alias=True)))
    return list(dict.fromkeys(names))


def _all_schemes() -> list[Scheme]:
    return [load_scheme_by_name(p.stem) for p in sorted(RULES_DIR.glob("*.yaml"))]

ROLES = ("citizen", "clerk", "officer")
UPLOAD_TYPES = {".txt", ".png", ".jpg", ".jpeg", ".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"   # gitignored: citizen documents


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


class DecisionIn(BaseModel):
    decision: str
    comment: str = ""


class _NoLLM:
    """Stands in when no agent LLM is configured: run_agent then uses the deterministic pipeline."""
    name, model = "none", None

    def __init__(self, reason: str):
        self.reason = reason

    def complete(self, system, messages, tools_) -> AgentReply:
        raise ProviderError(self.reason, kind="not_configured")


def _actor(x_role: Optional[str] = Header(None), x_user: Optional[str] = Header(None)) -> Actor:
    if x_role not in ROLES or not x_user:
        raise HTTPException(401, "Send X-Role (citizen, clerk or officer) and X-User headers")
    return Actor(role=x_role, user=x_user)


def _require(actor: Actor, *roles: str) -> None:
    if actor.role not in roles:
        raise HTTPException(403, f"Role {actor.role} cannot do this")


# --- read models ---------------------------------------------------------------------------

def _case_summary(c: Case, flags_count: Optional[int] = None) -> dict[str, Any]:
    out = {"case_id": c.id, "scheme": c.scheme, "status": c.status, "confidence_flag": c.confidence_flag,
           "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None, "officer_id": c.officer_id,
           "created_at": c.created_at.isoformat() if c.created_at else None}
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
                   "needs_review": f.confidence < threshold}
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
            "at": row.ts.isoformat()}


def _detail(session: Session, case: Case) -> dict[str, Any]:
    scheme = load_scheme_by_name(case.scheme)
    rules = session.query(RuleResultRow).filter_by(case_id=case.id).all()
    items = session.query(CompensationItemRow).filter_by(case_id=case.id).all()
    return mask_identifiers({
        **_case_summary(case), "reference_date": case.reference_date.isoformat() if case.reference_date else None,
        "inputs": json.loads(case.inputs_json), "rules_version": scheme.version, "labels": scheme.labels,
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
    })


# --- app -----------------------------------------------------------------------------------

def create_app(engine: Optional[Engine] = None, agent_llm_factory: Optional[Callable[[], Any]] = None,
               extraction_factory: Optional[Callable[[], Any]] = None,
               upload_dir: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title="GovFlow", version="0.1.0")
    state: dict[str, Any] = {"engine": engine}
    uploads = Path(upload_dir or DEFAULT_UPLOAD_DIR)

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

    @app.get("/cases")
    def list_cases(status: Optional[str] = None, scheme: Optional[str] = None, actor: Actor = Depends(_actor),
                   session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
        _require(actor, "clerk", "officer")
        query = session.query(Case)
        if status:
            query = query.filter_by(status=status)
        if scheme:
            query = query.filter_by(scheme=scheme)
        counts = dict(session.query(VerificationFlag.case_id, func.count(VerificationFlag.id))
                      .group_by(VerificationFlag.case_id).all())
        cases = sorted(query.all(), key=queue_key)
        return [_case_summary(c, counts.get(c.id, 0)) for c in cases]

    @app.get("/analytics")
    def get_analytics(stuck_days: float = 7, actor: Actor = Depends(_actor),
                      session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        return analytics(session, stuck_days=stuck_days)

    @app.get("/schemes")
    def schemes(actor: Actor = Depends(_actor)) -> list[dict[str, Any]]:
        return [{"scheme": s.scheme, "version": s.version, "documents": [d.id for d in s.required_documents],
                 "officer_inputs": officer_inputs(s), "labels": s.labels} for s in _all_schemes()]

    @app.post("/cases", status_code=201)
    def create_case(body: CreateCase, actor: Actor = Depends(_actor),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        case = tools.create_case(session, body.case_id, body.scheme, body.reference_date, body.inputs, actor.name)
        return _case_summary(case)

    @app.get("/cases/{case_id}")
    def case_detail(case_id: str, actor: Actor = Depends(_actor),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        return _detail(session, _get_case(session, case_id))

    @app.get("/cases/{case_id}/status")
    def case_status(case_id: str, actor: Actor = Depends(_actor),
                    session: Session = Depends(session_dep)) -> dict[str, Any]:
        return mask_identifiers(tools.get_case_status(session, case_id, actor=actor.name).model_dump())

    @app.put("/cases/{case_id}/inputs")
    def set_inputs(case_id: str, body: Inputs, actor: Actor = Depends(_actor),
                   session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        return {"case_id": case_id, "inputs": tools.update_inputs(session, case_id, body.inputs, actor.name)}

    @app.post("/cases/{case_id}/documents", status_code=201)
    def upload(case_id: str, body: Upload, actor: Actor = Depends(_actor),
               session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "clerk", "officer")
        _get_case(session, case_id)
        suffix = Path(body.filename).suffix.lower()
        if suffix not in UPLOAD_TYPES:
            raise HTTPException(400, f"Unsupported file type {suffix or '(none)'}; use {sorted(UPLOAD_TYPES)}")
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "content_base64 is not valid base64") from None
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "File too large (max 10 MB)")
        path = uploads / case_id / f"{uuid.uuid4().hex}{suffix}"   # server-chosen name: no path from the client
        doc = tools.add_document(session, case_id, body.doc_type, str(path), actor.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"id": doc.id, "case_id": case_id, "doc_type": doc.doc_type}

    @app.post("/cases/{case_id}/documents/{document_id}/extract")
    def extract(case_id: str, document_id: int, actor: Actor = Depends(_actor),
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
        result = tools.extract_document(session, document_id, provider, actor=actor.name)
        return mask_identifiers(result.model_dump(mode="json"))

    @app.post("/cases/{case_id}/run")
    def run(case_id: str, actor: Actor = Depends(_actor), session: Session = Depends(session_dep)) -> dict[str, Any]:
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
        return mask_identifiers(run_agent(session, case_id, llm, extraction=extraction).model_dump(mode="json"))

    @app.post("/cases/{case_id}/decision")
    def decide(case_id: str, body: DecisionIn, actor: Actor = Depends(_actor),
               session: Session = Depends(session_dep)) -> dict[str, Any]:
        _require(actor, "officer")
        return tools.record_officer_decision(session, case_id, role=actor.role, officer_id=actor.user,
                                             decision=body.decision, comment=body.comment).model_dump()

    @app.get("/cases/{case_id}/audit")
    def audit(case_id: str, actor: Actor = Depends(_actor),
              session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
        _require(actor, "officer")
        _get_case(session, case_id)
        rows = session.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id)
        return mask_identifiers([{"id": r.id, "ts": r.ts.isoformat(), "actor": r.actor, "action": r.action,
                                  "rules_version": r.rules_version, "payload": json.loads(r.payload_json)}
                                 for r in rows])

    return app


def _default_llm() -> Any:
    from app.env_file import load_env_file
    from app.providers.gemini_agent import GeminiAgentLLM
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    return GeminiAgentLLM()


def _default_extraction() -> Any:
    from app.env_file import load_env_file
    from app.providers.gemini import GeminiProvider
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    return GeminiProvider()


app = create_app(agent_llm_factory=_default_llm, extraction_factory=_default_extraction)
