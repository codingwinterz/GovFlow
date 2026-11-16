"""Build a demo database from the synthetic sets of every scheme (no network, no LLM).

- every synthetic case in data/synthetic/<scheme>/ is seeded (fields from case.json);
- the land-acquisition messy documents are re-read with their recorded fake responses, so
  low-confidence fields and the OCR fallback appear on the case page;
- one document is "uploaded" and fails with a simulated rate limit, to demo the retry banner;
- most cases go through the agent's deterministic fallback (no LLM), so each has an assessment
  and a plain summary clearly labelled "generated without the LLM";
- intake and submission dates are SYNTHETIC: spread over recent weeks by a fixed pattern, so SLA timers and
  overdue flags have something to show (audit entries keep their real timestamps);
- three officer decisions are recorded as actor officer:seed-demo with a "synthetic" comment,
  so analytics and the citizen page have data (skip with --no-decisions).

Usage: python -m scripts.seed_demo [--db govflow.db] [--reset] [--no-decisions]
"""

import argparse
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agent import run_agent
from app.case_model import CaseIn
from app.case_store import seed_case
from app.auth import AUTH_ENV
from app.citizen import SECRET_ENV, citizen_code
from app.env_file import env_value
from app.evaluation import SET_DIR, _fake_for
from app.extraction import ProviderError
from app.models import Case, make_engine
from app.providers.fake import FailingProvider
from app.tools import add_document, amount_field_values, extract_document, record_officer_decision

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"
NOT_RUN = ("LA-13", "LA-14", "LA-15", "DR-13", "DR-14")     # left as received / extracted
CITIZEN_DEMO_CASES = ("LA-01", "LA-05", "LA-07", "LA-14", "DR-01", "DR-08")
DECISIONS = [("LA-01", "approve", "synthetic demo decision (seed script)"),
             ("LA-05", "send_back", "synthetic demo decision (seed script): identity proof expired, upload a valid one"),
             ("DR-01", "approve", "synthetic demo decision (seed script)")]
INTAKE_DAYS_AGO = [3, 8, 12, 20, 27, 35, 41, 48, 55, 62, 66, 70, 74, 80, 85]   # synthetic, by case order


class _NoLLM:
    name, model = "none", None

    def complete(self, system, messages, tools):
        raise ProviderError("no agent LLM in the seed script", kind="not_configured")


def _all_cases() -> list[CaseIn]:
    return [CaseIn.model_validate_json(p.read_text(encoding="utf-8"))
            for scheme in sorted(d for d in DATA.iterdir() if d.is_dir())
            for p in sorted(scheme.glob("case_*/case.json"))]


def _read_messy_documents(session: Session) -> None:
    ids = {f.name: json.loads((f / "case.json").read_text(encoding="utf-8"))["case_id"]
           for f in sorted(SET_DIR.glob("case_*"))}
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


def _spread_intake_dates(session: Session, cases: list[CaseIn]) -> None:
    now = datetime.now(timezone.utc)
    per_scheme: dict[str, int] = {}
    for case in cases:
        i = per_scheme[case.scheme] = per_scheme.get(case.scheme, -1) + 1
        days = INTAKE_DAYS_AGO[i % len(INTAKE_DAYS_AGO)]
        if case.scheme == "disaster_relief":
            days = days // 3 + 1                      # relief cases are more recent
        session.get(Case, case.case_id).created_at = now - timedelta(days=days)
    session.commit()


def _backdate_submissions(session: Session) -> None:
    """The agent stamps submitted_at with the real clock; in the synthetic timeline the case went to the
    officer on its (backdated) intake date, so "Submitted" and "Days open" agree in the queue."""
    for case in session.query(Case).filter(Case.submitted_at.isnot(None)):
        case.submitted_at = case.created_at
    session.commit()


def ensure_dotenv_secret(dotenv: Path, name: str) -> tuple[str, bool]:
    """A demo secret (citizen codes, sign-in tokens): the configured one, else a new random one appended to
    `dotenv` (gitignored). Returns (secret, created). Random per machine, never in the source."""
    existing = env_value(name, dotenv)
    if existing:
        return existing, False
    secret = secrets.token_urlsafe(32)
    text = dotenv.read_text(encoding="utf-8") if dotenv.is_file() else ""
    sep = "" if not text or text.endswith("\n") else "\n"
    dotenv.write_text(f"{text}{sep}{name}={secret}\n", encoding="utf-8")
    return secret, True


def seed(db_path: Path, reset: bool = False, with_decisions: bool = True,
         code_secret: Optional[str] = None) -> dict[str, Any]:
    db_path = Path(db_path)
    if db_path.exists():
        if not reset:
            raise FileExistsError(f"{db_path} exists; pass --reset to replace it")
        if db_path.suffix != ".db":
            raise ValueError(f"Refusing to delete {db_path}: --reset only replaces .db files")
        db_path.unlink()
    engine = make_engine(f"sqlite:///{db_path}")
    cases = _all_cases()
    with Session(engine) as session:
        for case in cases:
            seed_case(session, case)
        _spread_intake_dates(session, cases)
        _read_messy_documents(session)
        _unavailable_document(session)
        for case in cases:
            if case.case_id not in NOT_RUN:
                run_agent(session, case.case_id, _NoLLM(), actor="seed-demo")
        _backdate_submissions(session)
        if with_decisions:
            for case_id, decision, comment in DECISIONS:
                if session.get(Case, case_id).status == "in_officer_review":
                    record_officer_decision(session, case_id, role="officer", officer_id="seed-demo",
                                            decision=decision, comment=comment,   # demo: values match the documents
                                            confirmed=amount_field_values(session, case_id))
        statuses = [c.status for c in session.query(Case)]
    engine.dispose()
    return {"db": str(db_path), "cases": len(statuses),
            "by_status": {s: statuses.count(s) for s in sorted(set(statuses))},
            "citizen_codes": ({ref: citizen_code(ref, code_secret) for ref in CITIZEN_DEMO_CASES} if code_secret else {})}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(ROOT / "govflow.db"))
    parser.add_argument("--reset", action="store_true", help="replace an existing .db file")
    parser.add_argument("--no-decisions", action="store_true", help="do not record seeded officer decisions")
    args = parser.parse_args()
    secret, created = ensure_dotenv_secret(ROOT / ".env", SECRET_ENV)
    _, auth_created = ensure_dotenv_secret(ROOT / ".env", AUTH_ENV)
    summary = seed(Path(args.db), reset=args.reset, with_decisions=not args.no_decisions, code_secret=secret)
    print(f"Seeded {summary['cases']} synthetic cases into {summary['db']}")
    for status, n in summary["by_status"].items():
        print(f"  {status:<18}{n}")
    for made, name in ((created, SECRET_ENV), (auth_created, AUTH_ENV)):
        if made:
            print(f"Wrote a new random {name} to .env (gitignored); the API reads it at start-up.")
    print("Demo citizen verification codes (public page #/citizen/track):")
    for ref, code in summary["citizen_codes"].items():
        print(f"  {ref}: {code}")


if __name__ == "__main__":
    main()
