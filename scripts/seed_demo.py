"""Build a demo database from the synthetic land-acquisition set (no network, no LLM).

- all 15 synthetic cases are seeded from data/synthetic (fields from case.json);
- the messy documents are re-read with their recorded fake responses, so low-confidence
  fields and the OCR fallback appear on the case page;
- one document is "uploaded" and fails with a simulated rate limit, to demo the retry banner;
- LA-01..LA-12 go through the agent's deterministic fallback (no LLM), so each has an
  assessment and a plain summary clearly labelled "generated without the LLM";
- two officer decisions are recorded as actor officer:seed-demo with a "synthetic" comment,
  so analytics has data (skip with --no-decisions).

Usage: python -m scripts.seed_demo [--db govflow.db] [--reset] [--no-decisions]
"""

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agent import run_agent
from app.citizen import citizen_code, citizen_secret
from app.case_model import CaseIn
from app.case_store import seed_case
from app.evaluation import SET_DIR, _fake_for
from app.extraction import ProviderError
from app.models import Case, make_engine
from app.providers.fake import FailingProvider
from app.tools import add_document, extract_document, record_officer_decision

ROOT = Path(__file__).resolve().parent.parent
ASSESSED = [f"LA-{i:02d}" for i in range(1, 13)]
CITIZEN_DEMO_CASES = ("LA-01", "LA-05", "LA-07", "LA-14")   # approved, sent back, under review, received
DECISIONS = [("LA-01", "approve", "synthetic demo decision (seed script)"),
             ("LA-05", "send_back", "synthetic demo decision (seed script): identity proof expired, upload a valid one")]


class _NoLLM:
    name, model = "none", None

    def complete(self, system, messages, tools):
        raise ProviderError("no agent LLM in the seed script", kind="not_configured")


def _case_ids() -> dict[str, str]:
    return {f.name: json.loads((f / "case.json").read_text(encoding="utf-8"))["case_id"]
            for f in sorted(SET_DIR.glob("case_*"))}


def _read_messy_documents(session: Session) -> None:
    ids = _case_ids()
    labels = json.loads((SET_DIR / "messy_labels.json").read_text(encoding="utf-8"))
    for item in labels["documents"]:
        folder = SET_DIR / item["case"]
        doc = add_document(session, ids[item["case"]], item["doc_type"],
                           str(folder / "documents" / f"{item['doc_type']}.txt"), actor="seed-demo")
        fixture = json.loads((folder / "fake" / f"{item['doc_type']}.json").read_text(encoding="utf-8"))
        provider, ocr = _fake_for(str(doc.id), fixture)
        extract_document(session, doc.id, provider, ocr, actor="seed-demo")


def _unavailable_document(session: Session) -> None:
    doc = add_document(session, "LA-14", "identity_proof",
                       str(SET_DIR / "case_02" / "documents" / "identity_proof.txt"), actor="seed-demo")
    extract_document(session, doc.id, FailingProvider(kind="rate_limited", message="simulated rate limit (seed)"),
                     actor="seed-demo")


def seed(db_path: Path, reset: bool = False, with_decisions: bool = True) -> dict[str, Any]:
    db_path = Path(db_path)
    if db_path.exists():
        if not reset:
            raise FileExistsError(f"{db_path} exists; pass --reset to replace it")
        if db_path.suffix != ".db":
            raise ValueError(f"Refusing to delete {db_path}: --reset only replaces .db files")
        db_path.unlink()
    engine = make_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for folder in sorted(SET_DIR.glob("case_*")):
            seed_case(session, CaseIn.model_validate_json((folder / "case.json").read_text(encoding="utf-8")))
        _read_messy_documents(session)
        _unavailable_document(session)
        for case_id in ASSESSED:
            run_agent(session, case_id, _NoLLM(), actor="seed-demo")
        if with_decisions:
            for case_id, decision, comment in DECISIONS:
                if session.get(Case, case_id).status == "in_officer_review":
                    record_officer_decision(session, case_id, role="officer", officer_id="seed-demo",
                                            decision=decision, comment=comment)
        statuses = [c.status for c in session.query(Case)]
    engine.dispose()
    return {"db": str(db_path), "cases": len(statuses),
            "by_status": {s: statuses.count(s) for s in sorted(set(statuses))},
            "citizen_codes": {ref: citizen_code(ref, citizen_secret()) for ref in CITIZEN_DEMO_CASES}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(ROOT / "govflow.db"))
    parser.add_argument("--reset", action="store_true", help="replace an existing .db file")
    parser.add_argument("--no-decisions", action="store_true", help="do not record seeded officer decisions")
    args = parser.parse_args()
    summary = seed(Path(args.db), reset=args.reset, with_decisions=not args.no_decisions)
    print(f"Seeded {summary['cases']} synthetic cases into {summary['db']}")
    for status, n in summary["by_status"].items():
        print(f"  {status:<18}{n}")
    print("Demo citizen verification codes (public page #/track):")
    for ref, code in summary["citizen_codes"].items():
        print(f"  {ref}: {code}")


if __name__ == "__main__":
    main()
