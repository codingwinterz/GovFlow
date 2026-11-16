"""The HTTP API, called in-process. Roles come from demo headers (X-Role, X-User)."""

import base64
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent import AgentReply, ToolCall
from app.case_model import CaseIn
from app.case_store import seed_case
from app.extraction import ProviderError, ProviderField
from app.main import create_app
from app.models import Base, Document
from app.providers.fake import FailingProvider, FakeProvider, ScriptedAgentLLM
from tests.asgi_client import call

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
OFFICER = {"X-Role": "officer", "X-User": "O-1"}
CLERK = {"X-Role": "clerk", "X-User": "C-1"}
CITIZEN = {"X-Role": "citizen", "X-User": "P-1"}


def _script():
    calls = lambda *n: AgentReply(tool_calls=[ToolCall(id=f"c-{x}", name=x) for x in n])
    return [calls("verify_documents"), calls("check_eligibility", "compute_compensation"),
            calls("submit_to_officer"), AgentReply(text="Recommended eligible. Officer to decide.")]


class Env:
    def __init__(self, tmp_path, llm_factory=None, extraction_factory=None):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as s:
            for folder in sorted(SET_DIR.glob("case_*")):
                seed_case(s, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))
        self.uploads = tmp_path / "uploads"
        self.app = create_app(engine=self.engine, agent_llm_factory=llm_factory,
                              extraction_factory=extraction_factory, upload_dir=self.uploads)

    def __call__(self, method, path, body=None, headers=None):
        return call(self.app, method, path, body, headers)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path, llm_factory=lambda: ScriptedAgentLLM(_script()))


def _upload(env, case_id="LA-01", doc_type="identity_proof", text="Name: Asha Naik", filename="id.txt"):
    return env("POST", f"/cases/{case_id}/documents", {"doc_type": doc_type, "filename": filename,
               "content_base64": base64.b64encode(text.encode()).decode()}, CLERK)


# --- auth -------------------------------------------------------------------------------

def test_missing_role_is_401(env):
    assert env("GET", "/cases")[0] == 401


def test_unknown_role_is_401(env):
    assert env("GET", "/cases", headers={"X-Role": "superuser", "X-User": "x"})[0] == 401


def test_citizen_role_gets_no_staff_endpoints(env):
    # status blockers name internal flags; citizens use POST /public/status instead
    assert env("GET", "/cases/LA-01/status", headers=CITIZEN)[0] == 403
    assert env("GET", "/cases/LA-01", headers=CITIZEN)[0] == 403
    assert env("GET", "/cases", headers=CITIZEN)[0] == 403


def test_health_needs_no_role(env):
    assert env("GET", "/health") == (200, {"status": "ok"})


# --- agent run and officer decision ----------------------------------------------------------

def test_run_agent_then_officer_approves(env):
    status, run = env("POST", "/cases/LA-01/run", headers=CLERK)
    assert status == 200 and run["final_status"] == "in_officer_review" and not run["used_fallback"]
    status, decided = env("POST", "/cases/LA-01/decision", {"decision": "approve"}, OFFICER)
    assert status == 200 and decided["status"] == "approved"
    _, audit = env("GET", "/cases/LA-01/audit", headers=OFFICER)
    (row,) = [a for a in audit if a["action"] == "officer_decision"]
    assert row["actor"] == "officer:O-1"


@pytest.mark.parametrize("headers", [CLERK, CITIZEN])
def test_only_officer_can_decide(env, headers):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    status, body = env("POST", "/cases/LA-01/decision", {"decision": "reject", "comment": "x"}, headers)
    assert status == 403
    assert env("GET", "/cases/LA-01/status", headers=OFFICER)[1]["status"] == "in_officer_review"


def test_decision_in_wrong_state_is_409(env):
    status, body = env("POST", "/cases/LA-01/decision", {"decision": "approve"}, OFFICER)
    assert status == 409 and "in_officer_review" in body["detail"]


def test_reject_without_comment_is_409(env):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    assert env("POST", "/cases/LA-01/decision", {"decision": "reject"}, OFFICER)[0] == 409


def test_run_without_llm_uses_deterministic_fallback(tmp_path):
    env = Env(tmp_path, llm_factory=None)
    status, run = env("POST", "/cases/LA-01/run", headers=CLERK)
    assert status == 200 and run["used_fallback"] and run["final_status"] == "in_officer_review"
    assert "generated without the LLM" in run["explanation"]


def test_run_with_llm_that_fails_to_start_falls_back(tmp_path):
    def broken():
        raise ProviderError("GEMINI_API_KEY is not set", kind="not_configured")
    env = Env(tmp_path, llm_factory=broken)
    assert env("POST", "/cases/LA-01/run", headers=CLERK)[1]["used_fallback"]


def test_unknown_case_is_404(env):
    assert env("GET", "/cases/LA-99", headers=OFFICER)[0] == 404
    assert env("POST", "/cases/LA-99/run", headers=CLERK)[0] == 404


# --- case detail: citations, masking, explanation ----------------------------------------------

def test_case_detail_cites_sources_and_masks_identifiers(env):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    status, d = env("GET", "/cases/LA-01", headers=OFFICER)
    assert status == 200 and d["status"] == "in_officer_review"
    assert {r["rule_id"] for r in d["rule_results"]} >= {"documents_complete", "valid_ownership"}
    assert all(r["clause"] and r["rules_version"] == "0.1.0" for r in d["rule_results"])
    assert d["compensation"]["total"] == pytest.approx(17_200_000, abs=0.005)
    assert all(i["formula_note"] for i in d["compensation"]["items"])
    fields = [f for doc in d["documents"] for f in doc["fields"]]
    assert all(f["document_type"] and f["field"] for f in fields)        # each value names its source
    ids = [f["value"] for f in fields if f["field"] == "id_number"]
    assert ids and all(str(v).startswith("XXXX XXXX ") for v in ids)
    assert d["recommendation"] == "eligible" and d["explanation"]["text"].startswith("Recommended eligible")
    assert "decision" not in d["explanation"]                            # explanation is not a decision


def test_audit_is_officer_only_and_masked(env, tmp_path):
    _upload(env, text="ID 9876 5432 1098")
    assert env("GET", "/cases/LA-01/audit", headers=CLERK)[0] == 403
    _, audit = env("GET", "/cases/LA-01/audit", headers=OFFICER)
    assert audit and all(a["rules_version"] for a in audit)
    assert "9876 5432 1098" not in json.dumps(audit)


def test_queue_lists_cases_in_officer_review_flagged_first(env):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    env("POST", "/cases/LA-07/run", headers=CLERK)              # the scripted LLM is recreated per run
    status, queue = env("GET", "/cases?status=in_officer_review", headers=OFFICER)
    assert status == 200 and [c["case_id"] for c in queue] == ["LA-07", "LA-01"]
    assert queue[0]["confidence_flag"] is True


# --- documents: upload, extraction, retry -------------------------------------------------------

def test_upload_stores_file_inside_upload_dir_and_reopens_case(env):
    status, doc = _upload(env, filename="../../etc/passwd.txt")
    assert status == 201 and doc["doc_type"] == "identity_proof"
    stored = list(env.uploads.rglob("*"))
    files = [p for p in stored if p.is_file()]
    assert len(files) == 1 and env.uploads in files[0].parents and "passwd" not in files[0].name
    assert env("GET", "/cases/LA-01/status", headers=CLERK)[1]["status"] == "received"


@pytest.mark.parametrize("filename", ["x.exe", "x.html", "noext"])
def test_upload_rejects_unsupported_types(env, filename):
    assert _upload(env, filename=filename)[0] == 400


def test_upload_rejects_bad_base64_and_unknown_doc_type(env):
    bad = env("POST", "/cases/LA-01/documents", {"doc_type": "identity_proof", "filename": "a.txt",
              "content_base64": "%%%"}, CLERK)
    assert bad[0] == 400
    assert _upload(env, doc_type="selfie")[0] == 400


def test_citizen_cannot_upload(env):
    status, _ = env("POST", "/cases/LA-01/documents", {"doc_type": "identity_proof", "filename": "a.txt",
                    "content_base64": "eA=="}, CITIZEN)
    assert status == 403


def test_extraction_unavailable_then_retry(tmp_path):
    providers = [FailingProvider(kind="rate_limited")]
    env = Env(tmp_path, extraction_factory=lambda: providers[0])
    _, doc = _upload(env)
    status, result = env("POST", f"/cases/LA-01/documents/{doc['id']}/extract", headers=CLERK)
    assert status == 200 and result["status"] == "extraction_unavailable" and result["retryable"]
    _, d = env("GET", "/cases/LA-01", headers=OFFICER)
    (shown,) = [x for x in d["documents"] if x["id"] == doc["id"]]
    assert shown["message"] == "extraction unavailable, retry" and shown["extraction_error_kind"] == "rate_limited"
    assert "extraction unavailable, retry" in " ".join(env("GET", "/cases/LA-01/status", headers=CLERK)[1]["blockers"])
    providers[0] = FakeProvider({(str(doc["id"]), "document"): [
        ProviderField(name="name", value="Asha Naik", confidence=0.95, page=1)]})
    status, result = env("POST", f"/cases/LA-01/documents/{doc['id']}/extract", headers=CLERK)
    assert status == 200 and result["status"] == "ok"


def test_extract_without_provider_is_503(env):
    _, doc = _upload(env)
    status, body = env("POST", f"/cases/LA-01/documents/{doc['id']}/extract", headers=CLERK)
    assert status == 503 and "extraction" in body["detail"]


def test_extract_document_of_another_case_is_404(env):
    _, doc = _upload(env, case_id="LA-02")
    assert env("POST", f"/cases/LA-01/documents/{doc['id']}/extract", headers=CLERK)[0] == 404


# --- case creation and officer inputs -------------------------------------------------------------

def test_create_case_and_set_inputs(env):
    status, body = env("POST", "/cases", {"case_id": "LA-50", "scheme": "land_acquisition",
                                          "reference_date": "2026-11-15"}, CLERK)
    assert status == 201 and body["status"] == "received"
    status, body = env("PUT", "/cases/LA-50/inputs", {"inputs": {"market_value_per_sqm": 2500}}, OFFICER)
    assert status == 200 and body["inputs"] == {"market_value_per_sqm": 2500}


@pytest.mark.parametrize("case_id", ["../x", "a b", "", "x" * 65])
def test_create_case_rejects_unsafe_ids(env, case_id):
    assert env("POST", "/cases", {"case_id": case_id, "scheme": "land_acquisition",
                                  "reference_date": "2026-11-15"}, CLERK)[0] == 422


def test_create_case_rejects_unknown_scheme_and_duplicates(env):
    assert env("POST", "/cases", {"case_id": "X-1", "scheme": "nope", "reference_date": "2026-11-15"}, CLERK)[0] == 400
    assert env("POST", "/cases", {"case_id": "LA-01", "scheme": "land_acquisition",
                                  "reference_date": "2026-11-15"}, CLERK)[0] == 409


def test_changing_inputs_after_assessment_reopens_assessment(env):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    env("PUT", "/cases/LA-01/inputs", {"inputs": {"market_value_per_sqm": 9999}}, OFFICER)
    assert env("GET", "/cases/LA-01/status", headers=OFFICER)[1]["status"] == "verified"


# --- queue extras and analytics (Days 6-8) ---------------------------------------------------

def test_queue_shows_flag_count_and_filters_by_scheme(env):
    env("POST", "/cases/LA-07/run", headers=CLERK)
    _, queue = env("GET", "/cases?scheme=land_acquisition", headers=OFFICER)
    by_id = {c["case_id"]: c for c in queue}
    assert len(queue) == 15 and by_id["LA-07"]["flags_count"] >= 1 and by_id["LA-03"]["flags_count"] == 0
    assert env("GET", "/cases?scheme=disaster_relief", headers=OFFICER)[1] == []


def test_analytics_counts_status_scheme_and_processing_time(env):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    env("POST", "/cases/LA-01/decision", {"decision": "approve"}, OFFICER)
    status, a = env("GET", "/analytics", headers=OFFICER)
    assert status == 200
    assert a["by_status"]["approved"] == 1 and a["by_status"]["received"] == 14
    assert a["per_scheme"] == {"land_acquisition": 15}
    assert a["decided_cases"] == 1 and a["average_processing_seconds"] >= 0
    assert a["average_processing_source"] == "case created_at to officer_decision audit entry"


def test_analytics_has_no_average_when_nothing_decided(env):
    a = env("GET", "/analytics", headers=OFFICER)[1]
    assert a["decided_cases"] == 0 and a["average_processing_seconds"] is None


def test_stuck_cases_use_last_audit_movement(env):
    env("POST", "/cases/LA-01/run", headers=CLERK)
    env("POST", "/cases/LA-01/decision", {"decision": "approve"}, OFFICER)
    stuck_now = env("GET", "/analytics?stuck_days=0", headers=OFFICER)[1]["stuck_cases"]
    assert "LA-01" not in {c["case_id"] for c in stuck_now}             # closed cases are never stuck
    assert len(stuck_now) == 14 and all("last_movement" in c and "status" in c for c in stuck_now)
    assert env("GET", "/analytics?stuck_days=30", headers=OFFICER)[1]["stuck_cases"] == []


def test_analytics_is_staff_only(env):
    assert env("GET", "/analytics", headers=CITIZEN)[0] == 403


def test_schemes_lists_every_rules_file_with_its_documents(env):
    status, schemes = env("GET", "/schemes", headers=CLERK)
    by_name = {s["scheme"]: s for s in schemes}
    assert status == 200 and by_name["land_acquisition"]["version"] == "0.1.0"
    assert "mutation_record" in by_name["land_acquisition"]["documents"]


def test_schemes_list_officer_inputs_from_the_yaml(env):
    (la,) = [s for s in env("GET", "/schemes", headers=CLERK)[1] if s["scheme"] == "land_acquisition"]
    assert la["officer_inputs"] == ["market_value_per_sqm", "assets_total", "multiplier",
                                    "sia_notification_date", "award_date", "possession_date"]


def test_admin_role_reaches_only_the_simulator(env):
    admin = {"X-Role": "admin", "X-User": "A-1"}
    assert env("GET", "/cases", headers=admin)[0] == 403
    assert env("GET", "/cases/LA-01", headers=admin)[0] == 403
    assert env("POST", "/cases/LA-01/decision", {"decision": "approve"}, admin)[0] == 403
