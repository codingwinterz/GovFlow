"""Input shape of a case as the tools see it (independent of the database)."""

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel


class FieldValue(BaseModel):
    value: Any
    confidence: float = 1.0
    source_page: Optional[int] = None


class DocumentIn(BaseModel):
    fields: dict[str, FieldValue] = {}
    extraction_unavailable: bool = False   # latest extraction attempt failed; retry


class CaseIn(BaseModel):
    case_id: str
    scheme: str
    reference_date: date               # all date checks compare against this, so tests are repeatable
    status: str = "received"
    documents: dict[str, DocumentIn]   # keyed by document type id from the scheme YAML
    inputs: dict[str, Any] = {}        # officer-entered values, e.g. market_value_per_sqm
