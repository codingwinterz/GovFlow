"""scripts/benchmark_processing.py: the statistics, the one-call preflight and the report. No product code involved.
Expected values are worked out by hand (nearest-rank percentile: the ceil(0.9 * n)-th smallest value)."""
import pytest

from scripts import benchmark_processing as bp


def test_summary_of_one_to_ten():
    s = bp.summarize([float(x) for x in range(1, 11)])
    assert s == {"n": 10, "median": 5.5, "mean": 5.5, "p90": 9.0}


def test_summary_nearest_rank_p90_for_eleven_values():
    s = bp.summarize([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0])
    assert s["p90"] == 100.0           # ceil(0.9 * 11) = 10th value
    assert s["median"] == 60.0 and s["mean"] == 60.0


def test_summary_single_and_empty():
    assert bp.summarize([2.5]) == {"n": 1, "median": 2.5, "mean": 2.5, "p90": 2.5}
    assert bp.summarize([]) == {"n": 0, "median": None, "mean": None, "p90": None}


def test_preflight_makes_one_call_and_never_retries():
    calls = []

    def failing():
        calls.append(1)
        raise RuntimeError("503 unavailable")

    ok, reason = bp.preflight(failing)
    assert ok is False and calls == [1] and "503" in reason

    def working():
        calls.append(1)
        return {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}

    calls.clear()
    assert bp.preflight(working) == (True, "") and calls == [1]


def test_preflight_without_a_key_is_a_fallback_run():
    ok, reason = bp.preflight(None)
    assert ok is False and "not configured" in reason


META = {"date": "2026-11-20", "machine": "Windows 11, 16 logical CPUs", "python": "3.12.4",
        "provider": "fallback provider (Tesseract only; Gemini preflight failed: 503)", "cases": 42, "documents": 14}
STATS = {"land_acquisition": {"read": bp.summarize([100.0, 200.0]), "verify": bp.summarize([1.0, 2.0]),
                              "assess": bp.summarize([0.5]), "calculate": bp.summarize([0.25]),
                              "total": bp.summarize([3.0, 300.0])}}


def test_report_states_provider_counts_and_limits():
    md = bp.render(META, STATS)
    assert "fallback provider" in md and "42" in md and "Windows 11" in md
    assert "| land_acquisition | read | 2 | 150.0 | 150.0 | 200.0 |" in md
    assert "synthetic" in md.lower() and "one machine" in md.lower() and "human review" in md.lower()


@pytest.mark.parametrize("word", ["manual", "faster than", "speed-up", "speedup", "times quicker"])
def test_report_makes_no_comparison_with_manual_processing(word):
    assert word not in bp.render(META, STATS).lower()
