"""Typed document fields. Extraction returns strings; this turns them into the declared type once,
before any rule, check or formula reads them. Strict on purpose: anything not clearly a value of the
type is rejected with a reason (and routed to human review), never repaired or guessed."""

import math
import re
from datetime import date, datetime
from typing import Any, Literal, Optional

from app.units import UnknownUnit, to_sqm

FieldType = Literal["text", "number", "percent", "date", "unit", "one_of"]
FIELD_TYPES: tuple[str, ...] = ("text", "number", "percent", "date", "unit", "one_of")

_FRACTION = r"(\.\d+)?"
_PLAIN_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_WESTERN_GROUPED = re.compile(r"[+-]?\d{1,3}(,\d{3})+" + _FRACTION)          # 100,000  1,234,567
_INDIAN_GROUPED = re.compile(r"[+-]?\d{1,2}(,\d{2})*,\d{3}" + _FRACTION)    # 1,00,000  12,34,567
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DAY_FIRST_DATE = re.compile(r"(\d{1,2})([/.-])(\d{1,2})\2(\d{4})")   # DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY

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
    if not 0 <= number <= 100:
        return None, f"{value!r} is outside 0-100"
    return number, None


def _date(value: Any) -> Coerced:
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    text = str(value).strip()
    try:
        if _ISO_DATE.fullmatch(text):
            return date.fromisoformat(text), None
        m = _DAY_FIRST_DATE.fullmatch(text)
        if m:   # Goa documents print dates day first: 01/10/2026 is 1 October, never 10 January
            return date(int(m.group(4)), int(m.group(3)), int(m.group(1))), None
    except ValueError:
        pass    # e.g. 01/13/2026 (only valid month first) or 31/02/2026: rejected, never swapped
    return None, f"{value!r} is not a date (YYYY-MM-DD, or day first DD/MM/YYYY)"


def _unit(value: Any) -> Coerced:
    text = str(value).strip()
    try:
        to_sqm(1.0, text)
    except UnknownUnit:
        return None, f"{value!r} is not a known area unit"
    return text, None


def _one_of(value: Any, options: list[str]) -> Coerced:
    """One of the scheme's listed values, matched ignoring case and spacing; returns the listed spelling."""
    key = " ".join(str(value).split()).casefold()
    for option in options:
        if key == option.casefold():
            return option, None
    return None, f"{value!r} is not one of {', '.join(options)}"


def coerce(field_type: str, value: Any, options: Optional[list[str]] = None) -> Coerced:
    if _blank(value):
        return None, "empty value"
    if field_type == "one_of":
        return _one_of(value, options or [])
    if field_type == "number":
        return _number(value)
    if field_type == "percent":
        return _percent(value)
    if field_type == "date":
        return _date(value)
    if field_type == "unit":
        return _unit(value)
    return str(value).strip(), None
