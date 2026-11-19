"""Social welfare: the source-conflict note (2026-11-19). Documentation only: every value stays the same placeholder.

Expected values are read by hand from rules/social_welfare.yaml before the note was added.
"""
from pathlib import Path

from app.rules_loader import load_scheme_by_name

ROOT = Path(__file__).resolve().parent.parent
YAML_TEXT = (ROOT / "rules" / "social_welfare.yaml").read_text(encoding="utf-8")
LIMITS = (ROOT / "docs" / "KNOWN_LIMITATIONS.md").read_text(encoding="utf-8")
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

# The facts the note must carry, wherever it appears.
FACTS = ["SOURCE CONFLICT", "Social Welfare Department", "15-year residence", "Rs 24,000 per annum income limit",
         "2002 notification", "Rs 1.5 lakh", "Rs 3 lakh", "Rs 2,000", "Rs 2,500", "Directorate"]


def _flat(text: str) -> str:
    """Joins wrapped lines (Markdown continuation and YAML '#' comment lines) so a phrase may span a line break."""
    lines = [line.strip().lstrip("#").lstrip("-").strip() for line in text.splitlines()]
    return " ".join(lines)


def test_yaml_carries_the_source_conflict_note():
    flat = _flat(YAML_TEXT)
    for fact in FACTS:
        assert fact in flat, fact


def test_known_limitations_and_verify_list_carry_the_note():
    for name, text in (("KNOWN_LIMITATIONS.md", LIMITS), ("CLAUDE.md", CLAUDE)):
        flat = _flat(text)
        for fact in FACTS:
            assert fact in flat, f"{name}: {fact}"


def test_no_value_changed():
    scheme = load_scheme_by_name("social_welfare")
    params = scheme.compensation.parameters
    assert params["min_residency_years"] == 15
    assert params["max_annual_income"] == 150000
    assert params["senior_base_annual"] == 24000
    assert params["widow_base_annual"] == 24000
    assert params["disability_base_annual"] == 24000
    assert params["single_woman_base_annual"] == 24000
    assert params["high_age_bonus_annual"] == 6000
    assert params["minor_child_supplement_annual"] == 6000
    assert scheme.version == "2026.1-draft"
