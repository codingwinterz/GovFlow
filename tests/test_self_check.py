"""Self-check before applying: dry-run of YAML-listed rules on the applicant's answers. Nothing is stored."""

import pytest
import yaml
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import AuditLog, Base, Case, Document
from app.rules_loader import RULES_DIR, RulesError, load_scheme_by_name, parse_scheme
from app.self_check import GUIDE_LABEL, self_check
from tests.asgi_client import call

DR = load_scheme_by_name("disaster_relief")
DAMAGE, AREA = "damage_assessment.damage_percent", "damage_assessment.notified_area"


@pytest.mark.parametrize("answers, outcome", [
    ({DAMAGE: "80", AREA: "yes"}, "likely_eligible"),
    ({DAMAGE: "80%", AREA: "Yes"}, "likely_eligible"),
    ({DAMAGE: "10", AREA: "yes"}, "likely_not_eligible"),
    ({DAMAGE: "80", AREA: "no"}, "likely_not_eligible"),
    ({DAMAGE: "80"}, "need_more_information"),
    ({DAMAGE: "eighty", AREA: "yes"}, "need_more_information"),
    ({DAMAGE: "150", AREA: "yes"}, "need_more_information"),
    ({}, "need_more_information"),
])
def test_outcomes(answers, outcome):
    assert self_check(DR, answers).outcome == outcome


def test_result_carries_the_guide_label_and_documents_to_bring():
    result = self_check(DR, {DAMAGE: "80", AREA: "yes"})
    assert result.guide_label == GUIDE_LABEL == "This is a guide, not a decision. Only an officer decides."
    assert result.documents_to_bring == DR.document_ids
    assert result.checked_when_you_apply == ["name_match", "house_match", "duplicate_claim"]


def test_failed_rule_explains_itself_in_plain_words():
    result = self_check(DR, {DAMAGE: "10", AREA: "yes"})
    (failed,) = [r for r in result.rules if r.status == "fail"]
    assert failed.rule_id == "damage_category_eligible"
    assert failed.message == "Assessed damage is below the minimum for housing relief."   # fail_reason from the YAML


def test_invalid_answer_names_the_question():
    result = self_check(DR, {DAMAGE: "eighty", AREA: "yes"})
    (review,) = [r for r in result.rules if r.status == "needs_review"]
    assert DAMAGE in review.message and "not a percentage" in review.message


def test_unknown_answer_keys_are_rejected():
    with pytest.raises(ValueError, match="not a self-check question"):
        self_check(DR, {"identity_proof.id_number": "9999 0000 0001"})


def test_scheme_without_self_check_is_refused():
    with pytest.raises(ValueError, match="no self-check"):
        self_check(load_scheme_by_name("land_acquisition"), {})


# --- YAML validation -------------------------------------------------------------------------

def _yaml():
    return yaml.safe_load((RULES_DIR / "disaster_relief.yaml").read_text(encoding="utf-8"))


def test_question_must_be_a_declared_field():
    data = _yaml()
    data["self_check"]["questions"][0]["field"] = "damage_assessment.roof_type"
    with pytest.raises(RulesError, match="roof_type"):
        parse_scheme(data)


def test_listed_rule_must_exist():
    data = _yaml()
    data["self_check"]["rules"].append("has_bank_account")
    with pytest.raises(RulesError, match="has_bank_account"):
        parse_scheme(data)


def test_listed_rule_may_only_read_questions():
    data = _yaml()
    data["self_check"]["rules"].append("documents_not_expired")
    with pytest.raises(RulesError, match="documents_not_expired"):
        parse_scheme(data)


# --- API: public, rate-limited, stores nothing -----------------------------------------------------

@pytest.fixture
def app_engine(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return create_app(engine=engine, upload_dir=tmp_path, clock=lambda: 0.0), engine


def _counts(engine):
    with Session(engine) as s:
        return [s.scalar(select(func.count()).select_from(t)) for t in (Case, Document, AuditLog)]


def test_api_self_check_is_public_and_stores_nothing(app_engine):
    app, engine = app_engine
    before = _counts(engine)
    status, body = call(app, "POST", "/public/self-check",
                        {"scheme": "disaster_relief", "answers": {DAMAGE: "80", AREA: "yes"}})
    assert status == 200 and body["outcome"] == "likely_eligible" and body["guide_label"] == GUIDE_LABEL
    assert _counts(engine) == before == [0, 0, 0]


def test_api_lists_only_schemes_with_a_self_check(app_engine):
    app, _ = app_engine
    status, schemes = call(app, "GET", "/public/self-check")
    assert status == 200 and [s["scheme"] for s in schemes] == ["disaster_relief", "social_welfare"]
    q = {x["field"]: x for x in schemes[0]["questions"]}
    assert q[DAMAGE]["type"] == "percent" and q[AREA]["choices"] == ["yes", "no"]
    assert schemes[0]["labels"]["title"] and schemes[0]["guide_label"] == GUIDE_LABEL


@pytest.mark.parametrize("body, code", [({"scheme": "land_acquisition", "answers": {}}, 404),
                                        ({"scheme": "../etc", "answers": {}}, 404),
                                        ({"scheme": "disaster_relief", "answers": {"x.y": "1"}}, 400)])
def test_api_errors(app_engine, body, code):
    app, _ = app_engine
    assert call(app, "POST", "/public/self-check", body)[0] == code


def test_api_self_check_is_rate_limited(app_engine):
    app, _ = app_engine
    body = {"scheme": "disaster_relief", "answers": {DAMAGE: "80", AREA: "yes"}}
    for _ in range(10):
        assert call(app, "POST", "/public/self-check", body, client="4.4.4.4")[0] == 200
    assert call(app, "POST", "/public/self-check", body, client="4.4.4.4")[0] == 429
