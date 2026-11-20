"""The deterministic (no-LLM) explanation must show ID numbers in the same masked form as the document view
(CLAUDE.md rule 7): "XXXX XXXX 1234", never the full number. Checked for every synthetic case of every scheme."""
import re
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.agent import run_agent
from app.case_model import CaseIn
from app.case_store import seed_case
from app.extraction import ProviderError
from app.models import make_engine

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
SCHEMES = sorted(p.name for p in DATA.iterdir() if p.is_dir() and any(p.glob("case_*/case.json")))
# Defined here, not imported from app.privacy, so the test still sees an ID if the masking pattern breaks.
UNMASKED_ID = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
MASKED_ID = re.compile(r"XXXX XXXX \d{4}(?!\d)")


class _NoLLM:
    name, model = "none", None

    def complete(self, system, messages, tools):
        raise ProviderError("no agent LLM in this test", kind="not_configured")


def _fallback_explanations(scheme: str) -> dict[str, str]:
    cases = [CaseIn.model_validate_json(p.read_text(encoding="utf-8"))
             for p in sorted((DATA / scheme).glob("case_*/case.json"))]
    engine = make_engine("sqlite://")
    out = {}
    with Session(engine) as session:
        for case in cases:
            seed_case(session, case)
        for case in cases:
            run = run_agent(session, case.case_id, _NoLLM(), actor="test")
            assert run.used_fallback
            out[case.case_id] = run.explanation
    engine.dispose()
    return out


@pytest.fixture(scope="module")
def explanations() -> dict[str, dict[str, str]]:
    return {scheme: _fallback_explanations(scheme) for scheme in SCHEMES}


def test_every_scheme_is_covered():
    assert {"land_acquisition", "disaster_relief", "social_welfare", "revenue_mutation"} <= set(SCHEMES)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_no_unmasked_id_in_the_fallback_explanation(explanations, scheme):
    leaked = [case_id for case_id, text in explanations[scheme].items() if UNMASKED_ID.search(text)]
    assert leaked == [], f"unmasked ID number in the fallback explanation of {leaked}"   # ids only, never the value


def test_the_check_is_not_vacuous(explanations):
    # At least one fallback explanation names an ID number, and it does so in the masked form.
    assert any(MASKED_ID.search(text) for per_scheme in explanations.values() for text in per_scheme.values())
