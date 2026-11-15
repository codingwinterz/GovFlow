"""Typed document fields. Extraction returns strings; this turns them into the declared type once,
before any rule, check or formula reads them. Strict on purpose: anything not clearly a value of the
type is rejected with a reason (and routed to human review), never repaired or guessed."""

import math
import re
from datetime import date, datetime
from typing import Any, Literal, Optional

from app.units import UnknownUnit, to_sqm

FieldType = Literal["text", "number", "percent", "date", "unit"]
FIELD_TYPES: tuple[str, ...] = ("text", "number", "percent", "date", "unit")

_FRACTION = r"(\.\d+)?"
_PLAIN_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_WESTERN_GROUPED = re.compile(r"[+-]?\d{1,3}(,\d{3})+" + _FRACTION)          # 100,000  1,234,567
_INDIAN_GROUPED = re.compile(r"[+-]?\d{1,2}(,\d{2})*,\d{3}" + _FRACTION)    # 1,00,000  12,34,567
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
    if _WESTERN_GROUPED.fullmatch(text) or _INDIAN_GROUPED.fullmatch(text):
        return float(text.replace(",", "")), None
    return None, (f"{value!r} is not a plain number (digits, an optional decimal point, and only "
                  "valid Indian or Western digit grouping)")


def _percent(value: Any) -> Coerced:
    text = str(value).strip() if isinstance(value, str) else value
    if isinstance(text, str) and text.endswith("%"):
        text = text[:-1].rstrip()
    number, error = _number(text) if text != "" else (None, "empty")
    if error:
        return None, f"{value!r} is not a percentage (a number with an optional trailing %)"
    return number, None


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
    if field_type == "percent":
        return _percent(value)
    if field_type == "date":
        return _date(value)
    if field_type == "unit":
        return _unit(value)
    return str(value).strip(), None
