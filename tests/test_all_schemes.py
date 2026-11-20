"""Every scheme with a synthetic set: hand-derived outcomes reproduced (pure and through the DB),
and the API screens work for it. Adding a scheme = a rules YAML + data/synthetic/<scheme>/; no new tests."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.assessment import assess_case
from app.case_model import CaseIn
from app.case_store import seed_case
from app.main import create_app
from app.models import Base, make_engine, make_session
from app.rules_loader import RULES_DIR, load_scheme_by_name
from app.tools import check_eligibility, compute_compensation, verify_documents
from tests.asgi_client import call
from tests.auth_headers import staff

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
SCHEMES = sorted(p.name for p in DATA.iterdir() if p.is_dir() and list(p.glob("case_*"))
                 and (RULES_DIR / f"{p.name}.yaml").is_file())
OFFICER = staff("officer", "O-1")
CLERK = staff("clerk", "C-1")


def _cases(scheme):
    out = []
    for folder in sorted((DATA / scheme).glob("case_*")):
        case = CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8"))
        out.append((case, json.loads((folder / "expected.json").read_text(encoding="utf-8"))))
    return out


PAIRS = [(s, c, e) for s in SCHEMES for c, e in _cases(s)]
IDS = [c.case_id for _, c, _ in PAIRS]


def test_both_schemes_have_synthetic_sets():
    assert {"land_acquisition", "disaster_relief"} <= set(SCHEMES)
    assert len(_cases("disaster_relief")) >= 10


def _check(expected, checks, eligibility, compensation):
    assert {c.check_id: c.status for c in checks} == expected["verification"]
    assert {r.rule_id: r.status for r in eligibility.results} == expected["eligibility"]["rules"]
    assert eligibility.overall == expected["eligibility"]["overall"]
    exp = expected["compensation"]
    if exp is None:                      # a scheme with no compensation section calculates no amount
        assert compensation is None
        return
    assert compensation.status == exp["status"]
    assert {i.component: i.amount for i in compensation.items} == pytest.approx(exp["items"], abs=0.005)
    if exp["total"] is None:
        assert compensation.total is None
    else:
        assert compensation.total == pytest.approx(exp["total"], abs=0.005)


@pytest.mark.parametrize("scheme, case, expected", PAIRS, ids=IDS)
def test_pure_tools_reproduce_expected(scheme, case, expected):
    result = assess_case(load_scheme_by_name(scheme), case, [c for c, _ in _cases(scheme)])
    _check(expected, result.verification.checks, result.eligibility, result.compensation)
    assert result.needs_human_review == expected["needs_human_review"]


@pytest.mark.parametrize("scheme, case, expected", PAIRS, ids=IDS)
def test_db_tools_reproduce_expected(scheme, case, expected):
    with make_session(make_engine("sqlite://")) as s:
        for c, _ in _cases(scheme):
            seed_case(s, c)
        verification = verify_documents(s, case.case_id)
        eligibility = check_eligibility(s, case.case_id)
        has_amount = load_scheme_by_name(scheme).compensation is not None
        compensation = compute_compensation(s, case.case_id) if has_amount else None
        _check(expected, verification.checks, eligibility, compensation)
        assert all(r.clause and r.rules_version for r in eligibility.results)


# --- the API screens work for every scheme, with no scheme-specific code ---------------------

@pytest.fixture(params=SCHEMES)
def env(request, tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for scheme in SCHEMES:
            for c, _ in _cases(scheme):
                seed_case(s, c)
    app = create_app(engine=engine, upload_dir=tmp_path / "uploads")
    return request.param, lambda method, path, body=None, headers=OFFICER: call(app, method, path, body, headers)


def test_scheme_is_listed_with_its_documents(env):
    scheme, api = env
    (listed,) = [s for s in api("GET", "/schemes")[1] if s["scheme"] == scheme]
    assert listed["documents"] == load_scheme_by_name(scheme).document_ids


def test_intake_queue_case_page_analytics_and_audit(env):
    scheme, api = env
    first = _cases(scheme)[0][0].case_id
    status, created = api("POST", "/cases", {"case_id": f"{scheme[:2].upper()}-90", "scheme": scheme,
                                             "reference_date": "2026-11-15"}, CLERK)
    assert status == 201 and created["scheme"] == scheme
    assert api("POST", f"/cases/{first}/run", headers=CLERK)[1]["final_status"] == "in_officer_review"
    queue = api("GET", f"/cases?scheme={scheme}")[1]
    assert len(queue) == len(_cases(scheme)) + 1 and {c["scheme"] for c in queue} == {scheme}
    detail = api("GET", f"/cases/{first}")[1]
    has_amount = load_scheme_by_name(scheme).compensation is not None
    assert detail["rule_results"] and all(r["clause"] for r in detail["rule_results"])
    assert bool(detail["compensation"]["items"]) == has_amount and detail["explanation"]["text"]
    assert all(str(f["value"]).startswith("XXXX XXXX ") for d in detail["documents"] for f in d["fields"]
               if f["field"] == "id_number")
    analytics = api("GET", "/analytics")[1]
    assert analytics["per_scheme"][scheme] == len(_cases(scheme)) + 1
    actions = {a["action"] for a in api("GET", f"/cases/{first}/audit")[1]}
    assert {"check_eligibility", "submit_to_officer"} <= actions
    assert ("compute_compensation" in actions) == has_amount
    confirmed = {f["ref"]: f["value"] for f in detail["confirm_fields"]}
    assert bool(confirmed) == has_amount                     # no amount: nothing drives one, nothing to confirm
    if has_amount:
        assert api("POST", f"/cases/{first}/decision", {"decision": "approve"})[0] == 409   # must confirm
    approved = api("POST", f"/cases/{first}/decision", {"decision": "approve", "confirmed_fields": confirmed,
                                                        "confirmed_case": first})
    assert approved[1]["status"] == "approved"


@pytest.mark.parametrize("scheme", SCHEMES)
def test_extracted_raw_identifier_is_masked_in_the_audit_log(scheme, tmp_path):
    from app.extraction import ProviderField
    from app.models import AuditLog
    from app.providers.fake import FakeProvider
    from app.tools import add_document, extract_document
    case = next(c for c, _ in _cases(scheme) if "identity_proof" in c.documents)
    raw = case.documents["identity_proof"].fields["id_number"].value
    assert raw[:4].isdigit(), "the synthetic set must hold a raw id for this test to mean anything"
    with make_session(make_engine("sqlite://")) as s:
        seed_case(s, case)
        path = tmp_path / "id.txt"
        path.write_text("scan", encoding="utf-8")
        doc = add_document(s, case.case_id, "identity_proof", str(path))
        fields = [ProviderField(name=k, value=v.value, confidence=0.97, page=1)
                  for k, v in case.documents["identity_proof"].fields.items()]
        extract_document(s, doc.id, FakeProvider({(str(doc.id), "document"): fields}))
        rows = [r.payload_json for r in s.query(AuditLog).filter_by(case_id=case.case_id)]
    assert any(f"XXXX XXXX {raw[-4:]}" in r for r in rows) and not any(raw in r for r in rows)
