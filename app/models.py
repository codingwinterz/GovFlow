"""SQLite schema (SPEC section 3). audit_log is append-only, enforced by triggers."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import DDL, Engine, ForeignKey, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

CASE_STATUSES = ("received", "extracted", "verified", "assessed",
                 "in_officer_review", "approved", "rejected", "needs_info")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    doc_type: Mapped[str]
    file_path: Mapped[str]
    uploaded_at: Mapped[datetime] = mapped_column(default=_now)


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


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=_now)
    case_id: Mapped[Optional[str]]
    actor: Mapped[str]
    action: Mapped[str]
    payload_json: Mapped[str]
    rules_version: Mapped[Optional[str]]


for _op in ("UPDATE", "DELETE"):
    event.listen(AuditLog.__table__, "after_create", DDL(
        f"CREATE TRIGGER audit_log_no_{_op.lower()} BEFORE {_op} ON audit_log "
        "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;"
    ))


def make_engine(url: str = "sqlite:///govflow.db") -> Engine:
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


def make_session(engine: Engine) -> Session:
    return Session(engine)
