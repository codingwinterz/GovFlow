"""Print extraction accuracy and verification flag precision/recall on the messy synthetic set.

Usage: python -m scripts.eval_day2          (fake provider: replays recorded responses)
"""

from app.evaluation import run_messy_eval


def main() -> None:
    r = run_messy_eval()
    e, f = r.extraction, r.flags
    print(f"Provider(s): {', '.join(sorted(r.providers))}")
    print(f"\nExtraction over {e.total} key fields in {len({(x.case, x.doc_type) for x in e.rows})} messy documents")
    print(f"  accepted (>= threshold): {e.accepted}  correct: {e.accepted_correct}  WRONG: {e.accepted_wrong}")
    print(f"  routed to human review:  {e.routed_to_review}")
    for x in e.rows:
        if not x.accepted or not x.correct or x.method == "ocr_fallback":
            print(f"    {x.case}.{x.doc_type}.{x.field}: got {x.value!r} @ {x.confidence} via {x.method}; "
                  f"truth {x.truth!r} -> {'accepted' if x.accepted else 'REVIEW'}")
    print(f"\nVerification flags over {len(f.per_case)} messy cases: precision {f.precision}, recall {f.recall}")
    for case_id, s in f.per_case.items():
        print(f"  {case_id}: expected {s['expected']}  actual {s['actual']}")
    print(f"  FP: {f.false_positives}  FN: {f.false_negatives}")


if __name__ == "__main__":
    main()
