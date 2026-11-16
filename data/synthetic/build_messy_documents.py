"""Writes messy synthetic documents, recorded fake-provider responses and truth labels.

ALL DATA IS SYNTHETIC. Names are invented; 12-digit ID numbers are fake (9999 0000 ....)
and exist to prove masking in the audit log.

For each document:
  case_XX/documents/<doc_type>.txt   simulated scan text (what the provider would see)
  case_XX/fake/<doc_type>.json       RECORDED fake responses: primary pass, OCR text + confidence,
                                     and the text-only pass over the OCR. Hand-written, not from a model.
messy_labels.json                    hand-written truth values and expected flag kinds per case.

Run: python data/synthetic/build_messy_documents.py
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "land_acquisition"


def pf(name, value, confidence, page=1):
    return {"name": name, "value": value, "confidence": confidence, "page": page}


DOCS = [
    {   # name spelled differently on identity proof (within fuzzy tolerance)
        "case": "case_02", "doc_type": "identity_proof",
        "text": "GOVERNMENT IDENTITY CARD (SYNTHETIC)\nName : PRAKASH KAMATH\nID No: 9999 0000 0002\n"
                "Valid upto: 31/03/2031\n",
        "document": [pf("name", "Prakash Kamath", 0.96), pf("id_number", "9999 0000 0002", 0.95),
                     pf("expiry_date", "2031-03-31", 0.94)],
        "truth": {"name": "Prakash Kamath", "expiry_date": "2031-03-31"},
    },
    {   # expired identity proof
        "case": "case_05", "doc_type": "identity_proof",
        "text": "GOVERNMENT IDENTITY CARD (SYNTHETIC)\nName : ROHAN DESAI\nID No: 9999 0000 0005\n"
                "Valid upto: 30/09/2026\n",
        "document": [pf("name", "Rohan Desai", 0.97), pf("id_number", "9999 0000 0005", 0.95),
                     pf("expiry_date", "2026-09-30", 0.95)],
        "truth": {"name": "Rohan Desai", "expiry_date": "2026-09-30"},
    },
    {   # survey number transposed on the survey sheet
        "case": "case_08", "doc_type": "survey_sheet",
        "text": "SURVEY PLAN (SYNTHETIC)\nVillage: Example\nSurvey No.: 154/2\nTotal area: 3000 sq. m.\n",
        "document": [pf("survey_number", "154/2", 0.95), pf("area", 3000, 0.95), pf("area_unit", "sqm", 0.93)],
        "truth": {"survey_number": "154/2", "area": 3000, "area_unit": "sqm"},
    },
    {   # area in square feet; unit is faint, so the OCR fallback confirms it
        "case": "case_09", "doc_type": "ownership_record",
        "text": "FORM I & XIV (SYNTHETIC)\nOccupant: Anita Sawant\nSurvey No.: 301/7\n"
                "Area: 10000 sq ft\nIssued: 01/10/2026\n",
        "document": [pf("name", "Anita Sawant", 0.96), pf("survey_number", "301/7", 0.95),
                     pf("area", 10000, 0.94), pf("area_unit", "sq ft", 0.78), pf("issue_date", "2026-10-01", 0.95)],
        "ocr": {"text": "FORM I & XIV\nOccupant: Anita Sawant\nSurvey No.: 301/7\nArea: 10000 sq ft", "confidence": 0.94},
        "ocr_text": [pf("area_unit", "sq ft", 0.93)],
        "truth": {"name": "Anita Sawant", "survey_number": "301/7", "area": 10000, "area_unit": "sq ft",
                  "issue_date": "2026-10-01"},
    },
    {   # low-quality scan: the paper copy itself is damaged, so letters are lost ("L?ta Sh1rodkar", "9?0").
        # The image is rendered from this damaged text (no separate print text), so the expected flags
        # (low confidence, name mismatch) are what a careful reader of the image should produce. The truth
        # stays the intact record: the paper is damaged, the person is not.
        "case": "case_11", "doc_type": "ownership_record",
        "text": "F0RM I & X1V (SYNTHETIC)\nOccup?nt: L?ta Sh1rodkar\nSurvey No.: 61/1\n"
                "Ar?a: 9?0 sq. m.\nIssued: 01/10/2026\n",
        "document": [pf("name", "L?ta Sh1rodkar", 0.62), pf("survey_number", "61/1", 0.90),
                     pf("area", 900, 0.70), pf("area_unit", "sqm", 0.90), pf("issue_date", "2026-10-01", 0.90)],
        "ocr": {"text": "F0RM I & X1V\nOccup nt: Lata Shirodkar\nAr a: 900 sq m", "confidence": 0.58},
        "ocr_text": [pf("name", "Lata Shirodkar", 0.90), pf("area", 900, 0.90)],
        "truth": {"name": "Lata Shirodkar", "survey_number": "61/1", "area": 900, "area_unit": "sqm",
                  "issue_date": "2026-10-01"},
    },
    {   # duplicate claim, first claimant
        "case": "case_12", "doc_type": "ownership_record",
        "text": "FORM I & XIV (SYNTHETIC)\nOccupant: Dinesh Naik\nSurvey No.: 45/2\nArea: 0.40 Ha\n"
                "Issued: 01/10/2026\n",
        "document": [pf("name", "Dinesh Naik", 0.97), pf("survey_number", "45/2", 0.96), pf("area", 0.4, 0.95),
                     pf("area_unit", "ha", 0.95), pf("issue_date", "2026-10-01", 0.95)],
        "truth": {"name": "Dinesh Naik", "survey_number": "45/2", "area": 0.4, "area_unit": "ha",
                  "issue_date": "2026-10-01"},
    },
    {   # duplicate claim, second claimant
        "case": "case_13", "doc_type": "ownership_record",
        "text": "FORM I & XIV (SYNTHETIC)\nOccupant: Suresh Gawas\nSurvey No.: 45/2\nArea: 0.30 Ha\n"
                "Issued: 01/10/2026\n",
        "document": [pf("name", "Suresh Gawas", 0.96), pf("survey_number", "45/2", 0.96), pf("area", 0.3, 0.95),
                     pf("area_unit", "ha", 0.95), pf("issue_date", "2026-10-01", 0.95)],
        "truth": {"name": "Suresh Gawas", "survey_number": "45/2", "area": 0.3, "area_unit": "ha",
                  "issue_date": "2026-10-01"},
    },
]

# Hand-labelled: which flag kinds a correct pipeline must raise for each messy case.
EXPECTED_FLAGS = {
    "LA-02": [],                                   # spelling variant is within tolerance
    "LA-05": ["document_expired"],
    "LA-07": ["missing_document"],                 # missing attachment: no mutation record uploaded
    "LA-08": ["survey_no_match"],
    "LA-09": [],                                   # sq ft converts cleanly; OCR confirms the faint unit
    "LA-11": ["low_confidence", "name_match"],
    "LA-12": ["duplicate_claim"],
    "LA-13": ["duplicate_claim"],
}


def main() -> None:
    labels = {"documents": [], "expected_flags": EXPECTED_FLAGS}
    for d in DOCS:
        folder = OUT / d["case"]
        (folder / "documents").mkdir(parents=True, exist_ok=True)
        (folder / "fake").mkdir(parents=True, exist_ok=True)
        (folder / "documents" / f"{d['doc_type']}.txt").write_text(d["text"], encoding="utf-8")
        printed = folder / "documents" / f"{d['doc_type']}.print.txt"
        if "print_text" in d:
            printed.write_text(d["print_text"], encoding="utf-8")
        elif printed.exists():
            printed.unlink()                     # the image is rendered from the scan text itself
        fake = {"document": d["document"], "ocr": d.get("ocr"), "ocr_text": d.get("ocr_text", [])}
        (folder / "fake" / f"{d['doc_type']}.json").write_text(json.dumps(fake, indent=2) + "\n", encoding="utf-8")
        labels["documents"].append({"case": d["case"], "doc_type": d["doc_type"], "truth": d["truth"]})
    (OUT / "messy_labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(DOCS)} messy documents and labels for {len(EXPECTED_FLAGS)} cases")


if __name__ == "__main__":
    main()
