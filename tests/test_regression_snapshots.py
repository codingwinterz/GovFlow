"""LA-01, DR-01 and SW-01 must keep exactly the output captured on main before the mutation engine changes
(explanation text, tool steps, rule results, compensation values, citizen page). See tests/regression_snapshot.py."""

import json

import pytest

from tests.regression_snapshot import CASES, capture, snapshot_path


@pytest.mark.parametrize("case_id", CASES)
def test_case_output_matches_the_snapshot_taken_on_main(case_id):
    expected = json.loads(snapshot_path(case_id).read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(capture(case_id), ensure_ascii=False))
    for part in ("steps", "explanation", "explanation_warnings", "used_fallback", "final_status",
                 "status_before_decision", "rules", "compensation", "citizen_view"):
        assert actual[part] == expected[part], f"{case_id}: {part} changed"


def test_snapshots_are_not_empty():
    """A snapshot with no steps, no explanation or no amounts would compare equal to a broken run."""
    for case_id in CASES:
        snap = json.loads(snapshot_path(case_id).read_text(encoding="utf-8"))
        assert [s["tool"] for s in snap["steps"]] == ["verify_documents", "check_eligibility",
                                                      "compute_compensation", "submit_to_officer"]
        assert all(s["ok"] for s in snap["steps"])
        assert snap["explanation"].startswith("Summary generated without the LLM")
        assert snap["compensation"] and snap["citizen_view"]["amounts"]["total"] > 0
        assert snap["citizen_view"]["status"] == "approved"
