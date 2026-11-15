"""Mask Aadhaar-like identifiers (CLAUDE.md rule 7) and redact API keys before anything is logged or shown."""

import os
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


_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),         # Google API key
    re.compile(r"\bAQ\.[0-9A-Za-z_\-]{20,}"),       # Google API key, newer format
    re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}"),     # Anthropic API key
]
_SECRET_ENV_VARS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")


def redact_secrets(value: Any) -> Any:
    """Replace API-key-shaped strings, and the configured keys themselves, with [redacted]."""
    if isinstance(value, str):
        for name in _SECRET_ENV_VARS:
            key = os.environ.get(name)
            if key and len(key) >= 8:
                value = value.replace(key, "[redacted]")
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub("[redacted]", value)
        return value
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_secrets(v) for v in value]
    return value
