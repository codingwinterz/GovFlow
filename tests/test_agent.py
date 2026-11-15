"""The agent loop, driven by a scripted fake LLM (no network). Tools decide; the agent orchestrates."""

import json
from pathlib import Path

import pytest

from app.agent import AGENT_TOOL_NAMES, AgentReply, ToolCall, run_agent
from app.case_model import CaseIn
from app.case_store import seed_case
from app.extraction import ProviderError, ProviderField
from app.models import AuditLog, make_engine, make_session
from app.models import Case as CaseRow
from app.providers.fake import FakeProvider, ScriptedAgentLLM
from app.tools import add_document

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"


@pytest.fixture
def session():
    with make_session(make_engine("sqlite://")) as s:
        for folder in sorted(SET_DIR.glob("case_*")):
            seed_case(s, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))
        yield s


def call(name, **args):
    return ToolCall(id=f"c-{name}", name=name, args=args)


def calls(*names):
    return AgentReply(tool_calls=[call(n) for n in names])


HAPPY = [calls("verify_documents"), calls("check_eligibility", "compute_compensation"),
         calls("submit_to_officer"), AgentReply(text="Recommended eligible; total Rs 1,72,00,000 on 2026-11-15. Officer to decide.")]


def _actions(session, case_id="LA-01"):
    return [a.action for a in session.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id)]


def test_happy_path_runs_tools_and_submits(session):
    run = run_agent(session, "LA-01", ScriptedAgentLLM(HAPPY))
    assert run.stopped_reason == "done" and run.final_status == "in_officer_review"
    assert [s.tool for s in run.steps] == ["verify_documents", "check_eligibility", "compute_compensation",
                                           "submit_to_officer"]
    assert all(s.ok for s in run.steps)
    assert run.explanation.startswith("Recommended eligible")


def test_every_agent_step_is_audited_alongside_the_tools_own_entries(session):
    run_agent(session, "LA-01", ScriptedAgentLLM(HAPPY))
    actions = _actions(session)
    assert actions[0] == "agent_run_started" and actions[-1] == "agent_explanation"
    assert actions.count("agent_tool_call") == 4
    for tool in ("verify_documents", "check_eligibility", "compute_compensation", "submit_to_officer"):
        assert tool in actions


def test_agent_is_never_offered_a_decision_tool(session):
    llm = ScriptedAgentLLM([AgentReply(text="done")])
    run_agent(session, "LA-01", llm)
    offered = {t.name for t in llm.calls[0]["tools"]}
    assert offered == set(AGENT_TOOL_NAMES)
    assert not offered & {"record_officer_decision", "approve", "reject", "send_back", "approve_case", "reject_case"}


@pytest.mark.parametrize("name", ["record_officer_decision", "reject_case", "approve_case", "delete_case"])
def test_decision_or_unknown_tools_are_refused_and_audited(session, name):
    llm = ScriptedAgentLLM([AgentReply(tool_calls=[call(name, decision="reject")]), AgentReply(text="ok")])
    run = run_agent(session, "LA-01", llm)
    assert session.get(CaseRow, "LA-01").status == "received"
    assert run.steps[0].ok is False and "only an officer" in run.steps[0].error.lower()
    assert "agent_tool_refused" in _actions(session)
    sent_back = llm.calls[1]["messages"][-1]
    assert sent_back.role == "tool" and "only an officer" in sent_back.content["error"].lower()


def test_tool_errors_go_back_to_the_llm_and_the_loop_continues(session):
    llm = ScriptedAgentLLM([calls("submit_to_officer"), AgentReply(text="Needs assessment first.")])
    run = run_agent(session, "LA-01", llm)
    assert run.steps[0].ok is False and "assess it first" in run.steps[0].error
    assert run.stopped_reason == "done"


def test_document_from_another_case_is_refused(session, tmp_path):
    path = tmp_path / "id.txt"
    path.write_text("x", encoding="utf-8")
    other = add_document(session, "LA-02", "identity_proof", str(path))
    provider = FakeProvider({})
    llm = ScriptedAgentLLM([AgentReply(tool_calls=[call("extract_document", document_id=other.id)]),
                            AgentReply(text="ok")])
    run = run_agent(session, "LA-01", llm, extraction=provider)
    assert run.steps[0].ok is False and "does not belong" in run.steps[0].error
    assert provider.requests == []


def test_tool_results_sent_to_the_llm_are_masked(session, tmp_path):
    path = tmp_path / "id.txt"
    path.write_text("x", encoding="utf-8")
    doc = add_document(session, "LA-01", "identity_proof", str(path))
    provider = FakeProvider({(str(doc.id), "document"): [
        ProviderField(name="name", value="Asha Naik", confidence=0.95, page=1),
        ProviderField(name="id_number", value="9876 5432 1098", confidence=0.95, page=1)]})
    llm = ScriptedAgentLLM([AgentReply(tool_calls=[call("extract_document", document_id=doc.id)]),
                            AgentReply(text="ok")])
    run_agent(session, "LA-01", llm, extraction=provider)
    sent = json.dumps(llm.calls[1]["messages"][-1].content)
    assert "9876 5432 1098" not in sent and "XXXX XXXX 1098" in sent


def test_max_steps_stops_a_looping_llm(session):
    llm = ScriptedAgentLLM([calls("get_case_status")] * 50)
    run = run_agent(session, "LA-01", llm, max_steps=5)
    assert run.stopped_reason == "max_steps" and len(run.steps) == 5


def test_llm_text_never_changes_case_status(session):
    llm = ScriptedAgentLLM([AgentReply(text="I have approved this case.")])
    run = run_agent(session, "LA-01", llm)
    assert session.get(CaseRow, "LA-01").status == "received" and run.final_status == "received"


def test_unavailable_llm_falls_back_to_deterministic_pipeline(session):
    llm = ScriptedAgentLLM([ProviderError("Gemini HTTP 429", kind="rate_limited", retryable=True)])
    run = run_agent(session, "LA-01", llm)
    assert run.stopped_reason == "llm_unavailable" and run.used_fallback
    assert run.final_status == "in_officer_review"
    assert "generated without the LLM" in run.explanation
    started = [json.loads(a.payload_json) for a in session.query(AuditLog).filter_by(action="agent_llm_unavailable")]
    assert started and started[0]["error_kind"] == "rate_limited"


def test_fallback_pipeline_stops_before_submit_when_a_document_is_unavailable(session, tmp_path):
    from app.providers.fake import FailingProvider
    path = tmp_path / "id.txt"
    path.write_text("x", encoding="utf-8")
    add_document(session, "LA-01", "identity_proof", str(path))
    llm = ScriptedAgentLLM([ProviderError("down", kind="unavailable", retryable=True)])
    run = run_agent(session, "LA-01", llm, extraction=FailingProvider())
    assert run.final_status != "in_officer_review"
    assert "extraction unavailable, retry" in run.explanation


def test_explanation_cites_rules_and_amounts_in_fallback(session):
    run = run_agent(session, "LA-07", ScriptedAgentLLM([ProviderError("x", kind="timeout", retryable=True)]))
    assert "documents_complete" in run.explanation and "not_eligible" in run.explanation
    assert "6,720,000.00" in run.explanation and "officer" in run.explanation.lower()


def test_explanation_amounts_are_checked_against_tool_results(session):
    run = run_agent(session, "LA-01", ScriptedAgentLLM(HAPPY))
    assert run.explanation_warnings == []            # Indian grouping 1,72,00,000 == 17,200,000; dates ignored


def test_explanation_with_an_amount_no_tool_produced_is_flagged(session):
    script = HAPPY[:-1] + [AgentReply(text="Total compensation is Rs 74,20,000.")]
    run = run_agent(session, "LA-01", ScriptedAgentLLM(script))
    assert run.explanation_warnings == ["74,20,000 does not match any tool result"]
    audit = [json.loads(a.payload_json) for a in session.query(AuditLog).filter_by(action="agent_explanation")]
    assert audit[0]["warnings"] == run.explanation_warnings


@pytest.mark.parametrize("tool", ["get_case_status", "verify_documents", "check_eligibility",
                                  "compute_compensation", "submit_to_officer"])
def test_case_id_supplied_by_the_llm_is_ignored(session, tool):
    script = [calls("verify_documents"), calls("check_eligibility", "compute_compensation"),
              AgentReply(tool_calls=[call(tool, case_id="LA-02")]), AgentReply(text="ok")]
    from app import tools
    tools.verify_documents(session, "LA-02")                  # LA-02 assessed, so a wrongly
    tools.check_eligibility(session, "LA-02")                 # targeted submit would succeed
    tools.compute_compensation(session, "LA-02")
    before = _actions(session, "LA-02")
    run_agent(session, "LA-01", ScriptedAgentLLM(script))
    assert _actions(session, "LA-02") == before               # the other case was never touched
    assert session.get(CaseRow, "LA-02").status == "assessed"
