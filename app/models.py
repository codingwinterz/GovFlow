"""SQLite schema (SPEC section 3). audit_log is append-only, enforced by triggers."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DDL, Engine, ForeignKey, String, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app import audit_chain

CASE_STATUSES = ("received", "extracted", "verified", "assessed",
                 "in_officer_review", "approved", "rejected", "needs_info", "withdrawn")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(ts: datetime) -> datetime:
    """SQLite returns naive datetimes (stored as UTC); new values are aware. Compare them as aware UTC."""
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def iso_utc(ts: datetime) -> str:
    """API form of a timestamp: ISO 8601 in UTC with an explicit Z, so no client has to guess the zone."""
    return as_utc(ts).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# India Standard Time. A fixed offset is exact (no daylight saving since 1945) and needs no tz database,
# which Windows Python lacks without the tzdata package.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def india_date(ts: datetime) -> str:
    """The calendar date of a timestamp as people in India read it: a decision at 00:30 IST is that day."""
    return as_utc(ts).astimezone(IST).date().isoformat()


# Month abbreviations as the browser's en-IN date format writes them ("Sept"), so both sides agree.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")


def india_day(ts: datetime) -> str:
    """The same India date for people to read: "17 Nov 2026" (as the web's formatDay)."""
    d = as_utc(ts).astimezone(IST).date()
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def queue_key(case: "Case") -> tuple[bool, datetime]:
    """Officer queue order: flagged cases first, then oldest submission (or creation) first."""
    return (not case.confidence_flag, as_utc(case.submitted_at or case.created_at))


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scheme: Mapped[str]
    applicant_ref: Mapped[str]
    status: Mapped[str] = mapped_column(default="received")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    officer_id: Mapped[Optional[str]]
    confidence_flag: Mapped[bool] = mapped_column(default=False)   # True = needs human review
    reference_date: Mapped[Optional[date]]                          # date checks compare against this
    inputs_json: Mapped[str] = mapped_column(default="{}")          # officer-entered values (market value, dates)
    submitted_at: Mapped[Optional[datetime]]                        # when it entered the officer queue


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    doc_type: Mapped[str]
    file_path: Mapped[str]
    uploaded_at: Mapped[datetime] = mapped_column(default=_now)
    extraction_status: Mapped[Optional[str]]       # None (not tried) | ok | extraction_unavailable
    extraction_error_kind: Mapped[Optional[str]]   # e.g. rate_limited, timeout (class only, never the message)


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    field: Mapped[str]
    value: Mapped[str]                                   # JSON-encoded so numbers stay numbers
    confidence: Mapped[float]
    source_page: Mapped[Optional[int]]
    method: Mapped[str] = mapped_column(default="seed")  # llm | ocr_fallback | seed
    note: Mapped[Optional[str]]
    review_reason: Mapped[Optional[str]]                 # e.g. "readers disagree": review whatever the confidence


class VerificationFlag(Base):
    __tablename__ = "verification_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    kind: Mapped[str]
    detail: Mapped[str]
    severity: Mapped[str]


class RuleResultRow(Base):
    __tablename__ = "rule_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    rule_id: Mapped[str]
    status: Mapped[str]   # pass | fail | needs_review (SPEC had a boolean `passed`; tri-state needed)
    reason: Mapped[str]
    clause: Mapped[str]
    rules_version: Mapped[str]


class CompensationItemRow(Base):
    __tablename__ = "compensation_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    component: Mapped[str]
    amount: Mapped[float]
    formula_note: Mapped[str]


class DeficiencyNotice(Base):
    """A "documents needed" notice an officer sent. Items are structured (document and field ids); lines are the
    exact text sent, in the chosen language. Kept for the record; the citizen page shows the latest one."""
    __tablename__ = "deficiency_notices"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    language: Mapped[str]
    items_json: Mapped[str]
    lines_json: Mapped[str]
    officer_id: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=_now)
    case_id: Mapped[Optional[str]]
    actor: Mapped[str]
    action: Mapped[str]
    payload_json: Mapped[str]
    rules_version: Mapped[Optional[str]]
    # Hash chain (app/audit_chain.py): set on every new row just before it is written.
    prev_hash: Mapped[Optional[str]]
    row_hash: Mapped[Optional[str]]


APPEND_ONLY_TRIGGERS = {
    op: (f"CREATE TRIGGER audit_log_no_{op.lower()} BEFORE {op} ON audit_log "
         "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;")
    for op in ("UPDATE", "DELETE")
}
for _sql in APPEND_ONLY_TRIGGERS.values():
    event.listen(AuditLog.__table__, "after_create", DDL(_sql))


@event.listens_for(Session, "before_flush")
def _chain_audit_rows(session: Session, _flush_context: object, _instances: object) -> None:
    """Every AuditLog row, however it was added, gets its place in the chain before it is inserted."""
    new = sorted((o for o in session.new if isinstance(o, AuditLog)), key=lambda o: inspect(o).insert_order)
    if not new:
        return
    for row in new:
        if row.ts is None:
            row.ts = _now()
    audit_chain.chain_new_rows(session.connection(), new)


def _add_missing_columns(engine: Engine) -> None:
    """Columns added after a database was created (no migrations in this prototype): add them, nullable."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(extracted_fields)")}
        if "review_reason" not in columns:
            conn.exec_driver_sql("ALTER TABLE extracted_fields ADD COLUMN review_reason VARCHAR")
        audit_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(audit_log)")}
        for name in ("prev_hash", "row_hash"):
            if name not in audit_columns:
                conn.exec_driver_sql(f"ALTER TABLE audit_log ADD COLUMN {name} VARCHAR")
        audit_chain.backfill(conn, APPEND_ONLY_TRIGGERS)


def make_engine(url: str = "sqlite:///govflow.db") -> Engine:
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def make_session(engine: Engine) -> Session:
    return Session(engine)
