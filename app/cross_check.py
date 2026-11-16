"""Cross-check: a second, independent reader (Tesseract) reads the same document.

When both readers return a value for a field and the values differ after normalisation, the field goes to human
review with the reason "readers disagree", however confident the first reader was. A model's self-reported
confidence cannot vouch for itself; a disagreement between two different readers is evidence.

Normalisation, by the field's declared type: text ignores case and spacing; numbers ignore digit grouping
(1,20,000 = 120000); dates accept ISO and day-first forms (01/10/2026 = 2026-10-01); units compare by their
conversion factor, so synonyms agree (sq. m. = sqm). A field the second reader did not return is not checked.
"""

import re
from datetime import date
from typing import Any

from app.field_types import coerce
from app.units import UnknownUnit, to_sqm

READERS_DISAGREE = "readers disagree"
_DAY_FIRST = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


def _text(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def canonical(field_type: str, value: Any) -> str:
    """One spelling per meaning. A value that cannot be read as its type falls back to its normalised text."""
    if field_type in ("number", "percent"):
        number, error = coerce(field_type, value)
        return f"number:{number:g}" if error is None else _text(value)
    if field_type == "date":
        parsed, error = coerce("date", value)
        if error is None:
            return parsed.isoformat()
        m = _DAY_FIRST.match(_text(value))
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                pass
        return _text(value)
    if field_type == "unit":
        try:
            return f"unit:{to_sqm(1.0, str(value)):.12g}"
        except UnknownUnit:
            return _text(value)
    return _text(value)


def readers_disagree(field_type: str, first: Any, second: Any) -> bool:
    return canonical(field_type, first) != canonical(field_type, second)
