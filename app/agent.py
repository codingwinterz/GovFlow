"""The agent: an LLM tool-calling loop that orchestrates the deterministic tools and explains results.

Safety comes from structure, not from the prompt:
- the tool registry has no approve/reject/send-back tool, so the agent cannot decide a case (rule 2);
- tools are bound to one case: the LLM never supplies a case id, and a document id must belong to it;
- eligibility and money come only from tool results (rule 1); amounts in the LLM's explanation
  that no tool produced are flagged;
- tool results are masked before they reach the LLM (rule 7), and every step is audited (rule 5).
If the LLM is unavailable, a deterministic pipeline runs the same tools and writes a plain summary.
"""

import re
from typing import Any, Callable, Literal, Optional, Protocol

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import tools
from app.audit import log_action
from app.extraction import ExtractionProvider, OcrEngine, ProviderError
from app.models import Case, CompensationItemRow, Document, RuleResultRow
from app.privacy import mask_identifiers
from app.rules_engine import overall_from
from app.rules_loader import load_scheme_by_name

MAX_STEPS = 12

SYSTEM_PROMPT = """You are GovFlow's case-processing assistant for government officers.
You work on one case, using only the tools provided. Rules you must follow:
- Tools decide. Never decide eligibility, compensation or approval yourself, and never invent numbers.
- You cannot approve, reject or send back a case. Only an officer can. Do not say a case is approved or rejected.
- Typical order: get_case_status, extract_document for unread documents, verify_documents,
  check_eligibility, compute_compensation, then submit_to_officer.
- If a tool returns an error, explain it; do not retry the same call more than once.
- Finish with a short plain-language explanation for the officer: the recommendation, the rule ids and
  clauses behind it, the compensation total and items exactly as the tools returned them, and any blockers.
"""


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = {}


class AgentReply(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = []
    raw: Any = None            # provider-native message, echoed back verbatim (e.g. Gemini thought signatures)


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = []
    tool_call_id: Optional[str] = None
    name: Optional[str] = None            # tool name, for role="tool"
    content: Optional[dict[str, Any]] = None
    raw: Any = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: Optional[dict[str, Any]] = None   # JSON schema; None = no arguments


class AgentLLM(Protocol):
    name: str
    model: Optional[str]

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> AgentReply: ...


class Step(BaseModel):
    tool: str
    args: dict[str, Any]
    ok: bool
    error: Optional[str] = None


class AgentRun(BaseModel):
    case_id: str
    llm: str
    steps: list[Step]
    explanation: str
    explanation_warnings: list[str]
    stopped_reason: Literal["done", "max_steps", "llm_unavailable"]
    used_fallback: bool
    final_status: str


TOOL_SPECS = [
    ToolSpec(name="get_case_status", description="Current status, next step and blockers of this case."),
    ToolSpec(name="extract_document", description="Read one uploaded document of this case and store its fields.",
             parameters={"type": "object", "properties": {"document_id": {"type": "integer"}},
                         "required": ["document_id"]}),
    ToolSpec(name="verify_documents", description="Cross-check this case's documents; returns flags."),
    ToolSpec(name="check_eligibility", description="Run the scheme's eligibility rules; per-rule results with clauses."),
    ToolSpec(name="compute_compensation", description="Compute the itemised compensation from the scheme formulas."),
    ToolSpec(name="submit_to_officer", description="Put the assessed case in the officer queue for a decision."),
]
AGENT_TOOL_NAMES = tuple(t.name for t in TOOL_SPECS)
REFUSAL = "Tool not available to the agent. Only an officer can approve, reject or send back a case."


class _Context(BaseModel, arbitrary_types_allowed=True):
    session: Session
    case_id: str
    extraction: Optional[Any] = None
    ocr: Optional[Any] = None
    actor: str = "agent"


def _extract(ctx: _Context, args: dict[str, Any]) -> BaseModel:
    if ctx.extraction is None:
        raise tools.ToolError("No extraction provider is configured")
    try:
        doc_id = int(args.get("document_id"))
    except (TypeError, ValueError):
        raise tools.ToolError("document_id must be an integer") from None
    doc = ctx.session.get(Document, doc_id)
    if doc is None or doc.case_id != ctx.case_id:
        raise tools.ToolError(f"Document {doc_id} does not belong to case {ctx.case_id}")
    return tools.extract_document(ctx.session, doc_id, ctx.extraction, ctx.ocr, actor=ctx.actor)


RUNNERS: dict[str, Callable[[_Context, dict[str, Any]], BaseModel]] = {
    "get_case_status": lambda c, a: tools.get_case_status(c.session, c.case_id, actor=c.actor),
    "extract_document": _extract,
    "verify_documents": lambda c, a: tools.verify_documents(c.session, c.case_id, actor=c.actor),
    "check_eligibility": lambda c, a: tools.check_eligibility(c.session, c.case_id, actor=c.actor),
    "compute_compensation": lambda c, a: tools.compute_compensation(c.session, c.case_id, actor=c.actor),
    "submit_to_officer": lambda c, a: tools.submit_to_officer(c.session, c.case_id, actor=c.actor),
}


def _rules_version(ctx: _Context) -> str:
    return load_scheme_by_name(ctx.session.get(Case, ctx.case_id).scheme).version


def _run_tool(ctx: _Context, call: ToolCall) -> tuple[Step, dict[str, Any]]:
    version = _rules_version(ctx)
    if call.name not in RUNNERS:
        log_action(ctx.session, ctx.case_id, ctx.actor, "agent_tool_refused", call.model_dump(), version)
        ctx.session.commit()
        return Step(tool=call.name, args=call.args, ok=False, error=REFUSAL), {"error": REFUSAL}
    try:
        result = mask_identifiers(RUNNERS[call.name](ctx, call.args).model_dump(mode="json"))
        step = Step(tool=call.name, args=call.args, ok=True)
    except (tools.ToolError, PermissionError) as exc:
        ctx.session.rollback()
        result, step = {"error": str(exc)}, Step(tool=call.name, args=call.args, ok=False, error=str(exc))
    log_action(ctx.session, ctx.case_id, ctx.actor, "agent_tool_call", step.model_dump(), version)
    ctx.session.commit()
    return step, result


# --- explanation check: amounts must come from tool results ----------------------------------

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\w.])\d{4,}(?:\.\d+)?")


def _numbers(value: Any) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {float(value)}
    if isinstance(value, str):
        return {float(m.replace(",", "")) for m in _NUMBER.findall(_DATE.sub(" ", value))}
    if isinstance(value, dict):
        return set().union(*(_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_numbers(v) for v in value)) if value else set()
    return set()


def unverified_numbers(text: str, results: list[dict[str, Any]]) -> list[str]:
    """Numbers of 4+ digits in the explanation that appear in no tool result (dates ignored)."""
    known = _numbers(results)
    return [f"{token} does not match any tool result" for token in _NUMBER.findall(_DATE.sub(" ", text))
            if not any(abs(float(token.replace(",", "")) - k) < 0.005 for k in known)]


# --- deterministic fallback ------------------------------------------------------------------

def _money(amount: float) -> str:
    return f"Rs {amount:,.2f}"


def deterministic_summary(session: Session, case_id: str, reason: str) -> str:
    status = tools.get_case_status(session, case_id, actor="pipeline")
    lines = [f"Summary generated without the LLM ({reason}). This is a recommendation; only an officer "
             "can approve, reject or send back the case.",
             f"Status: {status.status}. Next step: {status.next_step}."]
    rules = session.query(RuleResultRow).filter_by(case_id=case_id).all()
    if rules:
        lines.append(f"Eligibility recommendation: {overall_from([r.status for r in rules])} "
                     f"(rules version {rules[0].rules_version})")
        lines += [f"- {r.rule_id}: {r.status} [{r.clause}] {r.reason}" for r in rules]
    items = session.query(CompensationItemRow).filter_by(case_id=case_id).all()
    if items:
        lines.append(f"Compensation total: {_money(sum(i.amount for i in items))}")
        lines += [f"- {i.component}: {_money(i.amount)} ({i.formula_note})" for i in items]
    if status.blockers:
        lines.append("Blockers:")
        lines += [f"- {b}" for b in status.blockers]
    return "\n".join(lines)


def run_pipeline(session: Session, case_id: str, extraction: Optional[ExtractionProvider] = None,
                 ocr: Optional[OcrEngine] = None, actor: str = "pipeline") -> list[Step]:
    """The same tools in the standard order, without an LLM."""
    ctx = _Context(session=session, case_id=case_id, extraction=extraction, ocr=ocr, actor=actor)
    steps: list[Step] = []
    latest: dict[str, Document] = {}
    for doc in session.query(Document).filter_by(case_id=case_id).order_by(Document.id):
        latest[doc.doc_type] = doc
    if extraction is not None:
        for doc in latest.values():
            if not doc.file_path.startswith("seed:") and doc.extraction_status != "ok":
                steps.append(_run_tool(ctx, ToolCall(id=f"p-{doc.id}", name="extract_document",
                                                     args={"document_id": doc.id}))[0])
    for name in ("verify_documents", "check_eligibility", "compute_compensation"):
        steps.append(_run_tool(ctx, ToolCall(id=f"p-{name}", name=name))[0])
    if session.get(Case, case_id).status == "assessed":
        steps.append(_run_tool(ctx, ToolCall(id="p-submit", name="submit_to_officer"))[0])
    return steps


# --- the loop ----------------------------------------------------------------------------------

def run_agent(session: Session, case_id: str, llm: AgentLLM, extraction: Optional[ExtractionProvider] = None,
              ocr: Optional[OcrEngine] = None, max_steps: int = MAX_STEPS, actor: str = "agent") -> AgentRun:
    ctx = _Context(session=session, case_id=case_id, extraction=extraction, ocr=ocr, actor=actor)
    if session.get(Case, case_id) is None:
        raise tools.ToolError(f"Unknown case {case_id}")
    version = _rules_version(ctx)
    log_action(session, case_id, actor, "agent_run_started", {"llm": llm.name, "model": llm.model}, version)
    session.commit()
    messages = [Message(role="user", text=f"Process case {case_id} and explain the result for the officer.")]
    steps: list[Step] = []
    results: list[dict[str, Any]] = []
    explanation, stopped = "", "max_steps"
    while len(steps) < max_steps:
        try:
            reply = llm.complete(SYSTEM_PROMPT, messages, TOOL_SPECS)
        except ProviderError as exc:
            log_action(session, case_id, actor, "agent_llm_unavailable",
                       {"error_kind": exc.kind, "error": str(exc)}, version)
            session.commit()
            stopped = "llm_unavailable"
            break
        messages.append(Message(role="assistant", text=reply.text, tool_calls=reply.tool_calls, raw=reply.raw))
        if not reply.tool_calls:
            explanation, stopped = reply.text, "done"
            break
        for call in reply.tool_calls[: max_steps - len(steps)]:
            step, result = _run_tool(ctx, call)
            steps.append(step)
            results.append(result)
            messages.append(Message(role="tool", tool_call_id=call.id, name=call.name, content=result))

    used_fallback = stopped == "llm_unavailable"
    if used_fallback:
        steps += run_pipeline(session, case_id, extraction, ocr, actor="pipeline")
        explanation = deterministic_summary(session, case_id, "LLM unavailable")
        warnings: list[str] = []
    else:
        warnings = unverified_numbers(explanation, results)
    log_action(session, case_id, actor, "agent_explanation",
               {"text": explanation, "warnings": warnings, "used_fallback": used_fallback,
                "stopped_reason": stopped}, version)
    session.commit()
    return AgentRun(case_id=case_id, llm=llm.name, steps=steps, explanation=explanation,
                    explanation_warnings=warnings, stopped_reason=stopped, used_fallback=used_fallback,
                    final_status=session.get(Case, case_id).status)
