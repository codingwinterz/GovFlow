"""Mask Aadhaar-like 12-digit identifiers before anything is logged or shown (CLAUDE.md rule 7)."""

import re
from typing import Any

_ID_PATTERN = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?(\d{4})(?!\d)")


def mask_identifiers(value: Any) -> Any:
    if isinstance(value, str):
        return _ID_PATTERN.sub(lambda m: f"XXXX XXXX {m.group(1)}", value)
    if isinstance(value, dict):
        return {k: mask_identifiers(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_identifiers(v) for v in value]
    return value
