"""Cross-check comparison ignores punctuation at the start and end of a reading (Tesseract adds stray ":", ".",
"?", ";" and quotes around correct values). Punctuation inside a value still counts, a sign or decimal point
before a digit still counts, and the evaluation's scoring (canonical) is unchanged."""

import pytest

from app.cross_check import canonical, readers_disagree


@pytest.mark.parametrize("field_type, first, second", [
    ("text", "Suresh Gawas", "Suresh Gawas."),
    ("text", "Dinesh Naik", "Dinesh Naik..."),
    ("text", "Anita Sawant", "Anita Sawant: ;"),
    ("text", "H-9", ": H-9"),
    ("text", "Siolim", "Siolim ;"),
    ("text", "Aldona", "Aldona’"),          # right single quotation mark, as Tesseract read it
    ("one_of", "Hut", "? Hut"),
    ("text", "Corgao", "Corgao,"),
    ("number", "10000", "10000."),
])
def test_punctuation_only_at_the_edges_is_agreement(field_type, first, second):
    assert not readers_disagree(field_type, first, second)


@pytest.mark.parametrize("field_type, first, second", [
    ("text", "H-9", "H9"),                    # inside the value: still a difference
    ("text", "Jyoti Parab", "Jyoti Parab a"),  # a stray letter is not punctuation
    ("text", "Rohan Desai", "RGHAN DESAS"),
    ("number", "5", "-5"),                    # a sign before a digit is kept
    ("number", "5", ".5"),                    # so is a decimal point
    ("text", "Prakash", "?"),                 # nothing left after trimming is not agreement
])
def test_real_differences_still_disagree(field_type, first, second):
    assert readers_disagree(field_type, first, second)


def test_evaluation_scoring_is_not_loosened():
    # evaluation.py scores readings with canonical(); a reading with stray punctuation stays wrong there.
    assert canonical("text", "Suresh Gawas.") != canonical("text", "Suresh Gawas")
    assert canonical("text", ": H-9") != canonical("text", "H-9")
