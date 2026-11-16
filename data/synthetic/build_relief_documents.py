"""Writes the synthetic disaster-relief document set for image evaluation: scan text and truth labels.

ALL DATA IS SYNTHETIC. Names, houses and villages are invented for the test cases; 12-digit ID numbers are fake
(9999 2000 ....). Every document says SYNTHETIC on its face. Printed values come from the case's own case.json,
so the document, the truth label and the hand-derived expected outcome of the case all agree.

For each document:
  disaster_relief/case_XX/documents/<doc_type>.txt   the text printed on the paper (dates day-first, as printed)
  disaster_relief/messy_labels.json                  truth values and the expected flag kinds per case
Images are rendered from the .txt by scripts/render_images.py.

Run: python data/synthetic/build_relief_documents.py
"""

import json
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent / "disaster_relief"

# (case folder, document type, why it is in the set)
DOCS = [
    ("case_01", "damage_assessment", "fully damaged pucca house, 80%"),
    ("case_03", "damage_assessment", "exactly at the 75% full-damage threshold, kutcha, hilly"),
    ("case_06", "damage_assessment", "14.9%: a decimal just under the minimum, easy to misread"),
    ("case_07", "residence_proof", "name differs from the applicant (expected name_match)"),
    ("case_13", "residence_proof", "house number differs from the assessment (expected house_match)"),
    ("case_05", "identity_proof", "apostrophe in the name"),
    ("case_08", "identity_proof", "expired identity proof (expected document_expired)"),
]

# Expected verification flag kinds per case, derived by hand from each case's expected.json.
EXPECTED_FLAGS = {
    "DR-01": [],
    "DR-03": [],
    "DR-06": [],
    "DR-07": ["name_match"],
    "DR-13": ["house_match"],
    "DR-05": [],
    "DR-08": ["document_expired"],
}


def _day_first(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _percent(value) -> str:
    return f"{value:g}%"


def render_text(doc_type: str, f: dict) -> str:
    if doc_type == "damage_assessment":
        return ("DAMAGE ASSESSMENT REPORT (SYNTHETIC)\n"
                f"House No.: {f['house_number']}\nVillage: {f['village']}\nDamage: {_percent(f['damage_percent'])}\n"
                f"House type: {f['house_type'].capitalize()}\nArea type: {f['area_type'].capitalize()}\n"
                f"Notified area: {f['notified_area'].capitalize()}\nAssessed: {_day_first(f['assessment_date'])}\n")
    if doc_type == "residence_proof":
        return ("HOUSE TAX RECEIPT (SYNTHETIC)\n"
                f"Name: {f['name']}\nHouse No.: {f['house_number']}\nVillage: {f['village']}\n"
                f"Issued: {_day_first(f['issue_date'])}\n")
    if doc_type == "identity_proof":
        return ("GOVERNMENT IDENTITY CARD (SYNTHETIC)\n"
                f"Name : {f['name']}\nID No: {f['id_number']}\nValid upto: {_day_first(f['expiry_date'])}\n")
    raise ValueError(f"No layout for {doc_type}")


def main() -> None:
    labels = {"documents": [], "expected_flags": EXPECTED_FLAGS}
    for folder_name, doc_type, why in DOCS:
        folder = OUT / folder_name
        case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        fields = {name: fv["value"] for name, fv in case["documents"][doc_type]["fields"].items()}
        (folder / "documents").mkdir(exist_ok=True)
        (folder / "documents" / f"{doc_type}.txt").write_text(render_text(doc_type, fields), encoding="utf-8")
        labels["documents"].append({"case": folder_name, "doc_type": doc_type, "why": why, "truth": fields})
    (OUT / "messy_labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(DOCS)} relief documents and labels for {len(EXPECTED_FLAGS)} cases")


if __name__ == "__main__":
    main()
