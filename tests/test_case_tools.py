"""DB-backed assessment, submission, status and officer-decision tools, against the fixed synthetic set."""

import json
from pathlib import Path

import pytest

from app.case_model import CaseIn
from app.case_store import seed_case
from app.models import AuditLog, CompensationItemRow, Document, RuleResultRow, make_engine, make_session
from app.models import Case as CaseRow
from app.providers.fake import FailingProvider
from app.tools import (
    ToolError, add_document, check_eligibility, compute_compensation, extract_document, get_case_status,
    record_officer_decision, submit_to_officer, verify_documents,
)

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
EXPECTED = {json.loads((f / "case.json").read_text(encoding="utf-8"))["case_id"]:
            json.loads((f / "expected.json").read_text(encoding="utf-8")) for f in sorted(SET_DIR.glob("case_*"))}


@pytest.fixture
def session():
    with make_session(make_engine("sqlite://")) as s:
        for folder in sorted(SET_DIR.glob("case_*")):
            seed_case(s, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))
        yield s


def _audits(session, case_id, action=None):
    rows = session.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id).all()
    return [r for r in rows if action is None or r.action == action]


def _assess(session, case_id):
    verify_documents(session, case_id)
    return check_eligibility(session, case_id), compute_compensation(session, case_id)


def _to_review(session, case_id="LA-01"):
    _assess(session, case_id)
    submit_to_officer(session, case_id)


# --- assessment matches the hand-computed expected outcomes -------------------------

@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_db_tools_reproduce_expected_outcomes(session, case_id):
    exp = EXPECTED[case_id]
    eligibility, compensation = _assess(session, case_id)
    assert {r.rule_id: r.status for r in eligibility.results} == exp["eligibility"]["rules"]
    assert eligibility.overall == exp["eligibility"]["overall"]
    assert compensation.status == exp["compensation"]["status"]
    assert {i.component: i.amount for i in compensation.items} == pytest.approx(exp["compensation"]["items"],
                                                                                abs=0.005)
    stored = {r.component: r.amount for r in session.query(CompensationItemRow).filter_by(case_id=case_id)}
    assert stored == pytest.approx(exp["compensation"]["items"], abs=0.005)
    rows = {r.rule_id: (r.status, r.clause, r.rules_version) for r in session.query(RuleResultRow).filter_by(case_id=case_id)}
    assert {k: v[0] for k, v in rows.items()} == exp["eligibility"]["rules"]
    assert all(v[1] and v[2] == "0.1.0" for v in rows.values())        # every result cites clause + version


def test_rerunning_assessment_replaces_rows_instead_of_duplicating(session):
    _assess(session, "LA-01")
    _assess(session, "LA-01")
    assert session.query(RuleResultRow).filter_by(case_id="LA-01").count() == 5
    assert session.query(CompensationItemRow).filter_by(case_id="LA-01").count() == 4


def test_every_tool_call_is_audited_with_rules_version(session):
    _to_review(session)
    get_case_status(session, "LA-01")
    actions = [(a.action, a.rules_version) for a in _audits(session, "LA-01")]
    assert [a for a, _ in actions] == ["verify_documents", "check_eligibility", "compute_compensation",
                                       "submit_to_officer", "get_case_status"]
    assert all(v == "0.1.0" for _, v in actions)


def test_assessment_moves_status_to_assessed_only_when_both_parts_ran(session):
    verify_documents(session, "LA-01")
    check_eligibility(session, "LA-01")
    assert session.get(CaseRow, "LA-01").status == "verified"
    compute_compensation(session, "LA-01")
    assert session.get(CaseRow, "LA-01").status == "assessed"


# --- submission and queue ---------------------------------------------------------------

def test_submit_requires_assessment(session):
    with pytest.raises(ToolError, match="assess"):
        submit_to_officer(session, "LA-01")


def test_submit_puts_case_in_officer_review_with_queue_position(session):
    _assess(session, "LA-01")
    result = submit_to_officer(session, "LA-01")
    assert result.queue_position == 1 and session.get(CaseRow, "LA-01").status == "in_officer_review"


def test_flagged_cases_go_ahead_of_clean_ones_in_the_queue(session):
    _to_review(session, "LA-01")                      # clean
    _assess(session, "LA-07")                         # missing document -> flagged
    assert submit_to_officer(session, "LA-07").queue_position == 1


def test_not_eligible_is_still_submitted_as_a_recommendation(session):
    _assess(session, "LA-07")
    submit_to_officer(session, "LA-07")
    assert session.get(CaseRow, "LA-07").status == "in_officer_review"     # the agent never rejects


def test_submit_refuses_while_a_document_is_unavailable(session, tmp_path):
    path = tmp_path / "id.txt"
    path.write_text("x", encoding="utf-8")
    doc = add_document(session, "LA-01", "identity_proof", str(path))
    extract_document(session, doc.id, FailingProvider())
    _assess(session, "LA-01")
    with pytest.raises(ToolError, match="extraction unavailable, retry"):
        submit_to_officer(session, "LA-01")


# --- status ----------------------------------------------------------------------------

@pytest.mark.parametrize("steps, status, next_step", [
    ([], "received", "extract"),
    (["verify"], "verified", "check eligibility"),
    (["verify", "assess"], "assessed", "submit"),
    (["verify", "assess", "submit"], "in_officer_review", "officer decision"),
])
def test_status_reports_next_step(session, steps, status, next_step):
    if "verify" in steps:
        verify_documents(session, "LA-01")
    if "assess" in steps:
        check_eligibility(session, "LA-01")
        compute_compensation(session, "LA-01")
    if "submit" in steps:
        submit_to_officer(session, "LA-01")
    result = get_case_status(session, "LA-01")
    assert result.status == status and next_step in result.next_step


def test_status_lists_blockers_with_their_source(session):
    _assess(session, "LA-07")
    blockers = get_case_status(session, "LA-07").blockers
    assert any("missing_document" in b and "mutation_record" in b for b in blockers)
    assert any(b.startswith("recommendation: not_eligible") for b in blockers)


def test_status_of_unknown_case_is_a_tool_error(session):
    with pytest.raises(ToolError, match="Unknown case"):
        get_case_status(session, "LA-99")


# --- officer decisions: only the officer role decides -----------------------------------

@pytest.mark.parametrize("role", ["agent", "clerk", "citizen", "system", ""])
def test_only_officer_role_can_decide(session, role):
    _to_review(session)
    with pytest.raises(PermissionError):
        record_officer_decision(session, "LA-01", role=role, officer_id="O-1", decision="approve")
    assert session.get(CaseRow, "LA-01").status == "in_officer_review"


@pytest.mark.parametrize("decision, status", [("approve", "approved"), ("reject", "rejected"),
                                              ("send_back", "needs_info")])
def test_officer_decision_sets_status_and_is_audited(session, decision, status):
    _to_review(session)
    record_officer_decision(session, "LA-01", role="officer", officer_id="O-7", decision=decision, comment="checked")
    case = session.get(CaseRow, "LA-01")
    assert case.status == status and case.officer_id == "O-7"
    (row,) = _audits(session, "LA-01", "officer_decision")
    assert row.actor == "officer:O-7" and json.loads(row.payload_json)["decision"] == decision
    assert row.rules_version == "0.1.0"


@pytest.mark.parametrize("decision", ["reject", "send_back"])
def test_reject_and_send_back_need_a_comment(session, decision):
    _to_review(session)
    with pytest.raises(ToolError, match="comment"):
        record_officer_decision(session, "LA-01", role="officer", officer_id="O-1", decision=decision, comment=" ")


def test_decision_needs_case_in_officer_review(session):
    _assess(session, "LA-01")
    with pytest.raises(ToolError, match="in_officer_review"):
        record_officer_decision(session, "LA-01", role="officer", officer_id="O-1", decision="approve")


def test_unknown_decision_is_refused(session):
    _to_review(session)
    with pytest.raises(ToolError, match="decision"):
        record_officer_decision(session, "LA-01", role="officer", officer_id="O-1", decision="delete")


# --- new documents reopen a case ----------------------------------------------------------

def test_new_document_after_send_back_reopens_the_case(session, tmp_path):
    _to_review(session)
    record_officer_decision(session, "LA-01", role="officer", officer_id="O-1", decision="send_back",
                            comment="upload a clearer identity proof")
    path = tmp_path / "id.txt"
    path.write_text("x", encoding="utf-8")
    add_document(session, "LA-01", "identity_proof", str(path))
    assert session.get(CaseRow, "LA-01").status == "received"
    assert [a.action for a in _audits(session, "LA-01")][-1] == "add_document"


@pytest.mark.parametrize("closed", ["approved", "rejected"])
def test_documents_cannot_be_added_to_a_closed_case(session, tmp_path, closed):
    session.get(CaseRow, "LA-01").status = closed
    with pytest.raises(ToolError, match="closed"):
        add_document(session, "LA-01", "identity_proof", str(tmp_path / "x.txt"))


def test_unknown_document_type_is_refused(session, tmp_path):
    from app.tools import InvalidInput
    with pytest.raises(InvalidInput, match="document type"):
        add_document(session, "LA-01", "selfie", str(tmp_path / "x.txt"))
