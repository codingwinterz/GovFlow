"""Typed document fields. Extraction returns strings; this turns them into the declared type once,
before any rule, check or formula reads them. Strict on purpose: anything not clearly a value of the
type is rejected with a reason (and routed to human review), never repaired or guessed."""

import math
import re
from datetime import date, datetime
from typing import Any, Literal, Optional

from app.units import UnknownUnit, to_sqm

FieldType = Literal["text", "number", "date", "unit"]
FIELD_TYPES: tuple[str, ...] = ("text", "number", "date", "unit")

_PLAIN_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

Coerced = tuple[Optional[Any], Optional[str]]   # (value, None) or (None, reason)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value: Any) -> Coerced:
    if isinstance(value, bool):
        return None, f"{value!r} is not a plain number"
    if isinstance(value, (int, float)):
        return (float(value), None) if math.isfinite(value) else (None, f"{value!r} is not a plain number")
    text = str(value).strip()
    if _PLAIN_NUMBER.fullmatch(text):
        return float(text), None
    return None, f"{value!r} is not a plain number (digits and an optional decimal point only)"


def _date(value: Any) -> Coerced:
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    text = str(value).strip()
    if _ISO_DATE.fullmatch(text):
        try:
            return date.fromisoformat(text), None
        except ValueError:
            pass
    return None, f"{value!r} is not an ISO date (YYYY-MM-DD)"


def _unit(value: Any) -> Coerced:
    text = str(value).strip()
    try:
        to_sqm(1.0, text)
    except UnknownUnit:
        return None, f"{value!r} is not a known area unit"
    return text, None


def coerce(field_type: str, value: Any) -> Coerced:
    if _blank(value):
        return None, "empty value"
    if field_type == "number":
        return _number(value)
    if field_type == "date":
        return _date(value)
    if field_type == "unit":
        return _unit(value)
    return str(value).strip(), None
