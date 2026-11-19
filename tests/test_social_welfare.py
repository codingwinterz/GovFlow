"""Tests for the pure-YAML 3rd scheme (rules/social_welfare.yaml): zero scheme-specific Python code."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import Base
from app.rules_loader import load_scheme_by_name, scheme_names
from app.self_check import self_check
from tests.asgi_client import call

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def test_zero_scheme_specific_python_code_in_app():
    assert "social_welfare" in scheme_names()
    offending = [
        p.name for p in sorted(APP_DIR.glob("*.py"))
        if "social_welfare" in p.read_text(encoding="utf-8")
    ]
    assert offending == [], f"social_welfare hardcoded in app/: {offending}"


def test_social_welfare_yaml_metadata_and_terms():
    scheme = load_scheme_by_name("social_welfare")
    assert scheme.sla_days == 30
    assert scheme.confidence_threshold == 0.85
    cat = next(d for d in scheme.required_documents if d.id == "category_proof")
    assert "remarks" in cat.may_be_blank
    for r in scheme.eligibility_rules:
        assert r.id in scheme.terms, f"missing term for rule {r.id}"
    for comp in scheme.compensation.components:
        assert comp.id in scheme.terms, f"missing term for component {comp.id}"


def test_social_welfare_self_check_dry_run():
    scheme = load_scheme_by_name("social_welfare")
    ok = self_check(scheme, {   # within the Rs 24,000 limit of the 2002 notification
        "residence_proof.born_in_goa": "no",
        "residence_proof.years_in_goa": "20",
        "income_certificate.annual_income": "20000",
        "category_proof.applicant_category": "senior_citizen",
    })
    assert ok.outcome == "likely_eligible"

    high_income = self_check(scheme, {
        "residence_proof.born_in_goa": "no",
        "residence_proof.years_in_goa": "20",
        "income_certificate.annual_income": "200000",
        "category_proof.applicant_category": "senior_citizen",
    })
    assert high_income.outcome == "likely_not_eligible"


def test_social_welfare_precheck_options_exclude_application(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app = create_app(engine=engine, upload_dir=tmp_path)
    status, body = call(app, "GET", "/public/precheck")
    assert status == 200
    sw = next(s for s in body["schemes"] if s["scheme"] == "social_welfare")
    doc_ids = [d["id"] for d in sw["documents"]]
    assert doc_ids == ["identity_proof", "residence_proof", "income_certificate", "category_proof"]
    assert "application" not in doc_ids
