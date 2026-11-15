"""Writes the fixed synthetic land-acquisition test set.

ALL DATA IS SYNTHETIC. Names are invented; ID numbers are pre-masked.
Expected outcomes below are hand-computed literals, never produced by app code.
Do not edit expected values to make a test pass (see CLAUDE.md).

Run: python data/synthetic/build_land_acquisition.py
"""

import copy
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "land_acquisition"
REFERENCE_DATE = "2026-11-15"
ALL_PASS_CHECKS = {"name_match": "pass", "survey_no_match": "pass", "duplicate_claim": "pass"}
ALL_PASS_RULES = {r: "pass" for r in
                  ["documents_complete", "valid_ownership", "land_identified", "documents_not_expired",
                   "no_competing_claim"]}


def f(value, confidence=0.95, page=1):
    return {"value": value, "confidence": confidence, "source_page": page}


def documents(name, survey, area, unit, total_area, total_unit, id_name=None, sheet_survey=None,
              id_expiry="2031-03-31", mutation_issue="2026-08-01", id_last4="0001"):
    return {
        "application": {"fields": {"name": f(name, 1.0, None)}},
        "ownership_record": {"fields": {
            "name": f(name), "survey_number": f(survey), "area": f(area), "area_unit": f(unit),
            "issue_date": f("2026-10-01"),
        }},
        "identity_proof": {"fields": {
            "name": f(id_name or name), "id_number": f(f"XXXX XXXX {id_last4}"), "expiry_date": f(id_expiry),
        }},
        "survey_sheet": {"fields": {
            "survey_number": f(sheet_survey or survey), "area": f(total_area), "area_unit": f(total_unit),
        }},
        "mutation_record": {"fields": {"name": f(name), "issue_date": f(mutation_issue)}},
    }


def inputs(mv, assets, start="2024-11-15", end="2026-11-15", **extra):
    out = {"market_value_per_sqm": mv, "assets_total": assets, **extra}
    if start:
        out["interest_start_date"] = start
    if end:
        out["interest_end_date"] = end
    return out


def comp(land, assets, solatium, interest, status="computed"):
    """Item amounts are hand-computed literals; the total is their sum (no app code involved)."""
    items = {k: v for k, v in
             {"land_value": land, "assets_value": assets, "solatium": solatium, "interest": interest}.items()
             if v is not None}
    total = round(sum(items.values()), 2) if status == "computed" else None
    return {"status": status, "items": items, "total": total}


def expected(desc, checks=None, rules=None, overall="eligible", compensation=None, review=False):
    return {
        "description": desc,
        "verification": {**ALL_PASS_CHECKS, **(checks or {})},
        "eligibility": {"overall": overall, "rules": {**ALL_PASS_RULES, **(rules or {})}},
        "compensation": compensation,
        "needs_human_review": review,
    }


CASES = []

# 01 happy path. 2500 sqm x 3000 x 1.0; interest 12% x 730/365 = 2.0 y
CASES.append((documents("Asha Naik", "123/4", 0.25, "hectare", 1.0, "hectare"), inputs(3000, 200_000),
              expected("Clean case, all documents consistent",
                       compensation=comp(7_500_000, 200_000, 7_700_000, 1_800_000))))

# 02 name spelled differently but above fuzzy threshold (0.963). 1 year interest
CASES.append((documents("Prakash Kamat", "56/1", 1200, "sqm", 3000, "sqm", id_name="Prakash Kamath"),
              inputs(2500, 50_000, start="2025-11-15"),
              expected("Name spelled differently (Kamat/Kamath), within fuzzy tolerance",
                       compensation=comp(3_000_000, 50_000, 3_050_000, 360_000))))

# 03 name similarity 0.889: between confidence threshold 0.85 and fuzzy 0.9
CASES.append((documents("Santosh Parab", "88/2", 800, "sqm", 2000, "sqm", id_name="Santosh Prabhu"),
              inputs(4000, 100_000),
              expected("Similar but different surname on identity proof: review band",
                       checks={"name_match": "needs_review"}, rules={"valid_ownership": "needs_review"},
                       overall="needs_review", review=True,
                       compensation=comp(3_200_000, 100_000, 3_300_000, 768_000))))

# 04 identity proof belongs to a different person
CASES.append((documents("Maria Fernandes", "12/3", 1000, "sqm", 2500, "sqm", id_name="Vinod Shetty"),
              inputs(3500, 0, start="2025-11-15"),
              expected("Identity proof name does not match applicant",
                       checks={"name_match": "fail"}, rules={"valid_ownership": "fail"},
                       overall="not_eligible", review=True,
                       compensation=comp(3_500_000, 0, 3_500_000, 420_000))))

# 05 identity proof expired before reference date
CASES.append((documents("Rohan Desai", "210/1", 1500, "sqm", 4000, "sqm", id_expiry="2026-09-30"),
              inputs(2000, 75_000),
              expected("Expired identity proof",
                       rules={"documents_not_expired": "fail"}, overall="not_eligible", review=True,
                       compensation=comp(3_000_000, 75_000, 3_075_000, 720_000))))

# 06 mutation record issued 440 days before reference date (max age 365)
CASES.append((documents("Joao Pereira", "34/5", 600, "sqm", 1500, "sqm", mutation_issue="2025-09-01"),
              inputs(5000, 25_000, start="2025-11-15"),
              expected("Mutation record too old",
                       rules={"documents_not_expired": "fail"}, overall="not_eligible", review=True,
                       compensation=comp(3_000_000, 25_000, 3_025_000, 360_000))))

# 07 missing attachment: no mutation record
docs07 = documents("Shanti Gaonkar", "99/9", 2000, "sqm", 5000, "sqm")
del docs07["mutation_record"]
CASES.append((docs07, inputs(1500, 0),
              expected("Mutation record not submitted",
                       rules={"documents_complete": "fail"}, overall="not_eligible", review=True,
                       compensation=comp(3_000_000, 0, 3_000_000, 720_000))))

# 08 survey number transposed on survey sheet
CASES.append((documents("Francis Rodrigues", "145/2", 1000, "sqm", 3000, "sqm", sheet_survey="154/2"),
              inputs(3000, 100_000, start="2025-11-15"),
              expected("Survey number mismatch between ownership record and survey sheet",
                       checks={"survey_no_match": "fail"}, rules={"land_identified": "fail"},
                       overall="not_eligible", review=True,
                       compensation=comp(3_000_000, 100_000, 3_100_000, 360_000))))

# 09 area in square feet: 10000 sq ft = 929.0304 sqm x 2500 = 2,322,576
CASES.append((documents("Anita Sawant", "301/7", 10_000, "sq ft", 2000, "sqm"),
              inputs(2500, 30_000, start="2025-11-15"),
              expected("Area given in square feet",
                       compensation=comp(2_322_576, 30_000, 2_352_576, 278_709.12))))

# 10 area in acres (1 acre = 4046.8564224 sqm x 1000) and SIA notification date not supplied
CASES.append((documents("Vasant Kerkar", "18/1", 1, "acre", 2, "acres"), inputs(1000, 0, start=None),
              expected("Area in acres; interest start date missing so interest is not guessed",
                       review=True,
                       compensation=comp(4_046_856.42, 0, 4_046_856.42, None, status="needs_review"))))

# 11 low-quality scan: owner name and area unreadable on ownership record
docs11 = documents("Lata Shirodkar", "61/1", 900, "sqm", 2000, "sqm")
docs11["ownership_record"]["fields"]["name"] = f("L?ta Sh1rodkar", 0.62)
docs11["ownership_record"]["fields"]["area"] = f(900, 0.70)
CASES.append((docs11, inputs(3000, 40_000),
              expected("Low-quality scan of ownership record",
                       checks={"name_match": "needs_review"}, rules={"valid_ownership": "needs_review"},
                       overall="needs_review", review=True,
                       compensation=comp(None, 40_000, None, None, status="needs_review"))))

# 12 + 13 duplicate claim: survey 45/2 is 0.5 ha; claims 0.4 + 0.3 = 0.7 ha overlap
CASES.append((documents("Dinesh Naik", "45/2", 0.4, "ha", 0.5, "ha"), inputs(2000, 0, start="2025-11-15"),
              expected("Overlapping claim on survey 45/2 (with case 13)",
                       checks={"duplicate_claim": "needs_review"}, rules={"no_competing_claim": "needs_review"},
                       overall="needs_review", review=True,
                       compensation=comp(8_000_000, 0, 8_000_000, 960_000))))
CASES.append((documents("Suresh Gawas", "45/2", 0.3, "ha", 0.5, "ha", id_last4="0013"),
              inputs(2000, 10_000, start="2025-11-15"),
              expected("Overlapping claim on survey 45/2 (with case 12)",
                       checks={"duplicate_claim": "needs_review"}, rules={"no_competing_claim": "needs_review"},
                       overall="needs_review", review=True,
                       compensation=comp(6_000_000, 10_000, 6_010_000, 720_000))))

# 14 + 15 co-owners of survey 77/1 (1 ha): 0.4 + 0.5 ha fits, so not a duplicate
CASES.append((documents("Meena Kamat", "77/1", 0.4, "ha", 1, "ha"), inputs(1500, 0, start="2025-11-15"),
              expected("Co-owner claim, zero assets",
                       compensation=comp(6_000_000, 0, 6_000_000, 720_000))))
# 15: multiplier 2.0 from case; interest 2023-11-15 -> 2026-11-15 = 1096 days (leap year)
# interest = 15,000,000 x 0.12 x 1096/365 = 5,404,931.506.. -> 5,404,931.51
CASES.append((documents("Ravi Kamat", "77/1", 0.5, "ha", 1, "ha", id_last4="0015"),
              inputs(1500, 150_000, start="2023-11-15", multiplier=2.0),
              expected("Co-owner claim, multiplier 2.0, interest over three years incl. leap day",
                       compensation=comp(15_000_000, 150_000, 15_150_000, 5_404_931.51))))


def main() -> None:
    for i, (docs, case_inputs, exp) in enumerate(CASES, start=1):
        case_id = f"LA-{i:02d}"
        folder = OUT / f"case_{i:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        case = {"case_id": case_id, "scheme": "land_acquisition", "status": "received",
                "reference_date": REFERENCE_DATE, "documents": copy.deepcopy(docs), "inputs": case_inputs}
        (folder / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        (folder / "expected.json").write_text(json.dumps({"case_id": case_id, **exp}, indent=2) + "\n",
                                              encoding="utf-8")
    print(f"Wrote {len(CASES)} cases to {OUT}")


if __name__ == "__main__":
    main()
