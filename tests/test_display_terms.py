"""Human labels for every scheme identifier a user can see (rules YAML `terms:`), never snake_case on screen."""

import pytest
import yaml

from app.rules_loader import RULES_DIR, RulesError, known_terms, load_scheme_by_name, parse_scheme, term_label
from tests.asgi_client import call
from tests.auth_headers import staff

SCHEMES = sorted(p.stem for p in RULES_DIR.glob("*.yaml"))


@pytest.mark.parametrize("name", SCHEMES)
def test_every_identifier_in_the_scheme_has_an_explicit_label(name):
    scheme = load_scheme_by_name(name)
    unlabelled = [t for t in sorted(known_terms(scheme)) if term_label(scheme, t) is None]
    assert unlabelled == []


@pytest.mark.parametrize("name", SCHEMES)
def test_labels_are_words_not_identifiers(name):
    for term, label in load_scheme_by_name(name).terms.items():
        assert label.strip() and "_" not in label, term


def test_known_terms_cover_each_kind_of_identifier():
    terms = known_terms(load_scheme_by_name("land_acquisition"))
    for t in ["ownership_record", "ownership_record.survey_number", "name_match", "valid_ownership", "solatium",
              "years_since_notification", "market_value_per_sqm", "interest_rate", "ownership_record.area_sqm"]:
        assert t in terms, t


def test_a_field_falls_back_to_its_plain_field_label():
    scheme = load_scheme_by_name("disaster_relief")
    assert term_label(scheme, "damage_assessment.damage_percent") == scheme.terms["damage_percent"]


def _raw(name="disaster_relief"):
    return yaml.safe_load((RULES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def test_a_label_for_an_unknown_identifier_is_rejected():
    data = _raw()
    data["terms"]["no_such_thing"] = "Something"
    with pytest.raises(RulesError, match="no_such_thing"):
        parse_scheme(data)


def test_a_label_that_is_itself_snake_case_is_rejected():
    data = _raw()
    data["terms"]["hut"] = "hut_amount"
    with pytest.raises(RulesError, match="hut"):
        parse_scheme(data)


def test_terms_are_optional_for_a_new_scheme():
    data = _raw()
    del data["terms"]
    assert parse_scheme(data).terms == {}


def test_schemes_and_case_detail_return_the_terms(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.case_store import seed_case
    from app.main import create_app
    from app.models import Base
    from tests.test_all_schemes import _cases
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_case(s, _cases("land_acquisition")[0][0])
    app = create_app(engine=engine, upload_dir=tmp_path)
    officer = staff("officer", "O-1")
    (la,) = [s for s in call(app, "GET", "/schemes", None, officer)[1] if s["scheme"] == "land_acquisition"]
    assert la["terms"] == load_scheme_by_name("land_acquisition").terms
    assert call(app, "GET", "/cases/LA-01", None, officer)[1]["terms"]["solatium"] == la["terms"]["solatium"]


def test_citizen_amounts_carry_the_terms_so_the_basis_reads_as_words():
    from app.case_store import seed_case
    from app.citizen import _amounts
    from app.models import Case, make_engine, make_session
    from app.tools import compute_compensation
    from tests.test_all_schemes import _cases
    with make_session(make_engine("sqlite://")) as s:
        seed_case(s, _cases("land_acquisition")[0][0])
        compute_compensation(s, "LA-01")
        case = s.get(Case, "LA-01")
        case.status = "approved"          # amounts are public only after approval
        amounts = _amounts(s, case, "0.1.0")
    assert amounts["terms"] == load_scheme_by_name("land_acquisition").terms


def test_public_self_check_questions_carry_the_terms():
    from app.self_check import public_questions
    scheme = load_scheme_by_name("disaster_relief")
    assert public_questions(scheme)["terms"] == scheme.terms
